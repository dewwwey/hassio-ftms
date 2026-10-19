"""Incremental journal reads must not lose, duplicate or silently replace data."""
import importlib.util
import json
from pathlib import Path
import tempfile
import sys
from types import ModuleType
import unittest

root = Path(__file__).parents[1] / "custom_components/ftms"
package = ModuleType("observations_test_package")
package.__path__ = [str(root)]
sys.modules[package.__name__] = package
spec = importlib.util.spec_from_file_location("observations_test_package.observations", root / "observations.py")
observations = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observations)


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "journal.jsonl"

    def write(self, *records):
        with self.path.open("ab") as stream:
            for record in records:
                stream.write(json.dumps(record).encode() + b"\n")

    def test_page_boundaries_and_stable_ids(self):
        self.write(*({"kind": "sample", "ts": n, "metrics": {"cadence_instant": n}} for n in range(5)))
        first = observations.read_page(self.path, "source", limit=2)
        same = observations.read_page(self.path, "source", limit=2)
        self.assertEqual(first, same)
        second = observations.read_page(self.path, "source", first["next_cursor"], 2)
        third = observations.read_page(self.path, "source", second["next_cursor"], 2)
        rows = first["records"] + second["records"] + third["records"]
        self.assertEqual([r["ts"] for r in rows], list(range(5)))
        self.assertEqual(len({r["record_id"] for r in rows}), 5)
        self.assertTrue(first["has_more"])
        self.assertFalse(third["has_more"])
        self.assertFalse(observations.read_page(self.path, "source", third["next_cursor"])["records"])

    def test_partial_tail_stays_behind_cursor_until_completed(self):
        self.write({"kind": "sample", "ts": 1})
        with self.path.open("ab") as stream:
            stream.write(b'{"kind":"sample","ts":2')
        page = observations.read_page(self.path, "source")
        self.assertEqual(len(page["records"]), 1)
        self.assertFalse(page["has_more"])
        with self.path.open("ab") as stream:
            stream.write(b'}\n')
        following = observations.read_page(self.path, "source", page["next_cursor"])
        self.assertEqual([r["ts"] for r in following["records"]], [2])

    def test_empty_cursor_survives_first_write(self):
        page = observations.read_page(self.path, "source")
        self.write({"kind": "sample", "ts": 1})
        self.assertEqual(len(observations.read_page(self.path, "source", page["next_cursor"])["records"]), 1)

    def test_wrong_source_and_invalid_cursor_are_rejected(self):
        self.write({"kind": "sample", "ts": 1})
        cursor = observations.read_page(self.path, "source")["next_cursor"]
        for source, token in (("different", cursor), ("source", "garbage"), ("source", "x" * 513)):
            with self.assertRaises(ValueError):
                observations.read_page(self.path, source, token)

    def test_truncation_missing_file_and_replacement_fail_closed(self):
        self.write({"kind": "sample", "ts": 1})
        original = self.path.read_bytes()
        cursor = observations.read_page(self.path, "source")["next_cursor"]
        self.path.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "truncated"):
            observations.read_page(self.path, "source", cursor)
        self.path.unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            observations.read_page(self.path, "source", cursor)
        self.path.write_bytes(original.replace(b'1', b'2'))
        with self.assertRaisesRegex(ValueError, "changed"):
            observations.read_page(self.path, "source", cursor)

    def test_complete_corruption_does_not_advance_cursor(self):
        self.path.write_bytes(b'corrupt\n')
        with self.assertRaises(ValueError):
            observations.read_page(self.path, "source")
        self.assertEqual(self.path.read_bytes(), b'corrupt\n')

    def test_bounded_records_and_page_size(self):
        self.path.write_bytes(b'x' * (observations.MAX_LINE + 1))
        with self.assertRaisesRegex(ValueError, "Oversized"):
            observations.read_page(self.path, "source")
        for limit in (0, 201):
            with self.assertRaises(ValueError):
                observations.read_page(self.path, "source", limit=limit)

    def test_oversized_record_after_page_boundary_fails_closed(self):
        self.write({"kind": "sample", "ts": 1})
        with self.path.open("ab") as stream:
            stream.write(b'x' * (observations.MAX_LINE + 1) + b'\n')
        with self.assertRaisesRegex(ValueError, "Oversized"):
            observations.read_page(self.path, "source", limit=1)

    def test_offline_snapshot_recovers_last_seen_and_latest_event(self):
        self.write({"kind": "sample", "ts": 1, "metrics": {"cadence_instant": 0}},
                   {"kind": "activity_started", "ts": 1, "event_id": "synthetic-event"},
                   {"kind": "heartbeat", "ts": 30, "last_received_ts": 29},
                   {"kind": "disconnect", "ts": 35, "last_received_ts": 32})
        snapshot = observations.read_snapshot(self.path, "source")
        self.assertEqual(snapshot["last_received_ts"], 32)
        self.assertEqual(snapshot["last_persisted_ts"], 35)
        self.assertEqual(snapshot["latest_event"]["event_id"], "synthetic-event")

    def test_offline_snapshot_keeps_completed_summary_and_event(self):
        self.write({"kind": "sample", "ts": 0, "metrics": {"cadence_instant": 0}},
                   {"kind": "sample", "ts": 1, "metrics": {"cadence_instant": 60, "power_instant": 10}},
                   {"kind": "activity_started", "ts": 1, "event_id": "synthetic-event"},
                   {"kind": "sample", "ts": 2, "metrics": {"cadence_instant": 60}},
                   {"kind": "sample", "ts": 3, "metrics": {"cadence_instant": 0}},
                   {"kind": "finish", "ts": 4, "reason": "machine_stop"},
                   {"kind": "disconnect", "ts": 5, "last_received_ts": 3})
        snapshot = observations.read_snapshot(self.path, "source")
        self.assertEqual(snapshot, observations.read_snapshot(self.path, "source"))
        self.assertEqual(snapshot["completed_count"], 1)
        self.assertIsNone(snapshot["current_session"])
        self.assertEqual(snapshot["last_session"]["active_seconds"], 1)
        self.assertEqual(snapshot["last_session"]["finish_reason"], "machine_stop")
        self.assertFalse(snapshot["last_session"]["intent_confirmed"])
        self.assertEqual(snapshot["latest_event"]["event_id"], "synthetic-event")
        self.assertEqual(snapshot["observed_metrics"], ["cadence_instant", "power_instant"])
        self.assertEqual(snapshot["observed_metrics_scope"], "journal_history")

    def test_offline_snapshot_does_not_invent_completion(self):
        self.write({"kind": "sample", "ts": 1, "metrics": {"cadence_instant": 60}},
                   {"kind": "disconnect", "ts": 2, "last_received_ts": 1})
        snapshot = observations.read_snapshot(self.path, "source")
        self.assertEqual(snapshot["completed_count"], 0)
        self.assertIsNone(snapshot["last_session"])
        self.assertIn("disconnect", snapshot["current_session"]["flags"])
        self.assertEqual(snapshot["current_session"]["active_seconds"], 0)
