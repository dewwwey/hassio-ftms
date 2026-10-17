"""Timestamped FTMS observations and private durable journal."""
import asyncio
import json
import logging
import os
from datetime import timedelta
from pathlib import Path
from time import time

from homeassistant.core import callback
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from .sessions import Sessions

_LOGGER = logging.getLogger(__name__)
FRESH_SECONDS = 10


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

        @callback
        def event(e):
            if self.closed or e.event_id != "update":
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
            if self.sessions.current or metrics.get("cadence_instant", 0) > 0 or not self.idle_recorded:
                self.record({"kind": "sample", "ts": now, "metrics": metrics})
                self.idle_recorded = metrics.get("cadence_instant") == 0
            self.async_set_updated_data(e)
        ftms.set_callback(event)

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
                self.sessions.apply(json.loads(line))
        if self.storage_error and self.sessions.current:
            self.sessions.apply({"kind": "storage_gap", "ts": time()})

    async def open_journal(self):
        await self.hass.async_add_executor_job(self._replay)
        self.worker = asyncio.create_task(self._writer())
        if self.sessions.current:
            self.record({"kind": "restart", "ts": time()})

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
                await self.hass.async_add_executor_job(self._append, record)
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
            self.record({"kind": "disconnect", "ts": time()})
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
        self.cancel_reload = async_call_later(
            self.hass, delay,
            lambda now: self.hass.config_entries.async_schedule_reload(entry.entry_id),
        )

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
