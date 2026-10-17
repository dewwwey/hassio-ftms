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
        self.awaiting_idle_after_finish = False

    def apply(self, record):
        ts, kind = record["ts"], record["kind"]
        if kind == "finish":
            if self.current:
                end = self.current.get("inactive_since", ts)
                self._finish(end, None, record.get("reason", "explicit_finish"))
            self.awaiting_idle_after_finish = True
            self.saw_idle = False
            return
        # Setup retries have no running watchdog. Expire before resumed samples
        # as well, so a new day's ride cannot merge into yesterday's outage.
        if (self.current and kind in ("sample", "restart", "tick")
                and ts - self.current["last_sample"] >= OFFLINE_END):
            self._finish(self.current["last_activity"], "offline_timeout")
        if kind in ("disconnect", "restart", "storage_gap", "malformed_packet"):
            if self.current:
                self._flag(kind)
            self.previous = None
            self.saw_idle = False
            return
        if kind == "tick":
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
        if self.current is None and self.awaiting_idle_after_finish:
            if active:
                return
            self.awaiting_idle_after_finish = False
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
                "schema_version": 2,
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

    def _finish(self, end_ts, flag, reason="observed_inactivity"):
        if flag:
            self._flag(flag)
        s = self.current.copy()
        s["end_ts"] = end_ts
        s["total_seconds"] = max(0, end_ts - s["start_ts"])
        s["active_seconds"] = round(s["active_seconds"], 3)
        s["quality"] = "partial" if s["flags"] else "complete"
        s["finish_reason"] = flag or reason
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
