"""Technical diagnostics intentionally omit identifiers and measurements."""
async def async_get_config_entry_diagnostics(hass, entry):
    data = entry.runtime_data
    c = data.coordinator
    return {
        "read_only": False,
        "telemetry_observed": True,
        "automatic_control": False,
        "control_scope": ["finish_workout"],
        "connected": data.ftms.is_connected,
        "fresh": c.fresh,
        "observed_metric_names": sorted(c.observed),
        "supported_properties": list(data.ftms.supported_properties),
        "machine_type": data.ftms.machine_type.name,
        "storage_error": c.storage_error,
        "python_compatibility": "pinned vendored pyftms 0.4.15; tested on Python 3.14",
    }
