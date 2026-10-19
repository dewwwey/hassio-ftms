"""Timestamped FTMS observations and private durable journal."""
import asyncio
import json
import logging
import os
import hashlib
from datetime import timedelta
from pathlib import Path
from time import time

from homeassistant.core import callback
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from .sessions import Sessions
from .finish import finish_workout, ControlPointOwner
from homeassistant.exceptions import HomeAssistantError
from .intensity_target import encode_bounded_target

_LOGGER = logging.getLogger(__name__)
FRESH_SECONDS = 10
ACTIVITY_RESUME_SECONDS = 30


class DataCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, ftms, source):
        super().__init__(hass, _LOGGER, name="ftms")
        self.ftms = ftms
        self.source = source
        self.last_received = None
        self.field_times = {}
        self.values = {}
        self.observed = set()
        self.sessions = Sessions(source)
        self.storage_error = None
        self.path = Path(hass.config.path(".storage", "ftms", source + ".jsonl"))
        self.queue = asyncio.Queue(maxsize=1000)
        self.worker = None
        self.closed = False
        self.cancel_watchdog = None
        self.reloading = False
        self.idle_recorded = False
        self.pending_storage_gap = False
        self.cancel_reload = None
        self.stable_since = None
        self.finish_lock = asyncio.Lock()
        self.control_owner = ControlPointOwner()
        self.target_values = {}
        self.latest_event = None
        self.activity_active = False
        self.last_journal_received = None
        self.last_persisted_ts = None
        self.activity_inactive_since = None

        @callback
        def event(e):
            if self.closed:
                return
            if e.event_id == "stop":
                self.record({"kind": "finish", "ts": time(), "reason": "machine_stop"})
                self.async_update_listeners()
                return
            if e.event_id != "update":
                return
            if "packet_error" in e.event_data:
                self.record({"kind": "malformed_packet", "ts": time()})
                return
            metrics = {k: v for k, v in e.event_data.items() if k != "rssi" and v is not None}
            # A bike without an attached HR source commonly transmits zero.
            if "heart_rate" in metrics and not 0 < metrics["heart_rate"] < 255:
                metrics.pop("heart_rate")
                self.field_times.pop("heart_rate", None)
                self.values.pop("heart_rate", None)
            # Status notifications do not prove realtime measurements are fresh.
            if not any(k in metrics for k in ("speed_instant", "cadence_instant", "power_instant", "time_elapsed")):
                return
            now = time()
            if self.last_received is None or now - self.last_received > FRESH_SECONDS:
                self.stable_since = now
            if self.stable_since is not None and now - self.stable_since >= 60:
                self.hass.data.setdefault("ftms_retry", {})[self.source] = 0
            self.last_received = now
            self.values.update(metrics)
            self.observed.update(metrics)
            self.field_times.update({k: now for k in metrics})
            active = metrics.get("cadence_instant", 0) > 0
            new_activity = active and not self.activity_active
            had_session = self.sessions.current is not None
            inactive_since = self.activity_inactive_since
            if (self.sessions.current or metrics.get("cadence_instant", 0) > 0
                    or not self.idle_recorded or self.sessions.awaiting_idle_after_finish):
                self.record({"kind": "sample", "ts": now, "metrics": metrics})
                self.last_journal_received = now
                self.idle_recorded = metrics.get("cadence_instant") == 0
            elif self.last_journal_received is None or now - self.last_journal_received >= 30:
                self.record({"kind": "heartbeat", "ts": now, "last_received_ts": now})
                self.last_journal_received = now
            if new_activity and self.sessions.current:
                resumed = (had_session and inactive_since is not None
                           and now - inactive_since >= ACTIVITY_RESUME_SECONDS)
                kind = "activity_resumed" if resumed else "activity_started" if not had_session else None
            else:
                kind = None
            if kind:
                identity = f"ftms:event:v1:{self.source}:{kind}:{now:.6f}"
                session = self.sessions.current
                self.record({"kind": kind, "ts": now,
                             "event_id": hashlib.sha256(identity.encode()).hexdigest()[:24],
                             "session_id": session["session_id"] if session else None})
            if "cadence_instant" in metrics:
                self.activity_active = active
                self.activity_inactive_since = None if active else (inactive_since or now)
            self.async_set_updated_data(e)
        ftms.set_callback(event)

    async def async_finish_workout(self):
        requested = self.sessions.current["session_id"] if self.sessions.current else None
        async with self.finish_lock:
            if self.closed or not self.ftms.is_connected:
                raise HomeAssistantError("Bike is not connected")
            current = self.sessions.current["session_id"] if self.sessions.current else None
            if current != requested:
                raise HomeAssistantError("Workout changed while the finish request was waiting; try again")
            def finish_still_current():
                current_id = self.sessions.current["session_id"] if self.sessions.current else None
                return not self.closed and current_id == requested

            try:
                # No reconnect, reset, resistance or other application writes here.
                await finish_workout(self.ftms._cli, owner=self.control_owner, authorize=finish_still_current)
            except Exception as exc:
                self.record({"kind": "command_result", "ts": time(), "command": "finish_workout",
                             "success": False, "error_type": type(exc).__name__})
                raise HomeAssistantError(f"Bike did not confirm Finish workout: {exc}") from exc
            self.record({"kind": "finish", "ts": time(), "reason": "ha_finish_acknowledged"})
            self.async_update_listeners()
            await self.queue.join()
            return {"success": True, "connected": self.ftms.is_connected,
                    "session_id": requested, "command": "finish_workout"}

    async def async_set_target(self, setting, value):
        """Set a user-requested FTMS target within the machine's advertised range."""
        if setting not in ("target_resistance", "target_power"):
            raise HomeAssistantError("Unsupported FTMS intensity target")
        machine_range = self.ftms.supported_ranges.get(setting)
        if setting not in self.ftms.supported_settings or machine_range is None:
            raise HomeAssistantError("Bike does not advertise this target")
        if self.closed or not self.ftms.is_connected or not self.fresh:
            raise HomeAssistantError("Bike is disconnected or telemetry is stale")
        range_values = machine_range._asdict()
        try:
            payload = encode_bounded_target(setting, value, range_values, {
                "min_value": machine_range.min_value,
                "max_value": machine_range.max_value,
            })
        except (TypeError, ValueError) as exc:
            raise HomeAssistantError(f"Invalid FTMS target: {exc}") from exc

        expected_session = self.sessions.current["session_id"] if self.sessions.current else None

        def authorize():
            current_session = self.sessions.current["session_id"] if self.sessions.current else None
            return (
                not self.closed and self.ftms.is_connected and self.fresh
                and setting in self.ftms.supported_settings
                and self.ftms.supported_ranges.get(setting) == machine_range
                and current_session == expected_session
            )

        requested_value = float(value)
        try:
            await self.control_owner.target(
                self.ftms._cli, payload, authorize=authorize,
            )
        except Exception as exc:
            self.record({"kind": "command_result", "ts": time(), "command": setting,
                         "target": requested_value, "success": False,
                         "error_type": type(exc).__name__})
            await self.queue.join()
            raise HomeAssistantError(f"Bike did not confirm {setting}: {exc}") from exc
        self.target_values[setting] = requested_value
        self.record({"kind": "command_result", "ts": time(), "command": setting,
                     "target": requested_value, "success": True})
        self.async_update_listeners()
        await self.queue.join()

    def _replay(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            # Only an incomplete final write is recoverable. Preserve corruption evidence.
            raw = self.path.read_bytes()
            lines = raw.splitlines(keepends=True)
            if lines and not lines[-1].endswith(b"\n"):
                tail = lines.pop()
                self.path.with_suffix(".truncated").write_bytes(tail)
                with self.path.open("r+b") as stream:
                    stream.truncate(len(raw) - len(tail))
                self.storage_error = "recovered_truncated_tail"
            for line in lines:
                record = json.loads(line)
                self.sessions.apply(record)
                self.last_persisted_ts = record["ts"]
                if record["kind"] in ("activity_started", "activity_resumed"):
                    self.latest_event = record
                if record["kind"] in ("disconnect", "restart"):
                    self.activity_inactive_since = record["ts"]
                elif record["kind"] == "sample" and "cadence_instant" in record.get("metrics", {}):
                    if record["metrics"]["cadence_instant"] > 0:
                        self.activity_inactive_since = None
                    elif self.activity_inactive_since is None:
                        self.activity_inactive_since = record["ts"]
        self.activity_active = bool(self.sessions.current and self.activity_inactive_since is None)
        if self.storage_error and self.sessions.current:
            self.sessions.apply({"kind": "storage_gap", "ts": time()})

    async def open_journal(self):
        await self.hass.async_add_executor_job(self._replay)
        self.worker = asyncio.create_task(self._writer())
        if self.sessions.current:
            now = time()
            self.activity_active = False
            self.activity_inactive_since = self.activity_inactive_since or now
            self.record({"kind": "restart", "ts": now})

    def _append(self, record):
        payload = json.dumps(record, separators=(",", ":"), default=lambda v: v.value) + "\n"
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

    async def _writer(self):
        while True:
            record = await self.queue.get()
            try:
                if record is None:
                    return
                if self.pending_storage_gap:
                    await self.hass.async_add_executor_job(self._append, {"kind": "storage_gap", "ts": record["ts"]})
                    self.pending_storage_gap = False
                if (record["kind"] in ("activity_started", "activity_resumed")
                        and self.storage_error is not None):
                    # FIFO ordering only proves the triggering sample was
                    # fsynced if preceding writes/queueing remained healthy.
                    # Retain the fault evidence without publishing a wake.
                    record = {"kind": "activity_event_suppressed", "ts": record["ts"],
                              "reason": "unhealthy_recording"}
                await self.hass.async_add_executor_job(self._append, record)
                self.last_persisted_ts = record["ts"]
                if record["kind"] in ("activity_started", "activity_resumed"):
                    self.latest_event = record
                    self.hass.bus.async_fire("ftms_activity", {"config_entry_id": self.source, **record})
                    self.async_update_listeners()
            except OSError as exc:
                self.storage_error = type(exc).__name__
                self.pending_storage_gap = True
                if self.sessions.current:
                    self.sessions.apply({"kind": "storage_gap", "ts": time()})
                _LOGGER.error("FTMS journal write failed: %s", type(exc).__name__)
            finally:
                self.queue.task_done()

    @callback
    def record(self, record):
        try:
            self.queue.put_nowait(record)
        except asyncio.QueueFull:
            self.storage_error = "queue_full"
            self.pending_storage_gap = True
            self.sessions.apply({"kind": "storage_gap", "ts": record["ts"]})
        self.sessions.apply(record)

    @callback
    def disconnected(self):
        if not self.closed:
            self.activity_active = False
            now = time()
            self.activity_inactive_since = self.activity_inactive_since or now
            self.record({"kind": "disconnect", "ts": now, "last_received_ts": self.last_received})
            self.async_update_listeners()

    @property
    def fresh(self):
        return self.ftms.is_connected and self.last_received is not None and time() - self.last_received <= FRESH_SECONDS

    def field_fresh(self, key):
        return self.fresh and time() - self.field_times.get(key, 0) <= FRESH_SECONDS

    @callback
    def request_reconnect(self, entry):
        if self.closed or self.reloading:
            return
        self.reloading = True
        counts = self.hass.data.setdefault("ftms_retry", {})
        failures = counts.get(self.source, 0)
        counts[self.source] = failures + 1
        delay = min(300, 5 * 2 ** min(failures, 6))

        @callback
        def reload_entry(now):
            self.cancel_reload = None
            if not self.closed:
                self.hass.config_entries.async_schedule_reload(entry.entry_id)

        self.cancel_reload = async_call_later(self.hass, delay, reload_entry)

    def start_watchdog(self, entry):
        started = time()

        @callback
        def tick(now):
            if self.sessions.current:
                self.record({"kind": "tick", "ts": time()})
            self.async_update_listeners()
            age = time() - (self.last_received or started)
            if self.ftms.is_connected and age > 30 and not self.reloading:
                self.request_reconnect(entry)
                self.hass.async_create_task(self.ftms.disconnect())
        self.cancel_watchdog = async_track_time_interval(self.hass, tick, timedelta(seconds=5))

    async def close(self):
        if self.closed:
            return
        self.closed = True
        if self.cancel_watchdog:
            self.cancel_watchdog()
        if self.cancel_reload:
            self.cancel_reload()
        self.ftms.set_callback(None)
        if self.worker:
            await self.queue.join()
            await self.queue.put(None)
            await self.worker
