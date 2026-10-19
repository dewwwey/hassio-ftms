"""Technical diagnostics intentionally omit identifiers and measurements."""
async def async_get_config_entry_diagnostics(hass, entry):
    data = getattr(entry, 'runtime_data', None)
    c = getattr(data, 'coordinator', None)
    result = {
        'read_only': False,
        'telemetry_observed': True,
        'automatic_control': False,
        'control_scope': ['finish_workout'],
        'runtime_state': 'not_loaded',
        'connected': False,
        'fresh': False,
        'observed_metric_names': sorted(getattr(c, 'observed', ())),
        'supported_properties': [],
        'machine_type': None,
        'storage_error': getattr(c, 'storage_error', None) or 'entry_not_loaded',
        'python_compatibility': 'pinned vendored pyftms 0.4.15; tested on Python 3.14',
    }
    if data is None or c is None or getattr(c, 'closed', False):
        return result
    result.update(runtime_state='loaded', connected=data.ftms.is_connected,
                  fresh=c.fresh, supported_properties=list(data.ftms.supported_properties),
                  machine_type=data.ftms.machine_type.name, storage_error=c.storage_error)
    if data.ftms.is_connected:
        supported_settings = getattr(data.ftms, 'supported_settings', ())
        supported_ranges = getattr(data.ftms, 'supported_ranges', {})
        result['control_scope'] = ['finish_workout'] + [
            setting for setting in ('target_resistance', 'target_power')
            if setting in supported_settings and setting in supported_ranges
        ]
    return result
