"""Exercise actual checkpoint I/O, restart, expiry and failed-commit behavior."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch

root = Path(__file__).parents[1] / "custom_components/ftms"
package = ModuleType("outbox_test_package")
package.__path__ = [str(root)]
sys.modules[package.__name__] = package
spec = importlib.util.spec_from_file_location("outbox_test_package.wake_outbox", root / "wake_outbox.py")
outbox = importlib.util.module_from_spec(spec)
spec.loader.exec_module(outbox)


class OutboxTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name)
        self.journal = self.path / "journal.jsonl"
        self.state = self.path / "queue.json"
        self.queue = self.make()
        self.queue.initialize(100)

    def make(self, source="source"):
        return outbox.WakeOutbox(self.state, source, "sensor.bike_diagnostics")

    def append(self, *records):
        with self.journal.open("a") as stream:
            for record in records:
                stream.write(json.dumps(record) + "\n")

    def event(self, identity="event-1", ts=101):
        return {"kind": "activity_started", "event_id": identity, "ts": ts,
                "session_id": "private-session"}

    def test_pending_event_and_cursor_survive_restart_without_duplicate(self):
        self.append({"kind": "sample", "ts": 101, "metrics": {"heart_rate": 80}}, self.event())
        self.queue.ingest(self.journal, 102)
        restored = self.make()
        pending = restored.pending(103)
        self.assertEqual([p["event_id"] for p in pending], ["event-1"])
        restored.ingest(self.journal, 104)
        self.assertEqual(restored.pending(104), pending)
        self.assertNotIn("heart_rate", self.state.read_text())
        self.assertNotIn("private-session", self.state.read_text())

    def test_failed_atomic_replace_cannot_advance_cursor_or_lose_event(self):
        self.append(self.event())
        before = self.state.read_bytes()
        with patch.object(outbox.os, "replace", side_effect=OSError("synthetic write failure")):
            with self.assertRaises(OSError):
                self.queue.ingest(self.journal, 102)
        self.assertEqual(self.state.read_bytes(), before)
        self.make().ingest(self.journal, 103)
        self.assertEqual(len(self.make().pending(103)), 1)
        self.assertFalse(list(self.path.glob(".wake-*")))

    def test_activation_boundary_and_expiry_never_replay_old_workouts(self):
        self.append(self.event("old", 99), self.event("recent", 101))
        self.queue.ingest(self.journal, 102)
        self.assertEqual([p["event_id"] for p in self.queue.pending(102)], ["recent"])
        self.assertEqual(self.make().pending(3702), [])
        saved = json.loads(self.state.read_text())
        self.assertEqual(saved["before_activation_count"], 1)
        self.assertEqual(saved["expired_count"], 1)
        self.assertEqual(saved["recent_receipts"][-1]["outcome"], "expired")

    def test_only_correlated_receipt_removes_pending_event(self):
        self.append(self.event())
        self.queue.ingest(self.journal, 102)
        with self.assertRaises(ValueError):
            self.queue.confirm_processed("different-event", 103)
        self.assertEqual(len(self.make().pending(104)), 1)
        self.queue.confirm_processed("event-1", 105)
        self.assertEqual(self.make().pending(106), [])
        self.append(self.event())
        self.make().ingest(self.journal, 107)
        self.assertEqual(self.make().pending(107), [])

    def test_capacity_failure_retains_checkpoint(self):
        self.append(self.event("one"), self.event("two"))
        before = self.state.read_bytes()
        with patch.object(outbox, "MAX_PENDING", 1):
            with self.assertRaisesRegex(ValueError, "queue full"):
                self.queue.ingest(self.journal, 102)
        self.assertEqual(self.state.read_bytes(), before)

    def test_source_mismatch_corruption_and_reinitialization_fail_closed(self):
        with self.assertRaises(ValueError):
            self.queue.initialize(101)
        with self.assertRaises(ValueError):
            self.make("other").pending(102)
        self.state.write_text("corrupt")
        with self.assertRaises(ValueError):
            self.queue.pending(102)
        self.assertEqual(self.state.read_text(), "corrupt")

    def test_future_event_does_not_advance_checkpoint(self):
        self.append(self.event(ts=105))
        before = self.state.read_bytes()
        with self.assertRaisesRegex(ValueError, "Future activity"):
            self.queue.ingest(self.journal, 102)
        self.assertEqual(self.state.read_bytes(), before)

    def test_saved_pending_envelope_cannot_gain_arbitrary_data_or_task(self):
        self.append(self.event())
        self.queue.ingest(self.journal, 102)
        original = json.loads(self.state.read_text())
        for mutation in ("task", "metric"):
            state = json.loads(json.dumps(original))
            envelope = state["pending"]["event-1"]
            if mutation == "task":
                envelope["task"] = "unexpected_task"
            else:
                envelope["data"]["heart_rate"] = 80
            self.state.write_text(json.dumps(state))
            with self.assertRaises(ValueError):
                self.make().pending(103)
