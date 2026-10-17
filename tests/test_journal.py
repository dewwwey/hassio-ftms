"""Exercise actual journal I/O and teardown with a minimal HA executor facade."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[1] / "custom_components" / "ftms"


def load_coordinator():
    for name in ("homeassistant", "homeassistant.core", "homeassistant.helpers", "homeassistant.exceptions",
                 "homeassistant.helpers.event", "homeassistant.helpers.update_coordinator"):
        sys.modules.setdefault(name, ModuleType(name))
    def callback(fn):
        fn._hass_callback = True
        return fn
    sys.modules["homeassistant.core"].callback = callback
    sys.modules["homeassistant.exceptions"].HomeAssistantError = type("HomeAssistantError", (Exception,), {})
    sys.modules["homeassistant.helpers.event"].async_track_time_interval = lambda *args: lambda: None
    sys.modules["homeassistant.helpers.event"].async_call_later = lambda *args: lambda: None

    class Coordinator:
        def __init__(self, hass, *args, **kwargs):
            self.hass = hass
        def async_set_updated_data(self, data):
            self.data = data
        def async_update_listeners(self):
            pass

    sys.modules["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator = Coordinator
    package = ModuleType("journal_test_package")
    package.__path__ = [str(ROOT)]
    sys.modules[package.__name__] = package
    spec = importlib.util.spec_from_file_location("journal_test_package.coordinator", ROOT / "coordinator.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.DataCoordinator


DataCoordinator = load_coordinator()


class JournalTests(unittest.IsolatedAsyncioTestCase):
    def make(self, path):
        async def executor(fn, *args):
            return await asyncio.to_thread(fn, *args)
        hass = SimpleNamespace(data={}, config=SimpleNamespace(path=lambda *parts: str(Path(path).joinpath(*parts))),
                               async_add_executor_job=executor)
        ftms = SimpleNamespace(is_connected=True)
        ftms.set_callback = lambda cb: setattr(ftms, "callback", cb)
        return DataCoordinator(hass, ftms, "synthetic")

    async def test_flush_close_and_restart_replay(self):
        with tempfile.TemporaryDirectory() as path:
            first = self.make(path)
            await first.open_journal()
            first.record({"kind": "sample", "ts": 0, "metrics": {"cadence_instant": 0}})
            first.record({"kind": "sample", "ts": 1, "metrics": {"cadence_instant": 60}})
            first.record({"kind": "sample", "ts": 2, "metrics": {"cadence_instant": 60}})
            identity = first.sessions.current["session_id"]
            await first.close()
            self.assertTrue(first.worker.done())
            second = self.make(path)
            with patch("journal_test_package.coordinator.time", return_value=3):
                await second.open_journal()
            self.assertEqual(second.sessions.current["session_id"], identity)
            self.assertEqual(second.sessions.current["active_seconds"], 1)
            self.assertIn("restart", second.sessions.current["flags"])
            await second.close()
            for line in second.path.read_text().splitlines():
                json.loads(line)

    async def test_truncated_tail_preserved_and_repaired(self):
        with tempfile.TemporaryDirectory() as path:
            state = self.make(path)
            state.path.parent.mkdir(parents=True)
            record = {"kind": "sample", "ts": 1, "metrics": {"cadence_instant": 60}}
            state.path.write_bytes(json.dumps(record).encode() + b'\n{"kind":')
            with patch("journal_test_package.coordinator.time", return_value=3):
                await state.open_journal()
            self.assertEqual(state.path.with_suffix(".truncated").read_bytes(), b'{"kind":')
            self.assertIn("storage_gap", state.sessions.current["flags"])
            await state.close()
            for line in state.path.read_text().splitlines():
                json.loads(line)

    async def test_corrupt_complete_record_fails_without_destroying_it(self):
        with tempfile.TemporaryDirectory() as path:
            state = self.make(path)
            state.path.parent.mkdir(parents=True)
            original = b"corrupt complete line\n"
            state.path.write_bytes(original)
            with self.assertRaises(json.JSONDecodeError):
                await state.open_journal()
            self.assertEqual(state.path.read_bytes(), original)

    async def test_rssi_does_not_refresh_metric_or_create_workout(self):
        with tempfile.TemporaryDirectory() as path:
            state = self.make(path)
            await state.open_journal()
            with patch("journal_test_package.coordinator.time", return_value=100):
                state.ftms.callback(SimpleNamespace(event_id="update", event_data={"speed_instant": 0, "cadence_instant": 0}))
                self.assertTrue(state.field_fresh("cadence_instant"))
                self.assertFalse(state.field_fresh("power_instant"))
            with patch("journal_test_package.coordinator.time", return_value=111):
                state.ftms.callback(SimpleNamespace(event_id="update", event_data={"rssi": -60}))
                self.assertFalse(state.fresh)
                self.assertEqual(state.last_received, 100)
            self.assertIsNone(state.sessions.current)
            await state.close()

    async def test_queue_overflow_marks_quality_before_finishing(self):
        with tempfile.TemporaryDirectory() as path:
            state = self.make(path)
            state.queue = asyncio.Queue(maxsize=1)
            state.sessions.apply({"kind": "sample", "ts": 0, "metrics": {"cadence_instant": 0}})
            state.sessions.apply({"kind": "sample", "ts": 1, "metrics": {"cadence_instant": 60}})
            state.record({"kind": "sample", "ts": 2, "metrics": {"cadence_instant": 0}})
            state.record({"kind": "sample", "ts": 122, "metrics": {"cadence_instant": 0}})
            self.assertEqual(state.storage_error, "queue_full")
            self.assertEqual(state.sessions.last["quality"], "partial")

    async def test_absent_heart_rate_never_reports_a_false_zero(self):
        with tempfile.TemporaryDirectory() as path:
            state = self.make(path)
            await state.open_journal()
            state.ftms.callback(SimpleNamespace(event_id="update", event_data={"speed_instant": 0, "cadence_instant": 0, "heart_rate": 80}))
            self.assertTrue(state.field_fresh("heart_rate"))
            state.ftms.callback(SimpleNamespace(event_id="update", event_data={"speed_instant": 0, "cadence_instant": 0, "heart_rate": 0}))
            self.assertFalse(state.field_fresh("heart_rate"))
            self.assertNotIn("heart_rate", state.values)
            await state.close()

    async def test_reconnect_backoff_is_bounded_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as path:
            state = self.make(path)
            delays = []
            entry = SimpleNamespace(entry_id="synthetic")
            def later(hass, delay, callback):
                # HA dispatches unmarked sync functions to an executor thread.
                self.assertTrue(getattr(callback, "_hass_callback", False))
                delays.append(delay)
                return lambda: None
            with patch("journal_test_package.coordinator.async_call_later", later):
                state.request_reconnect(entry)
                state.request_reconnect(entry)
                self.assertEqual(delays, [5])
                for _ in range(10):
                    state.reloading = False
                    state.request_reconnect(entry)
            self.assertEqual(delays[:4], [5, 10, 20, 40])
            self.assertEqual(max(delays), 300)

    async def test_reconnect_timer_reloads_on_loop_and_ignores_closed_coordinator(self):
        with tempfile.TemporaryDirectory() as path:
            state = self.make(path)
            scheduled = []
            calls = []
            state.hass.config_entries = SimpleNamespace(async_schedule_reload=calls.append)
            def later(hass, delay, callback):
                self.assertTrue(getattr(callback, "_hass_callback", False))
                scheduled.append(callback)
                return lambda: None
            with patch("journal_test_package.coordinator.async_call_later", later):
                state.request_reconnect(SimpleNamespace(entry_id="synthetic"))
                scheduled[-1](None)
                self.assertEqual(calls, ["synthetic"])
                self.assertIsNone(state.cancel_reload)
                state.reloading = False
                state.request_reconnect(SimpleNamespace(entry_id="synthetic"))
                state.closed = True
                scheduled[-1](None)
                self.assertEqual(calls, ["synthetic"])

    async def test_idle_after_explicit_finish_rearms_next_ride_and_is_persisted(self):
        with tempfile.TemporaryDirectory() as path:
            state = self.make(path)
            await state.open_journal()
            def send(cadence):
                state.ftms.callback(SimpleNamespace(event_id="update", event_data={"speed_instant": 0, "cadence_instant": cadence}))
            send(0)
            self.assertTrue(state.idle_recorded)
            state.ftms.callback(SimpleNamespace(event_id="stop"))
            self.assertTrue(state.sessions.awaiting_idle_after_finish)
            send(0)
            self.assertFalse(state.sessions.awaiting_idle_after_finish)
            send(60)
            self.assertIsNotNone(state.sessions.current)
            self.assertEqual(state.sessions.current["flags"], [])
            await state.close()
