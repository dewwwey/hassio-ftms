"""Synthetic wake transport tests; never send a real ride or touch credentials."""
import hashlib
import hmac
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from urllib.error import HTTPError, URLError

spec = importlib.util.spec_from_file_location("wake_test", Path(__file__).parents[1] / "custom_components/ftms/wake_transport.py")
wake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wake)


class Response(io.BytesIO):
    def __init__(self, body, status=202):
        super().__init__(body)
        self.status = status


class WakeTests(unittest.TestCase):
    def request(self):
        return wake.signed_request("https://example.invalid/wake", "synthetic-only",
                                   wake.ping_envelope("test-1"), 100)

    def test_activity_envelope_omits_private_metrics_and_source_identifiers(self):
        envelope = wake.activity_envelope({"kind": "activity_started", "ts": 100,
            "event_id": "event-1", "session_id": "private-session",
            "config_entry_id": "private-entry", "heart_rate": 80}, "sensor.bike_diagnostics")
        self.assertEqual(envelope["data"], {"status_entity": "sensor.bike_diagnostics", "observed_at": 100})
        text = json.dumps(envelope)
        self.assertNotIn("private-", text)
        self.assertNotIn("heart_rate", text)
        self.assertEqual(envelope["task"], "ride_started")

    def test_ping_cannot_select_a_ride_task(self):
        self.assertEqual(wake.ping_envelope("probe")["task"], "test_ping")
        with self.assertRaises(ValueError):
            wake.activity_envelope({"kind": "heartbeat"}, "sensor.bike")

    def test_invalid_observation_is_not_a_wake(self):
        for timestamp in (None, True, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                wake.activity_envelope({"kind": "activity_started", "event_id": "e", "ts": timestamp}, "sensor.bike")

    def test_signature_covers_exact_body_and_timestamp_without_sending_secret(self):
        request = self.request()
        signature = hmac.new(b"synthetic-only", b"100." + request.data, hashlib.sha256).hexdigest()
        self.assertEqual(request.get_header("X-wake-signature"), "t=100,v1=" + signature)
        self.assertNotIn(b"synthetic-only", request.data)
        self.assertNotIn("synthetic-only", str(request.headers))
        self.assertEqual(request.data, self.request().data)

    def test_rejects_credentials_in_urls_and_unexpected_routes(self):
        for url in ("https://user:password@example.invalid/wake", "https://example.invalid/wake?key=x",
                    "https://example.invalid/other", "file:///wake"):
            with self.assertRaises(ValueError):
                wake.signed_request(url, "test", wake.ping_envelope("e"), 100)

    def test_acceptance_and_even_processed_text_are_not_a_correlated_ack(self):
        for status in ("accepted", "duplicate", "suppressed", "processed"):
            opener = SimpleNamespace(open=lambda *a, **k: Response(json.dumps({"status": status}).encode()))
            result = wake.post_once(self.request(), opener=opener)
            self.assertTrue(result["http_accepted"])
            self.assertFalse(result["processing_acknowledged"])
            self.assertEqual(result["receiver_status"], status)

    def test_redirect_is_not_followed_and_http_errors_are_sanitized(self):
        self.assertIsNone(wake._NoRedirect().redirect_request(self.request(), None, 302, "", {}, "https://other.invalid/wake"))
        def rejected(*args, **kwargs):
            raise HTTPError("https://example.invalid/wake", 401, "private text", {}, io.BytesIO(b"secret"))
        result = wake.post_once(self.request(), opener=SimpleNamespace(open=rejected))
        self.assertEqual(result["http_status"], 401)
        self.assertFalse(result["http_accepted"])
        self.assertNotIn("private text", str(result))

    def test_network_failures_and_response_limits_do_not_leak_content(self):
        def unavailable(*args, **kwargs):
            raise URLError("private internal details")
        result = wake.post_once(self.request(), opener=SimpleNamespace(open=unavailable))
        self.assertEqual(result["error"], "transport_unavailable")
        self.assertNotIn("private", str(result))
        for body, expected in ((b"invalid", "invalid_response"), (b"x" * (wake.MAX_RESPONSE + 1), "response_too_large")):
            result = wake.post_once(self.request(), opener=SimpleNamespace(open=lambda *a, **k: Response(body)))
            self.assertEqual(result["error"], expected)
            self.assertFalse(result["processing_acknowledged"])

    def test_timeout_is_bounded(self):
        for timeout in (0, 11, True, float("nan")):
            with self.assertRaises(ValueError):
                wake.post_once(self.request(), timeout=timeout)

    def test_bearer_profile_uses_header_only_and_rejects_header_injection(self):
        request = wake.bearer_request("https://example.invalid/wake", "synthetic-only", wake.ping_envelope("e"))
        self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-only")
        self.assertNotIn(b"synthetic-only", request.data)
        self.assertNotIn("synthetic-only", request.full_url)
        with self.assertRaises(ValueError):
            wake.bearer_request("https://example.invalid/wake", "bad\r\nheader", wake.ping_envelope("e"))

    def test_boolean_receipt_fields_do_not_claim_processing_completion(self):
        body = b'{"accepted":false,"duplicate":true,"woke":false}'
        result = wake.post_once(self.request(), opener=SimpleNamespace(open=lambda *a, **k: Response(body)))
        self.assertTrue(result["http_accepted"])
        self.assertTrue(result["duplicate"])
        self.assertFalse(result["accepted"])
        self.assertFalse(result["woke"])
        self.assertFalse(result["processing_acknowledged"])
