"""Packet and deterministic lifecycle regressions; no hardware assumptions."""
import asyncio
import importlib.util
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).parents[1] / "custom_components" / "ftms"
sys.path.insert(0, str(ROOT / "_vendor"))
from pyftms.client.backends.updater import DataUpdater
from pyftms.client.machines import IndoorBike
from pyftms.client.machines import Treadmill
from types import SimpleNamespace
from pyftms.models.realtime_data.indoor_bike import IndoorBikeData

spec = importlib.util.spec_from_file_location("sessions", ROOT / "sessions.py")
sessions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sessions)


def sample(ts, cadence=60, **extra):
    return {"kind": "sample", "ts": ts, "metrics": {"cadence_instant": cadence, **extra}}


class PacketTests(unittest.TestCase):
    def test_identical_and_zero_frames_are_emitted(self):
        events = []
        updater = DataUpdater(IndoorBikeData, events.append)
        frame = struct.pack("<HHH", 4, 1000, 120)
        for packet in (frame, frame, struct.pack("<HHH", 4, 0, 0)):
            updater._on_notify(None, packet)
        self.assertEqual(len(events), 3)
        self.assertEqual(events[-1].event_data["cadence_instant"], 0)
        self.assertEqual(events[-1].event_data["speed_instant"], 0)

    def test_units_signed_power_distance_and_time(self):
        events = []
        updater = DataUpdater(IndoorBikeData, events.append)
        frame = struct.pack("<HHH", 4 | 16 | 64 | 2048, 1550, 81)
        frame += (1000).to_bytes(3, "little") + struct.pack("<hH", -12, 60)
        updater._on_notify(None, frame)
        result = events[-1].event_data
        self.assertEqual(result["speed_instant"], 15.5)
        self.assertEqual(result["cadence_instant"], 40.5)
        self.assertEqual(result["power_instant"], -12)
        self.assertEqual(result["distance_total"], 1000)
        self.assertEqual(result["time_elapsed"], 60)
        self.assertNotIn("heart_rate", result)

    def test_missing_field_does_not_crash_diff(self):
        events = []
        updater = DataUpdater(IndoorBikeData, events.append)
        updater._on_notify(None, struct.pack("<HHH", 4, 100, 40))
        updater._on_notify(None, struct.pack("<HH", 0, 100))
        self.assertNotIn("cadence_instant", events[-1].event_data)

    def test_malformed_packet_then_recovery(self):
        events = []
        updater = DataUpdater(IndoorBikeData, events.append)
        updater._on_notify(None, b"\x04")
        updater._on_notify(None, struct.pack("<HHH", 4, 0, 0))
        self.assertEqual(events[0].event_data, {"packet_error": 1})
        self.assertEqual(events[-1].event_data["cadence_instant"], 0)

    def test_control_cannot_write(self):
        machine = IndoorBike.__new__(IndoorBike)
        with self.assertRaises(PermissionError):
            asyncio.run(machine.start_resume())

    def test_gatt_overrides_incorrect_advertised_machine(self):
        machine = Treadmill.__new__(Treadmill)
        machine._cli = SimpleNamespace(services=SimpleNamespace(
            get_service=lambda uuid: True,
            get_characteristic=lambda uuid: uuid == IndoorBike._data_uuid,
        ))
        machine._verify_gatt_machine()
        self.assertEqual(machine.machine_type, IndoorBike._machine_type)
        self.assertEqual(machine._data_uuid, IndoorBike._data_uuid)
        self.assertIn("cadence_instant", machine._get_supported_properties())

    def test_gatt_ambiguity_fails_closed(self):
        machine = IndoorBike.__new__(IndoorBike)
        machine._cli = SimpleNamespace(services=SimpleNamespace(
            get_service=lambda uuid: True,
            get_characteristic=lambda uuid: True,
        ))
        with self.assertRaises(ValueError):
            machine._verify_gatt_machine()


