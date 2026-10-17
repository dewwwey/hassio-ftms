"""Deterministic, replayable observation ledger. No reward ledger writes."""
import hashlib

MAX_SAMPLE_GAP = 10.0
IDLE_END = 120.0
OFFLINE_END = 1800.0


class Sessions:
    def __init__(self, source):
        self.source = source
        self.current = None
        self.last = None
        self.previous = None
        self.completed_count = 0
        self.saw_idle = False

    def apply(self, record):
        ts, kind = record["ts"], record["kind"]
        if kind in ("disconnect", "restart", "storage_gap", "malformed_packet"):
            if self.current:
                self._flag(kind)
            self.previous = None
            self.saw_idle = False
            return
        if kind == "tick":
            if self.current and ts - self.current["last_sample"] >= OFFLINE_END:
                self._finish(self.current["last_activity"], "offline_timeout")
            return
        if kind != "sample":
            return
        m = record["metrics"]
        # Cadence is activity evidence. Speed can coast; power may be stale.
        cadence = m.get("cadence_instant")
        if cadence is None:
            if self.current:
                self._flag("missing_cadence")
            self.previous = None
            return
        active = cadence > 0
        if not active and self.current is None:
            self.saw_idle = True
        if self.current and self.previous:
            prev_ts, prev_m = self.previous
            for key in ("time_elapsed", "distance_total"):
                if key in m and key in prev_m and m[key] < prev_m[key]:
                    self._finish(prev_ts, "counter_reset")
                    break
        if self.current is None and active:
            identity = f"ftms:v1:{self.source}:{ts:.6f}"
            self.current = {
                "schema_version": 1,
                "session_id": hashlib.sha256(identity.encode()).hexdigest()[:24],
                "source": "ha.ftms.indoor_bike",
                "start_ts": ts, "last_activity": ts, "last_sample": ts,
                "active_seconds": 0.0, "flags": [] if self.saw_idle else ["start_not_observed"], "samples": 0,
                "distance_m": None, "distance_previous": m.get("distance_total"),
                "intent_confirmed": False,
            }
            self.previous = None
            self.saw_idle = False
        s = self.current
        if s is None:
            return
        if self.previous:
            prev_ts, prev_m = self.previous
            dt = ts - prev_ts
            if dt < 0:
                self._flag("clock_regression")
            elif dt <= MAX_SAMPLE_GAP:
                if active and prev_m.get("cadence_instant", 0) > 0:
                    s["active_seconds"] += dt
                old, new = s["distance_previous"], m.get("distance_total")
                if old is not None and new is not None:
                    s["distance_m"] = (s["distance_m"] or 0) + max(0, new - old)
            else:
                self._flag("sample_gap")
        s["distance_previous"] = m.get("distance_total")
        s["last_sample"] = ts
        s["samples"] += 1
        if active:
            s["last_activity"] = ts
            s.pop("inactive_since", None)
        else:
            s.setdefault("inactive_since", ts)
            if ts - s["inactive_since"] >= IDLE_END:
                self._finish(s["inactive_since"], None)
        self.previous = (ts, m.copy()) if self.current else None

    def _flag(self, flag):
        if flag not in self.current["flags"]:
            self.current["flags"].append(flag)

    def _finish(self, end_ts, flag):
        if flag:
            self._flag(flag)
        s = self.current.copy()
        s["end_ts"] = end_ts
        s["total_seconds"] = max(0, end_ts - s["start_ts"])
        s["active_seconds"] = round(s["active_seconds"], 3)
        s["quality"] = "partial" if s["flags"] else "complete"
        s["reward_status"] = "requires_quality_review" if s["flags"] else "requires_intent_confirmation"
        s["duration_qualifies"] = s["active_seconds"] >= 600
        s["proposed_reward_cents"] = (
            200 + (100 if s["active_seconds"] >= 1200 else 0)
        ) if s["duration_qualifies"] and not s["flags"] else 0
        for key in ("distance_previous", "inactive_since"):
            s.pop(key, None)
        self.last = s
        self.completed_count += 1
        self.current = None
        self.previous = None
        self.saw_idle = flag is None

    @property
    def status(self):
        if not self.current:
            return "idle"
        return "paused" if "inactive_since" in self.current else "riding"


def completed_sessions(records, source):
    """Export every completed ID exactly once, including after restarts."""
    engine = Sessions(source)
    result = []
    for record in records:
        count = engine.completed_count
        engine.apply(record)
        if engine.completed_count > count:
            result.append(engine.last)
    return result
