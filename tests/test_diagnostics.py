"""Downloaded technical diagnostics work through unloaded entries without health values."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace as N
import unittest
spec=importlib.util.spec_from_file_location('diagnostics_guard',Path(__file__).parents[1]/'custom_components/ftms/diagnostics.py')
diag=importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)
class DiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_or_unloaded_runtime_is_truthfully_offline(self):
        for entry in (N(),N(runtime_data=None),N(runtime_data=N(coordinator=None))):
            result=await diag.async_get_config_entry_diagnostics(None,entry)
            self.assertFalse(result['connected'])
            self.assertFalse(result['fresh'])
            self.assertEqual(result['runtime_state'],'not_loaded')
            self.assertEqual(result['storage_error'],'entry_not_loaded')
    async def test_closed_runtime_preserves_fault_without_freshness(self):
        c=N(closed=True,observed={'heart_rate'},storage_error='recording_fault',fresh=True,values={'heart_rate':123})
        result=await diag.async_get_config_entry_diagnostics(None,N(runtime_data=N(coordinator=c)))
        self.assertFalse(result['fresh'])
        self.assertEqual(result['storage_error'],'recording_fault')
        self.assertEqual(result['observed_metric_names'],['heart_rate'])
        self.assertNotIn('values',result)
        self.assertNotIn('123',str(result))
    async def test_loaded_runtime_still_reports_technical_capabilities(self):
        c=N(closed=False,observed={'cadence_instant'},storage_error=None,fresh=True)
        client=N(is_connected=True,supported_properties=['cadence_instant'],machine_type=N(name='INDOOR_BIKE'),
                 supported_settings=['target_resistance','target_power'],
                 supported_ranges={'target_resistance':object(),'target_power':object()})
        result=await diag.async_get_config_entry_diagnostics(None,N(runtime_data=N(coordinator=c,ftms=client)))
        self.assertTrue(result['fresh'])
        self.assertTrue(result['connected'])
        self.assertIsNone(result['storage_error'])
        self.assertEqual(result['runtime_state'],'loaded')
        self.assertEqual(result['control_scope'],['finish_workout','target_resistance','target_power'])