class SessionTests(unittest.TestCase):
    def run_records(self, records):
        state = sessions.Sessions("synthetic-device")
        for record in records:
            state.apply(record)
        return state

    def completed_ride(self, seconds):
        return [sample(-1, 0)] + [sample(t) for t in range(seconds + 1)] + [
            sample(t, 0) for t in range(seconds + 1, seconds + 122)
        ]

    def test_idle_never_creates_a_session(self):
        state = self.run_records([sample(t, 0) for t in range(300)])
        self.assertIsNone(state.current)
        self.assertIsNone(state.last)

    def test_ride_summary_and_replay_dedup(self):
        records = self.completed_ride(600)
        first = self.run_records(records)
        replay = self.run_records(records)
        self.assertEqual(first.last, replay.last)
        self.assertEqual(first.completed_count, 1)
        self.assertEqual(first.last["active_seconds"], 600)
        self.assertEqual(first.last["total_seconds"], 601)
        self.assertEqual(first.last["quality"], "complete")
        self.assertEqual(first.last["proposed_reward_cents"], 200)
        self.assertFalse(first.last["intent_confirmed"])

    def test_reward_boundaries(self):
        for seconds, reward in ((599, 0), (600, 200), (1199, 200), (1200, 300)):
            state = self.run_records(self.completed_ride(seconds))
            self.assertEqual(state.last["proposed_reward_cents"], reward)

    def test_pause_and_resume_keep_id_and_exclude_pause(self):
        state = self.run_records([sample(-1, 0), sample(0), sample(5)])
        identity = state.current["session_id"]
        for t, cadence in ((10, 0), (15, 0), (20, 60), (25, 60)):
            state.apply(sample(t, cadence))
        self.assertEqual(state.current["session_id"], identity)
        self.assertEqual(state.current["active_seconds"], 10)

    def test_disconnect_restart_and_gap_never_count(self):
        records = [sample(-1, 0), sample(0), sample(5), {"kind": "disconnect", "ts": 6},
                   {"kind": "restart", "ts": 7}, sample(100), sample(105)]
        state = self.run_records(records)
        self.assertEqual(state.current["active_seconds"], 10)
        self.assertIn("disconnect", state.current["flags"])
        self.assertIn("restart", state.current["flags"])
        identity = state.current["session_id"]
        state.apply({"kind": "tick", "ts": 2000})
        self.assertEqual(state.last["session_id"], identity)
        self.assertEqual(state.last["quality"], "partial")
        self.assertEqual(state.last["proposed_reward_cents"], 0)

    def test_missing_samples_and_clock_regression_are_flagged(self):
        state = self.run_records([sample(-1, 0), sample(0), sample(50), sample(40)])
        self.assertIn("sample_gap", state.current["flags"])
        self.assertIn("clock_regression", state.current["flags"])
        self.assertEqual(state.current["active_seconds"], 0)

    def test_counter_reset_splits_and_marks_partial(self):
        state = self.run_records([sample(-1, 0), sample(0, time_elapsed=100),
                                  sample(5, time_elapsed=105), sample(6, time_elapsed=0)])
        self.assertEqual(state.last["quality"], "partial")
        self.assertNotEqual(state.last["session_id"], state.current["session_id"])

    def test_attach_mid_ride_is_partial(self):
        state = self.run_records([sample(0), sample(1)])
        self.assertIn("start_not_observed", state.current["flags"])

    def test_second_ride_after_observed_stop_has_known_start(self):
        state = self.run_records(self.completed_ride(60))
        state.apply(sample(300))
        self.assertNotIn("start_not_observed", state.current["flags"])

    def test_export_covers_multiple_sessions_with_stable_ids(self):
        records = self.completed_ride(60)
        records += [{**r, "ts": r["ts"] + 500} for r in self.completed_ride(90)]
        exported = sessions.completed_sessions(records, "synthetic-device")
        self.assertEqual(len(exported), 2)
        self.assertEqual(len({r["session_id"] for r in exported}), 2)
        self.assertEqual(exported, sessions.completed_sessions(records, "synthetic-device"))


if __name__ == "__main__":
    unittest.main()
