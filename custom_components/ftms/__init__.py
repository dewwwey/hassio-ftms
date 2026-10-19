"""Observed FTMS telemetry with an explicit, narrowly scoped Finish action."""
import asyncio
import json
from pathlib import Path
import voluptuous as vol
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant, SupportsResponse, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from ._vendor import pyftms
from .coordinator import DataCoordinator
from .models import FtmsData
from .sessions import completed_sessions
from .observations import read_page, read_snapshot

PLATFORMS = [Platform.SENSOR, Platform.BUTTON, Platform.NUMBER]
type FtmsConfigEntry = ConfigEntry[FtmsData]


def _control_scope(ftms):
    """Report only controls supported by the current live connection."""
    scope = ["finish_workout"]
    if ftms and ftms.is_connected:
        for setting in ("target_resistance", "target_power"):
            if setting in ftms.supported_settings and setting in ftms.supported_ranges:
                scope.append(setting)
    return scope


async def async_setup(hass, config):
    def resolve(call):
        entry = hass.config_entries.async_get_entry(call.data["config_entry_id"])
        if entry is None or entry.domain != "ftms":
            raise HomeAssistantError("Unknown FTMS config entry")
        runtime = getattr(entry, "runtime_data", None)
        coordinator = runtime.coordinator if runtime and not runtime.coordinator.closed else None
        return entry, coordinator, Path(hass.config.path(".storage", "ftms", entry.entry_id + ".jsonl"))

    async def flush(coordinator):
        if coordinator:
            if coordinator.worker is None or coordinator.worker.done():
                return "writer_not_running"
            try:
                async with asyncio.timeout(5):
                    await coordinator.queue.join()
            except TimeoutError:
                return "flush_timeout"
            return coordinator.storage_error
        return "entry_not_loaded"

    async def get_status(call):
        entry, c, path = resolve(call)
        error = await flush(c)
        if c:
            connected, fresh = c.ftms.is_connected, c.fresh
            snapshot = {"last_received_ts": c.last_received, "latest_event": c.latest_event}
            snapshot.update(current_session=c.sessions.current, last_session=c.sessions.last,
                            completed_count=c.sessions.completed_count,
                            observed_metrics=sorted(c.observed), observed_metrics_scope="connection")
            session = c.sessions.current or c.sessions.last
            snapshot["last_activity_ts"] = session["last_activity"] if session else None
            state = c.sessions.status if fresh else "stale" if connected else "disconnected"
        else:
            connected, fresh, state = False, False, "disconnected"
            def recover():
                stat = path.stat() if path.exists() else None
                signature = (stat.st_mtime_ns, stat.st_size) if stat else None
                cache = hass.data.setdefault("ftms_offline_snapshots", {})
                previous = cache.get(entry.entry_id)
                if previous is None or previous[0] != signature:
                    cache[entry.entry_id] = (signature, read_snapshot(path, entry.entry_id))
                return cache[entry.entry_id][1]
            try:
                snapshot = await hass.async_add_executor_job(recover)
            except (OSError, ValueError, KeyError) as exc:
                error = type(exc).__name__
                snapshot = {"last_received_ts": None, "last_activity_ts": None,
                            "last_persisted_ts": None, "latest_event": None}
        return {"schema_version": 2, "state": state, "connected": connected, "fresh": fresh,
                "recording_ready": fresh and error is None, "storage_error": error, **snapshot,
                "last_persisted_ts": c.last_persisted_ts if c else snapshot.get("last_persisted_ts"),
                "hr_validation": "unvalidated", "hr_source": "bike_ftms_heart_rate",
                "supported_settings": list(c.ftms.supported_settings) if c and connected else [],
                "supported_ranges": {k: r._asdict() for k, r in c.ftms.supported_ranges.items()} if c and connected else {},
                "control_scope": _control_scope(c.ftms if c else None), "automatic_control": False}

    async def get_observations(call):
        entry, c, path = resolve(call)
        error = await flush(c)
        try:
            page = await hass.async_add_executor_job(
                read_page, path, entry.entry_id, call.data.get("cursor"), call.data["limit"])
        except (OSError, ValueError) as exc:
            raise HomeAssistantError(f"Observation read failed: {exc}") from exc
        return {"schema_version": 2, "records_schema_version": 1, "telemetry_observed": True,
                "storage_error": error, "hr_validation": "unvalidated",
                "units": {"cadence_instant": "rpm", "power_instant": "W", "speed_instant": "km/h",
                          "distance_total": "m", "time_elapsed": "s", "heart_rate": "bpm",
                          "resistance_level": "device level"}, **page}

    async def get_sessions(call):
        entry_id = call.data["config_entry_id"]
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != "ftms":
            raise ValueError("Unknown FTMS config entry")
        _, coordinator, _ = resolve(call)
        error = await flush(coordinator)
        path = Path(hass.config.path(".storage", "ftms", entry_id + ".jsonl"))

        def read():
            if not path.exists():
                return []
            with path.open(encoding="utf-8") as stream:
                records = [json.loads(line) for line in stream if line.endswith("\n")]
            return completed_sessions(records, entry_id)

        sessions = await hass.async_add_executor_job(read)
        offset, limit = call.data["offset"], call.data["limit"]
        storage_error = error
        return {"schema_version": 2, "read_only": False, "telemetry_observed": True,
                "automatic_control": False, "control_scope": _control_scope(coordinator.ftms if coordinator else None),
                "storage_error": storage_error, "total": len(sessions),
                "sessions": sessions[offset:offset + limit],
                "has_more": offset + limit < len(sessions)}

    async def finish(call):
        entry = hass.config_entries.async_get_entry(call.data["config_entry_id"])
        runtime = getattr(entry, "runtime_data", None) if entry else None
        if entry is None or entry.domain != "ftms" or runtime is None or runtime.coordinator.closed:
            raise ValueError("FTMS entry is not connected")
        return await runtime.coordinator.async_finish_workout()

    hass.services.async_register("ftms", "get_sessions", get_sessions, schema=vol.Schema({
        vol.Required("config_entry_id"): str,
        vol.Optional("offset", default=0): vol.All(int, vol.Range(min=0)),
        vol.Optional("limit", default=50): vol.All(int, vol.Range(min=1, max=100)),
    }), supports_response=SupportsResponse.ONLY)
    hass.services.async_register("ftms", "finish_workout", finish, schema=vol.Schema({
        vol.Required("config_entry_id"): str,
    }), supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register("ftms", "get_status", get_status, schema=vol.Schema({
        vol.Required("config_entry_id"): str,
    }), supports_response=SupportsResponse.ONLY)
    hass.services.async_register("ftms", "get_observations", get_observations, schema=vol.Schema({
        vol.Required("config_entry_id"): str,
        vol.Optional("cursor"): vol.Any(None, str),
        vol.Optional("limit", default=100): vol.All(int, vol.Range(min=1, max=200)),
    }), supports_response=SupportsResponse.ONLY)
    from .wake_runtime import async_setup_publisher
    await async_setup_publisher(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: FtmsConfigEntry) -> bool:
    address = entry.data[CONF_ADDRESS]
    info = bluetooth.async_last_service_info(hass, address, connectable=True)
    device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if (info is None or device is None
            or not bluetooth.async_scanner_devices_by_address(hass, address, connectable=True)):
        raise ConfigEntryNotReady("Waiting for connectable FTMS advertisement")
    ready = False
    coordinator = None

    @callback
    def disconnected(ftms):
        if coordinator:
            coordinator.disconnected()
        if ready and ftms.need_connect:
            coordinator.request_reconnect(entry)

    try:
        ftms = pyftms.get_client(device, info.advertisement, on_disconnect=disconnected)
    except pyftms.NotFitnessMachineError as exc:
        raise ConfigEntryNotReady("Waiting for FTMS service data; use active scanning") from exc
    coordinator = DataCoordinator(hass, ftms, entry.entry_id)
    await coordinator.open_journal()
    try:
        async with asyncio.timeout(40):
            await ftms.connect()
        unique_id = entry.unique_id or entry.entry_id
        entry.runtime_data = FtmsData(
            entry_id=entry.entry_id, unique_id=unique_id,
            device_info=dr.DeviceInfo(
                connections={(dr.CONNECTION_BLUETOOTH, address)},
                identifiers={("ftms", unique_id)}, name="Kettler FTMS",
                **ftms.device_info,
            ),
            ftms=ftms, coordinator=coordinator,
            sensors=list(ftms.supported_properties),
        )

        @callback
        def advertisement(info, change):
            ftms.set_ble_device_and_advertisement_data(info.device, info.advertisement)

        entry.async_on_unload(bluetooth.async_register_callback(
            hass, advertisement, {"address": address, "connectable": True},
            bluetooth.BluetoothScanningMode.ACTIVE,
        ))
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except asyncio.CancelledError:
        await ftms.disconnect()
        await coordinator.close()
        raise
    except Exception as exc:
        await ftms.disconnect()
        await coordinator.close()
        raise ConfigEntryNotReady(f"FTMS setup failed: {type(exc).__name__}") from exc
    ready = True
    coordinator.start_watchdog(entry)

    async def stop(event):
        await ftms.disconnect()
        await coordinator.close()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FtmsConfigEntry) -> bool:
    data = entry.runtime_data
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await data.ftms.disconnect()
        await data.coordinator.close()
        return True
    return False
