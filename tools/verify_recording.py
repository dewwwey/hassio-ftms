"""Validate a private recorded session against its journal; emits no measurements."""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("journal", type=Path)
parser.add_argument("export", type=Path)
parser.add_argument("output", type=Path)
parser.add_argument("--quality", choices=("complete", "partial"), required=True)
parser.add_argument("--require-interruption", action="store_true")
args = parser.parse_args()
records = [json.loads(line) for line in args.journal.read_text().splitlines()]
export = json.loads(args.export.read_text())
sessions = export["sessions"]
assert sessions, "No finalized recorded session yet"
summary = sessions[-1]
start, end = summary["start_ts"], summary["end_ts"]
previous = None
active = 0.0
distance = None
first_positive = None
last_positive = None
first_inactive_after_last_positive = None
recorded_samples = 0
for record in records:
    if record["ts"] < start:
        continue
    if record["kind"] in ("disconnect", "restart", "storage_gap", "malformed_packet"):
        previous = None
        continue
    if record["kind"] != "sample":
        continue
    if record["ts"] > end:
        break
    ts, m = record["ts"], record["metrics"]
    cadence = m.get("cadence_instant")
    recorded_samples += 1
    if cadence is None:
        previous = None
        continue
    if cadence > 0:
        first_positive = first_positive if first_positive is not None else ts
        last_positive = ts
        first_inactive_after_last_positive = None
    elif last_positive is not None and first_inactive_after_last_positive is None:
        first_inactive_after_last_positive = ts
    if previous:
        prev_ts, prev = previous
        dt = ts - prev_ts
        if 0 <= dt <= 10:
            if cadence > 0 and prev.get("cadence_instant", 0) > 0:
                active += dt
            old, new = prev.get("distance_total"), m.get("distance_total")
            if old is not None and new is not None:
                distance = (distance or 0) + max(0, new - old)
    previous = (ts, m)
checks = {
    "start_is_first_observed_activity": first_positive == start,
    "end_matches_observed_inactivity_or_explicit_finish": (
        first_inactive_after_last_positive == end or any(
            r["kind"] == "finish" and r["ts"] == end for r in records
        )
    ),
    "active_seconds_match_independent_adjacent_sample_sum": abs(active - summary["active_seconds"]) < .002,
    "total_seconds_match_observed_boundaries": abs((end - start) - summary["total_seconds"]) < .002,
    "distance_matches_independent_observed_delta_sum": distance == summary["distance_m"],
    "observed_telemetry": export.get("telemetry_observed", export.get("read_only") is True) is True,
    "control_is_explicit_and_scoped": (
        export.get("automatic_control", False) is False
        and set(export.get("control_scope", [])) <= {"finish_workout"}
    ),
    "storage_healthy": export["storage_error"] is None,
    "no_monetary_fields": not {"proposed_reward_cents", "duration_qualifies", "reward_status"}.intersection(summary),
    "expected_quality": summary["quality"] == args.quality,
    "required_interruption_flags": not args.require_interruption or {"disconnect", "restart"}.issubset(summary["flags"]),
    "intent_not_inferred": summary["intent_confirmed"] is False,
}
args.output.write_text(json.dumps({"checks": checks, "summary": summary,
                                  "independent_active_seconds": active,
                                  "independent_distance_m": distance}, indent=2) + "\n")
assert all(checks.values()), {k: v for k, v in checks.items() if not v}
print(json.dumps({"all_checks_passed": True, "checks": checks}))
