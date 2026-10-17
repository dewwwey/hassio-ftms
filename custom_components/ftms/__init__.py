"""Observed FTMS telemetry with an explicit, narrowly scoped Finish action."""
import asyncio
import json
from pathlib import Path
import voluptuous as vol
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant, SupportsResponse, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from ._vendor import pyftms
from .coordinator import DataCoordinator
from .models import FtmsData
from .sessions import completed_sessions

PLATFORMS = [Platform.SENSOR, Platform.BUTTON]
type FtmsConfigEntry = ConfigEntry[FtmsData]


async def async_setup(hass, config):
    async def get_sessions(call):
        entry_id = call.data["config_entry_id"]
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != "ftms":
            raise ValueError("Unknown FTMS config entry")
        if hasattr(entry, "runtime_data") and entry.runtime_data:
            await entry.runtime_data.coordinator.queue.join()
        path = Path(hass.config.path(".storage", "ftms", entry_id + ".jsonl"))

        def read():
            if not path.exists():
                return []
            with path.open(encoding="utf-8") as stream:
                records = [json.loads(line) for line in stream if line.endswith("\n")]
            return completed_sessions(records, entry_id)

        sessions = await hass.async_add_executor_job(read)
        offset, limit = call.data["offset"], call.data["limit"]
        runtime = getattr(entry, "runtime_data", None)
        storage_error = runtime.coordinator.storage_error if runtime else "entry_not_loaded"
        return {"schema_version": 2, "read_only": False, "telemetry_observed": True,
                "automatic_control": False, "control_scope": ["finish_workout"],
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
