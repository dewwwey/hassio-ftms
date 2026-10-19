"""Private wake request preparation; not registered or enabled in Home Assistant.

HTTP acceptance is deliberately distinct from a processed coach acknowledgement.
Run blocking I/O in an executor when wiring this adapter into HA.
"""
import hashlib
import hmac
import json
import math
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_RESPONSE = 16384


def activity_envelope(event, status_entity):
    """Only durable HA activity events may enter this path; never forward metrics."""
    if event.get("kind") not in ("activity_started", "activity_resumed"):
        raise ValueError("Expected a durable FTMS activity event")
    event_id, timestamp = event.get("event_id"), event.get("ts")
    if not isinstance(event_id, str) or not 1 <= len(event_id) <= 128:
        raise ValueError("Missing or invalid event identity")
    if (type(timestamp) not in (int, float) or not math.isfinite(timestamp)
            or timestamp < 0):
        raise ValueError("Invalid activity timestamp")
    if not isinstance(status_entity, str) or not status_entity.startswith("sensor."):
        raise ValueError("Expected a diagnostic sensor entity")
    return {"event_id": event_id, "source": "home-assistant", "task": "ride_started",
            "expect_ack": True,
            "data": {"status_entity": status_entity, "observed_at": timestamp}}


def ping_envelope(event_id):
    """Synthetic transport probes cannot select the ride notification task."""
    if not isinstance(event_id, str) or not 1 <= len(event_id) <= 128:
        raise ValueError("Missing or invalid test identity")
    return {"event_id": event_id, "source": "home-assistant", "task": "test_ping",
            "expect_ack": True}



def demo_ping_envelope(event_id, when):
    """Basilisk's explicitly allowlisted, user-requested Telegram demo task."""
    from datetime import datetime
    if not isinstance(event_id, str) or not event_id.startswith("ha-ftms-demo-ping-") or not 1 <= len(event_id) <= 200:
        raise ValueError("Invalid synthetic demo identity")
    if not isinstance(when, str):
        raise ValueError("Demo timestamp must be ISO 8601")
    try:
        parsed = datetime.fromisoformat(when.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Demo timestamp must be ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Demo timestamp must include a timezone")
    return {"event_id": event_id, "source": "home-assistant", "task": "demo_ping",
            "when": when, "data": {"demo": True}, "expect_ack": False}


def _request(url, envelope):
    parts = urlsplit(url)
    if (parts.scheme not in ("http", "https") or not parts.hostname
            or parts.username is not None or parts.password is not None
            or parts.query or parts.fragment or parts.path != "/wake"):
        raise ValueError("Expected the configured HTTP(S) /wake endpoint without credentials")
    body = json.dumps(envelope, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(body) > 16384:
        raise ValueError("Wake envelope exceeds receiver limit")
    return Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})


def bearer_request(url, token, envelope):
    """Use the administrator-provided dedicated source credential, without logging it."""
    if not isinstance(token, str) or not token or "\r" in token or "\n" in token:
        raise ValueError("Missing or invalid private source credential")
    request = _request(url, envelope)
    request.add_header("Authorization", "Bearer " + token)
    return request


def signed_request(url, secret, envelope, timestamp):
    """Sign the exact transmitted bytes using the receiver's published contract."""
    if not isinstance(secret, str) or not secret:
        raise ValueError("Missing private source secret")
    if type(timestamp) is not int or timestamp < 0:
        raise ValueError("Expected an integer signing timestamp")
    request = _request(url, envelope)
    body = request.data
    signed = str(timestamp).encode() + b"." + body
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    request.add_header("X-Wake-Signature", f"t={timestamp},v1={digest}")
    return request


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def post_once(request, *, timeout=5, opener=None):
    """Send once; caller retains event identity for retries and durable receipts.

Never follow a redirect with the signed payload. Do not return arbitrary receiver
text or exception messages: either may contain private data. No processing-ack
schema is agreed yet, so no response can claim that the coach processed a wake.
"""
    if type(timeout) not in (int, float) or not 0 < timeout <= 10:
        raise ValueError("Timeout must be positive and no greater than ten seconds")
    opener = opener or build_opener(_NoRedirect())
    result = {"http_status": None, "http_accepted": False,
              "processing_acknowledged": False, "receiver_status": None, "error": None,
              "accepted": None, "duplicate": None, "woke": None}
    try:
        with opener.open(request, timeout=timeout) as response:
            result["http_status"] = response.status
            result["http_accepted"] = 200 <= response.status < 300
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                result["error"] = "response_too_large"
                return result
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeError):
                result["error"] = "invalid_response"
                return result
            if isinstance(payload, dict) and payload.get("status") in (
                    "accepted", "duplicate", "suppressed", "pending", "processed", "rejected"):
                result["receiver_status"] = payload["status"]
            if isinstance(payload, dict):
                for key in ("accepted", "duplicate", "woke"):
                    if type(payload.get(key)) is bool:
                        result[key] = payload[key]
    except HTTPError as exc:
        result["http_status"] = exc.code
        result["error"] = "http_rejected"
        exc.close()
    except (URLError, OSError, TimeoutError):
        result["error"] = "transport_unavailable"
    return result


def receipt_request(url, token, event_id):
    """Only the source-authenticated status route on the configured wake origin."""
    from urllib.parse import quote
    request = bearer_request(url, token, ping_envelope(event_id))
    return Request(url + "/status?event_id=" + quote(event_id, safe=""), method="GET",
                   headers={"Authorization": request.get_header("Authorization")})


def lookup_receipt(url, token, event_id, task, *, timeout=5, opener=None):
    """Validate correlation and allowlist receipt fields; never return raw text."""
    if type(timeout) not in (int, float) or not 0 < timeout <= 10:
        raise ValueError("Invalid receipt timeout")
    request = receipt_request(url, token, event_id)
    opener = opener or build_opener(_NoRedirect())
    result = {"found": False, "missing": False, "error": None}
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                return {**result, "error": "receipt_http_rejected"}
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                return {**result, "error": "receipt_too_large"}
            p = json.loads(raw)
            expected = hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:12]
            if (not isinstance(p, dict) or p.get("event_ref") != expected
                    or p.get("source") != "home-assistant" or p.get("task") != task
                    or p.get("turn") not in ("pending", "completed", "failed", "suppressed")
                    or p.get("delivery") not in ("pending", "delivered", "failed", "no_reply", "skipped")
                    or type(p.get("terminal")) is not bool or type(p.get("pending")) is not bool):
                return {**result, "error": "receipt_invalid"}
            terminal = p["turn"] != "pending" and p["delivery"] != "pending"
            if p["terminal"] != terminal or p["pending"] == terminal:
                return {**result, "error": "receipt_inconsistent"}
            if p["delivery"] == "delivered" and p["turn"] != "completed":
                return {**result, "error": "receipt_inconsistent"}
            return {**result, "found": True, "event_ref": expected,
                    "turn": p["turn"], "delivery": p["delivery"], "terminal": terminal}
    except HTTPError as exc:
        code = exc.code
        exc.close()
        return {**result, "missing": code == 404,
                "error": None if code == 404 else "receipt_http_rejected"}
    except (ValueError, UnicodeError):
        return {**result, "error": "receipt_invalid"}
    except (URLError, OSError, TimeoutError):
        return {**result, "error": "receipt_unavailable"}
