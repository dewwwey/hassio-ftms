"""Bounded durable publisher; networking never touches HA's event loop or recorder."""
import time
from .wake_transport import bearer_request, post_once, lookup_receipt


class WakePublisher:
    def __init__(self, queue, journal, url, token, *, lookup=lookup_receipt, post=post_once):
        self.queue, self.journal = queue, journal
        self.url, self.token = url, token
        self.lookup, self.post = lookup, post

    def tick(self, now=None):
        now = time.time() if now is None else now
        # Bound catch-up work, preserve checkpoint and resume next tick.
        for _ in range(20):
            if not self.queue.ingest(self.journal, now, limit=200)["has_more"]:
                break
        for envelope in self.queue.pending(now)[:2]:
            event_id = envelope["event_id"]
            progress = self.queue.progress(event_id)
            if progress.get("next_attempt", 0) > now:
                continue
            receipt = self.lookup(self.url, self.token, event_id, "ride_started")
            if receipt["found"]:
                if receipt["terminal"]:
                    outcome = receipt["delivery"]
                    if receipt["turn"] == "suppressed":
                        outcome = "suppressed"
                    elif receipt["turn"] == "failed":
                        outcome = "failed"
                    self.queue.finalize(event_id, outcome, now, receipt)
                else:
                    self.queue.update_progress(event_id, {**progress, "accepted": True,
                        "next_attempt": now + 15, "turn": receipt["turn"], "delivery": receipt["delivery"], "error": None})
                continue
            # Once accepted, only poll; a lost/evicted receipt must never replay a turn.
            if progress.get("accepted"):
                self.queue.update_progress(event_id, {**progress, "next_attempt": now + 30,
                    "error": receipt["error"] or "receipt_missing_after_acceptance"})
                continue
            attempts = progress.get("attempts", 0)
            if attempts >= 8:
                self.queue.finalize(event_id, "failed", now)
                continue
            attempts += 1
            progress = {**progress, "attempts": attempts, "accepted": False,
                        "next_attempt": now + min(300, 15 * 2 ** (attempts - 1)),
                        "error": receipt["error"]}
            # Commit before POST: ambiguous failures retain the original identity.
            self.queue.update_progress(event_id, progress)
            if not receipt["missing"]:
                continue
            result = self.post(bearer_request(self.url, self.token, envelope))
            accepted = (result["http_accepted"] and result["error"] is None
                        and (result["accepted"] is True or result["duplicate"] is True))
            self.queue.update_progress(event_id, {**progress, "accepted": bool(accepted),
                "error": result["error"] or (None if accepted else "acceptance_unconfirmed")})
        return self.queue.summary()
