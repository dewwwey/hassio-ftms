"""Persistence and network ambiguity checks using synthetic local journals only."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

root = Path(__file__).parents[1] / "custom_components/ftms"
package = ModuleType("publisher_test_package")
package.__path__ = [str(root)]
sys.modules[package.__name__] = package

def load(name):
    spec = importlib.util.spec_from_file_location(package.__name__ + "." + name, root / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

outbox = load("wake_outbox")
transport = load("wake_transport")
publisher = load("wake_publisher")
runtime = load("wake_runtime")

class Response(io.BytesIO):
    status = 200

class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.journal = self.path / "journal.jsonl"
        self.journal.write_text(json.dumps({"kind":"activity_started", "event_id":"synthetic-event", "ts":101}) + "\n")
        self.queue = outbox.WakeOutbox(self.path / "queue.json", "synthetic-source", "sensor.bike_diagnostics")
        self.queue.initialize(100)
        self.posts = []
        self.receipt = {"found":False,"missing":True,"error":None}
        self.post_result = {"http_accepted":True,"accepted":True,"duplicate":False,"error":None}
        def post(request):
            self.posts.append(json.loads(request.data))
            return self.post_result
        self.worker = publisher.WakePublisher(self.queue,self.journal,"https://example.invalid/wake","synthetic",lookup=lambda *a:self.receipt,post=post)

    def terminal(self, delivery="delivered", turn="completed"):
        return {"found":True,"missing":False,"error":None,"terminal":True,
                "turn":turn,"delivery":delivery,"event_ref":hashlib.sha256(b"synthetic-event").hexdigest()[:12]}

    def test_accepted_event_is_only_polled_across_restart_even_if_receipt_missing(self):
        self.worker.tick(102)
        self.assertEqual(len(self.posts),1)
        reloaded = outbox.WakeOutbox(self.path / "queue.json","synthetic-source","sensor.bike_diagnostics")
        self.worker.queue = reloaded
        self.worker.tick(200)
        self.assertEqual(len(self.posts),1)
        self.assertEqual(reloaded.summary()["pending_count"],1)
        self.receipt = self.terminal()
        result = self.worker.tick(300)
        self.assertEqual(result["last_receipt"]["outcome"],"delivered")
        self.assertEqual(result["pending_count"],0)
        self.worker.tick(400)
        self.assertEqual(len(self.posts),1)

    def test_ambiguous_post_cannot_replay_when_receiver_already_has_receipt(self):
        self.post_result = {"http_accepted":False,"accepted":None,"duplicate":None,"error":"transport_unavailable"}
        self.worker.tick(102)
        self.receipt = self.terminal()
        self.worker.tick(200)
        self.assertEqual(len(self.posts),1)
        self.assertEqual(self.queue.summary()["last_receipt"]["outcome"],"delivered")

    def test_same_id_and_backoff_when_server_confirmed_missing(self):
        self.post_result = {"http_accepted":False,"accepted":None,"duplicate":None,"error":"transport_unavailable"}
        self.worker.tick(102)
        self.worker.tick(103)
        self.assertEqual(len(self.posts),1)
        self.worker.tick(118)
        self.assertEqual(len(self.posts),2)
        self.assertEqual(self.posts[0],self.posts[1])
        self.assertNotIn("session_id",str(self.posts))

    def test_untrusted_status_cannot_trigger_post_or_finalize(self):
        self.receipt = {"found":False,"missing":False,"error":"receipt_invalid"}
        for t in range(102,3700,301):
            self.worker.tick(t)
        self.assertEqual(self.posts,[])
        self.assertEqual(self.queue.summary()["last_receipt"]["outcome"],"failed")

    def test_pending_processing_and_delivery_stages_are_not_success(self):
        self.receipt = {**self.terminal("pending"),"terminal":False}
        self.worker.tick(102)
        self.assertEqual(self.queue.summary()["pending_count"],1)
        self.assertIsNone(self.queue.summary()["last_receipt"])
        self.assertEqual(self.queue.progress("synthetic-event")["delivery"],"pending")
        self.assertEqual(self.posts,[])

    def test_no_reply_suppression_and_delivery_failure_remain_truthful(self):
        for delivery,turn,outcome in [("no_reply","completed","no_reply"),("skipped","suppressed","suppressed"),("failed","completed","failed")]:
            with self.subTest(delivery=delivery):
                directory = self.path / delivery
                queue = outbox.WakeOutbox(directory / "queue.json","synthetic-source","sensor.bike_diagnostics")
                queue.initialize(100)
                self.worker.queue=queue
                self.receipt=self.terminal(delivery,turn)
                result=self.worker.tick(102)
                self.assertEqual(result["last_receipt"]["outcome"],outcome)
                self.assertEqual(result["pending_count"],0)

    def test_expiry_removes_retry_metadata_and_never_transmits(self):
        self.worker.tick(102)
        self.worker.tick(4000)
        state=json.loads((self.path / "queue.json").read_text())
        self.assertEqual(len(self.posts),1)
        self.assertEqual(state["progress"],{})
        self.assertEqual(state["recent_receipts"][-1]["outcome"],"expired")

    def test_failed_retry_checkpoint_prevents_network_write(self):
        with patch.object(self.queue,"update_progress",side_effect=OSError("synthetic")):
            with self.assertRaises(OSError):
                self.worker.tick(102)
        self.assertEqual(self.posts,[])

    def test_disabled_setup_never_loads_profile_or_initializes_queue(self):
        self.assertIsNone(runtime.load_publisher(self.path))
        (self.path / ".ftms_wake_publisher.json").write_text('{"enabled":false}')
        self.assertIsNone(runtime.load_publisher(self.path))
        self.assertFalse((self.path / ".storage").exists())

class ReceiptTests(unittest.TestCase):
    def receipt(self):
        return {"event_ref":hashlib.sha256(b"test-event").hexdigest()[:12],"source":"home-assistant","task":"test_ping","turn":"completed","delivery":"skipped","terminal":True,"pending":False,"assistant_text":"must never escape"}
    def lookup(self,payload):
        opener=SimpleNamespace(open=lambda *a,**k:Response(json.dumps(payload).encode()))
        return transport.lookup_receipt("https://example.invalid/wake","synthetic","test-event","test_ping",opener=opener)
    def test_correlated_receipt_drops_all_arbitrary_fields(self):
        result=self.lookup(self.receipt())
        self.assertTrue(result["found"])
        self.assertTrue(result["terminal"])
        self.assertNotIn("assistant_text",str(result))
        self.assertNotIn("must never escape",str(result))
    def test_mismatched_or_inconsistent_receipt_is_rejected(self):
        for field,value in [("event_ref","wrong"),("source","other"),("task","ride_started"),("terminal",False),("pending",True),("turn","unknown"),("delivery","unknown")]:
            p=self.receipt();p[field]=value
            with self.subTest(field=field):
                self.assertFalse(self.lookup(p)["found"])
        p=self.receipt();p.update(turn="failed",delivery="delivered")
        self.assertFalse(self.lookup(p)["found"])
    def test_authenticated_lookup_stays_on_configured_origin_and_encodes_id(self):
        request=transport.receipt_request("https://example.invalid/wake","synthetic","a?x&y/z")
        self.assertEqual(request.full_url,"https://example.invalid/wake/status?event_id=a%3Fx%26y%2Fz")
        self.assertEqual(request.method,"GET")
        self.assertIsNone(request.data)
        self.assertEqual(request.get_header("Authorization"),"Bearer synthetic")
    def test_404_is_distinct_from_auth_failure_and_redirect(self):
        for code in (404,401,302):
            def fail(*a,**k):raise HTTPError("https://example.invalid",code,"private",{},io.BytesIO())
            result=transport.lookup_receipt("https://example.invalid/wake","synthetic","test-event","test_ping",opener=SimpleNamespace(open=fail))
            self.assertEqual(result["missing"],code==404)
            self.assertFalse(result["found"])
            self.assertNotIn("private",str(result))
