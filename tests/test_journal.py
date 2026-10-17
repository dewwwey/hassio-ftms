"""Exercise actual journal I/O and teardown with a minimal HA executor facade."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest

ROOT = Path(__file__).parents[1] / "custom_components" / "ftms"


def load_coordinator():
    for name in ("homeassistant", "homeassistant.core", "homeassistant.helpers",
                 "homeassistant.helpers.event", "homeassistant.helpers.update_coordinator"):
        sys.modules.setdefault(name, ModuleType(name))
    sys.modules["homeassistant.core"].callback = lambda f: f
    sys.modules["homeassistant.helpers.event"].async_track_time_interval = lambda *args: lambda: None

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
    spec.loader.exec_module(module)
    return module.DataCoordinator


DataCoordinator = load_coordinator()


class JournalTests(unittest.IsolatedAsyncioTestCase):
    def make(self, path):
        async def executor(fn, *args):
            return await asyncio.to_thread(fn, *args)
        hass = SimpleNamespace(config=SimpleNamespace(path=lambda *parts: str(Path(path).joinpath(*parts))),
                               async_add_executor_job=executor)
        ftms = SimpleNamespace(set_callback=lambda cb: None, is_connected=True)
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
