"""Single-writer durable wake queue, prepared but not enabled in HA."""
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading

from .observations import read_page
from .wake_transport import activity_envelope

MAX_AGE = 3600
MAX_PENDING = 256
MAX_STATE_BYTES = 2 * 1024 * 1024


def _time(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("Invalid wake queue timestamp")
    return value


class WakeOutbox:
    """Use one instance/worker per state file; never store source credentials here."""
    def __init__(self, path, source, status_entity):
        self.path = Path(path)
        self.source = source
        self.identity = hashlib.sha256(source.encode()).hexdigest()
        self.status_entity = status_entity
        self.lock = threading.Lock()

    def initialize(self, activated_at):
        """Explicit activation boundary: old workouts must not cause new wakes."""
        with self.lock:
            if self.path.exists():
                raise ValueError("Wake queue already exists; retain its checkpoint")
            self._save({"schema_version": 1, "source_hash": self.identity,
                        "activated_at": _time(activated_at), "cursor": None,
                        "pending": {}, "recent_receipts": [],
                        "expired_count": 0, "before_activation_count": 0})

    def _load(self):
        if self.path.stat().st_size > MAX_STATE_BYTES:
            raise ValueError("Wake queue exceeds size limit; retain it for diagnosis")
        state = json.loads(self.path.read_text(encoding="utf-8"))
        if (not isinstance(state, dict) or state.get("schema_version") != 1 or state.get("source_hash") != self.identity
                or not isinstance(state.get("pending"), dict)
                or not isinstance(state.get("recent_receipts"), list)):
            raise ValueError("Invalid or mismatched wake queue; do not reset automatically")
        _time(state["activated_at"])
        if len(state["pending"]) > MAX_PENDING or len(state["recent_receipts"]) > 512:
            raise ValueError("Invalid wake queue bounds")
        for event_id, envelope in state["pending"].items():
            try:
                expected = activity_envelope({"kind": "activity_started", "event_id": event_id,
                                              "ts": envelope["data"]["observed_at"]}, self.status_entity)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Invalid pending wake envelope") from exc
            if envelope != expected:
                raise ValueError("Unexpected fields in pending wake envelope")
        return state

    def _save(self, state):
        data = json.dumps(state, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if len(data) > MAX_STATE_BYTES:
            raise ValueError("Wake queue exceeds size limit")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix=".wake-", delete=False) as stream:
                temp_path = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self.path)
            if os.name == "posix":
                directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    @staticmethod
    def _receipt(state, event_id, outcome, now):
        state["recent_receipts"].append({"event_id": event_id, "outcome": outcome, "at": now})
        state["recent_receipts"] = state["recent_receipts"][-512:]

    def ingest(self, journal, now, limit=100):
        """Atomically checkpoint a raw page together with its new pending events."""
        now = _time(now)
        with self.lock:
            state = self._load()
            page = read_page(journal, self.source, state["cursor"], limit)
            seen = {r["event_id"] for r in state["recent_receipts"]} | set(state["pending"])
            for record in page["records"]:
                if record["kind"] not in ("activity_started", "activity_resumed"):
                    continue
                envelope = activity_envelope(record, self.status_entity)
                event_id, timestamp = envelope["event_id"], record["ts"]
                if timestamp > now:
                    raise ValueError("Future activity timestamp; retain the journal checkpoint")
                if event_id in seen:
                    continue
                if timestamp < state["activated_at"]:
                    state["before_activation_count"] += 1
                elif now - timestamp > MAX_AGE:
                    state["expired_count"] += 1
                    self._receipt(state, event_id, "expired", now)
                else:
                    if len(state["pending"]) >= MAX_PENDING:
                        raise ValueError("Wake queue full; journal checkpoint not advanced")
                    state["pending"][event_id] = envelope
                seen.add(event_id)
            state["cursor"] = page["next_cursor"]
            self._save(state)
            return {"has_more": page["has_more"], "pending_count": len(state["pending"])}

    def pending(self, now):
        """Return retry candidates with stable IDs, expiring late wakes explicitly."""
        now = _time(now)
        with self.lock:
            state = self._load()
            changed = False
            for event_id, envelope in list(state["pending"].items()):
                age = now - envelope["data"]["observed_at"]
                if age < 0:
                    raise ValueError("Clock precedes pending activity; do not transmit")
                if age > MAX_AGE:
                    del state["pending"][event_id]
                    state.setdefault("progress", {}).pop(event_id, None)
                    state["expired_count"] += 1
                    self._receipt(state, event_id, "expired", now)
                    changed = True
            if changed:
                self._save(state)
            return list(state["pending"].values())

    def confirm_processed(self, event_id, now):
        """Internal hook for a future authenticated, event-correlated receipt only.

        HTTP acceptance is not a receipt. No currently enabled caller invokes this.
        """
        now = _time(now)
        with self.lock:
            state = self._load()
            if event_id not in state["pending"]:
                raise ValueError("Receipt does not match a pending event")
            del state["pending"][event_id]
            self._receipt(state, event_id, "processed", now)
            self._save(state)

    def progress(self, event_id):
        with self.lock:
            state = self._load()
            return dict(state.get("progress", {}).get(event_id, {}))

    def update_progress(self, event_id, progress):
        """Persist retry/acceptance before the next network operation."""
        if set(progress) - {"attempts", "accepted", "next_attempt", "error", "turn", "delivery"}:
            raise ValueError("Unexpected wake progress fields")
        if type(progress.get("attempts", 0)) is not int or not 0 <= progress.get("attempts", 0) <= 8:
            raise ValueError("Invalid attempt count")
        _time(progress.get("next_attempt", 0))
        if type(progress.get("accepted", False)) is not bool:
            raise ValueError("Invalid acceptance state")
        with self.lock:
            state = self._load()
            if event_id not in state["pending"]:
                raise ValueError("Progress does not match a pending event")
            state.setdefault("progress", {})[event_id] = dict(progress)
            self._save(state)

    def finalize(self, event_id, outcome, now, receipt=None):
        """Retire only on a validated terminal receipt or explicit local failure."""
        if outcome not in ("delivered", "failed", "no_reply", "skipped", "suppressed", "expired"):
            raise ValueError("Invalid terminal outcome")
        with self.lock:
            state = self._load()
            if event_id not in state["pending"]:
                raise ValueError("Receipt does not match a pending event")
            del state["pending"][event_id]
            state.setdefault("progress", {}).pop(event_id, None)
            self._receipt(state, event_id, outcome, _time(now))
            if receipt:
                state["recent_receipts"][-1].update({k: receipt[k] for k in
                    ("event_ref", "turn", "delivery") if k in receipt})
            self._save(state)

    def summary(self):
        with self.lock:
            state = self._load()
            latest = state["recent_receipts"][-1] if state["recent_receipts"] else None
            # HA diagnostics omit full private event identities and journal cursor.
            latest = {k: v for k, v in latest.items() if k != "event_id"} if latest else None
            return {"activated_at": state["activated_at"], "pending_count": len(state["pending"]),
                    "expired_count": state["expired_count"], "last_receipt": latest,
                    "before_activation_count": state["before_activation_count"],
                    "pending_events": [{"event_ref": hashlib.sha256(event_id.encode()).hexdigest()[:12],
                        **state.get("progress", {}).get(event_id, {})}
                        for event_id in list(state["pending"])[:10]]}
