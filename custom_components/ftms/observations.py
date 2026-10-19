"""Bounded incremental reads of the private append-only observation journal."""
import base64
import hashlib
import json
from .sessions import Sessions

MAX_LINE = 65536


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _cursor(source, offset, previous):
    payload = json.dumps([1, _digest(source.encode())[:16], offset, len(previous),
                          _digest(previous)], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode()


def read_page(path, source, cursor=None, limit=100):
    """Never skip a partial final line; reject changed/truncated cursor history."""
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    offset, previous = 0, b""
    if cursor:
        try:
            if len(cursor) > 512:
                raise ValueError
            version, identity, offset, length, digest = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
            if (version != 1 or identity != _digest(source.encode())[:16]
                    or type(offset) is not int or type(length) is not int
                    or offset < 0 or not 0 <= length <= MAX_LINE or length > offset):
                raise ValueError
        except (ValueError, TypeError, UnicodeError) as exc:
            raise ValueError("Invalid observation cursor") from exc
    else:
        length, digest = 0, _digest(b"")
    records = []
    if not path.exists():
        if offset:
            raise ValueError("Journal missing; retain the cursor and investigate")
        return {"records": [], "next_cursor": _cursor(source, 0, b""), "has_more": False}
    with path.open("rb") as stream:
        stream.seek(0, 2)
        if stream.tell() < offset:
            raise ValueError("Journal truncated; retain the cursor and investigate")
        stream.seek(offset - length)
        previous = stream.read(length)
        if _digest(previous) != digest or (offset and not previous.endswith(b"\n")):
            raise ValueError("Journal changed; retain the cursor and investigate")
        stream.seek(offset)
        for _ in range(limit):
            start = stream.tell()
            line = stream.readline(MAX_LINE + 1)
            if len(line) > MAX_LINE:
                raise ValueError("Oversized journal record")
            if not line.endswith(b"\n"):
                break
            record = json.loads(line)
            if not isinstance(record, dict) or "kind" not in record or "ts" not in record:
                raise ValueError("Invalid journal record")
            record = dict(record)
            record["record_id"] = _digest(source.encode() + str(start).encode() + line)[:24]
            records.append(record)
            offset, previous = stream.tell(), line
        stream.seek(offset)
        following = stream.readline(MAX_LINE + 1)
        if len(following) > MAX_LINE:
            raise ValueError("Oversized journal record")
        more = following.endswith(b"\n")
    return {"records": records, "next_cursor": _cursor(source, offset, previous), "has_more": more}


def read_snapshot(path, source):
    """Recover last-seen/event metadata even when no config-entry runtime exists."""
    result = {"last_received_ts": None, "last_activity_ts": None,
              "last_persisted_ts": None, "latest_event": None,
              "current_session": None, "last_session": None,
              "completed_count": 0, "observed_metrics": [],
              "observed_metrics_scope": "journal_history"}
    if not path.exists():
        return result
    sessions = Sessions(source)
    observed = set()
    with path.open("rb") as stream:
        for line in stream:
            if not line.endswith(b"\n"):
                break
            record = json.loads(line)
            sessions.apply(record)
            result["last_persisted_ts"] = record["ts"]
            if record["kind"] == "sample":
                observed.update(record["metrics"])
                result["last_received_ts"] = record["ts"]
                if record.get("metrics", {}).get("cadence_instant", 0) > 0:
                    result["last_activity_ts"] = record["ts"]
            elif record["kind"] in ("heartbeat", "disconnect") and record.get("last_received_ts") is not None:
                result["last_received_ts"] = record["last_received_ts"]
            elif record["kind"] in ("activity_started", "activity_resumed"):
                result["latest_event"] = record
    result.update(current_session=sessions.current, last_session=sessions.last,
                  completed_count=sessions.completed_count,
                  observed_metrics=sorted(observed))
    return result
