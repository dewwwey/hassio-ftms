"""HA lifecycle for the private, opt-in FTMS coaching publisher."""
import asyncio
from datetime import timedelta, datetime, timezone
import json
from pathlib import Path
import re
from time import time
from uuid import uuid4

from .wake_outbox import WakeOutbox
from .wake_publisher import WakePublisher
from .wake_transport import bearer_request, post_once, lookup_receipt, ping_envelope, demo_ping_envelope

ENTITY = "sensor.kettler_coach_delivery"


def load_publisher(config_root):
    """Existing queue required: never silently reset a lost checkpoint."""
    root = Path(config_root)
    settings_path = root / ".ftms_wake_publisher.json"
    if not settings_path.exists():
        return None
    settings = json.loads(settings_path.read_text())
    if settings.get("enabled") is not True:
        return None
    source = settings["config_entry_id"]
    if not isinstance(source, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", source):
        raise ValueError("Invalid publisher source")
    import yaml
    profile = yaml.safe_load((root / ".basilisk_wake_staging.yaml").read_text())
    if profile.get("source") != "home-assistant" or profile["auth"]["type"] != "bearer":
        raise ValueError("Unsupported publisher profile")
    queue = WakeOutbox(root / ".storage" / "ftms" / (source + ".wake.json"),
                       source, "sensor.kettler_ftms_diagnostics")
    summary = queue.summary()
    if summary["activated_at"] != settings["activated_at"]:
        raise ValueError("Publisher activation mismatch")
    # Validate URL/header before enabling any callback.
    bearer_request(profile["receiver"]["url"], profile["auth"]["token"], ping_envelope("validation-only"))
    return WakePublisher(queue, root / ".storage" / "ftms" / (source + ".jsonl"),
                         profile["receiver"]["url"], profile["auth"]["token"])


def save_probe(path, value):
    """Durable synthetic identity before request; contains no credential."""
    import os
    temp = path.with_suffix(".tmp")
    with temp.open("w") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


async def async_setup_publisher(hass):
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP
    from homeassistant.helpers.event import async_track_time_interval
    from homeassistant.core import SupportsResponse
    import voluptuous as vol

    lock = asyncio.Lock()
    stopping = False
    last_notice = None
    publisher = None
    setup_error = None
    try:
        publisher = await hass.async_add_executor_job(load_publisher, hass.config.config_dir)
    except Exception as exc:
        setup_error = type(exc).__name__

    async def publish_status(summary=None, error=None):
        nonlocal last_notice
        summary = summary or {}
        latest = summary.get("last_receipt") or {}
        state = ("error" if error else "disabled" if publisher is None else
                 "pending" if summary.get("pending_count", 0) else latest.get("outcome", "armed"))
        hass.states.async_set(ENTITY, state, {"friendly_name": "Bike coaching delivery",
            "icon": "mdi:message-check-outline", "checked_at": time(),
            "enabled": publisher is not None, "error": error, **summary})
        failure = error or (latest.get("outcome") if latest.get("outcome") in
                            ("failed", "no_reply", "skipped", "suppressed", "expired") else None)
        notice_key = (failure, latest.get("at")) if failure else None
        if failure and notice_key != last_notice:
            await hass.services.async_call("persistent_notification", "create", {
                "notification_id": "ftms_coach_delivery", "title": "Bike coaching needs attention",
                "message": "Automatic coaching delivery could not be confirmed. Bike recording is separate. Check Bike coaching delivery in HA."}, blocking=True)
        elif latest.get("outcome") == "delivered" and last_notice:
            await hass.services.async_call("persistent_notification", "dismiss", {
                "notification_id": "ftms_coach_delivery"}, blocking=True)
        last_notice = notice_key

    async def tick(event=None):
        if stopping or lock.locked() or publisher is None:
            return
        async with lock:
            try:
                summary = await hass.async_add_executor_job(publisher.tick)
                await publish_status(summary)
            except Exception as exc:
                # Never expose receiver/profile/exception text, and never stop recording.
                await publish_status(error=type(exc).__name__)

    async def status(call):
        state = hass.states.get(ENTITY)
        return {"state": state.state, **dict(state.attributes)} if state else {"state": "unknown"}

    def probe_once(task="test_ping", new_probe=False):
        # Allow only the receiver's fixed synthetic tasks, never ride_started.
        if task not in ("test_ping", "demo_ping"):
            raise ValueError("Unsupported synthetic wake task")
        report_path = Path(hass.config.path(".storage", "ftms_coach_" + task + "_probe.json"))
        previous = {} if new_probe or not report_path.exists() else json.loads(report_path.read_text())
        identity = previous.get("event_id")
        if not identity:
            prefix = "ha-ftms-demo-ping-" if task == "demo_ping" else "ha-ftms-test-ping-"
            identity = prefix + uuid4().hex
            envelope = (demo_ping_envelope(identity, datetime.now(timezone.utc).isoformat())
                        if task == "demo_ping" else ping_envelope(identity))
            previous = {"event_id": identity, "envelope": envelope, "post_attempted": False}
            save_probe(report_path, previous)
        if previous.get("envelope", {}).get("task") != task:
            raise ValueError("Saved synthetic task does not match")
        receipt = lookup_receipt(publisher.url, publisher.token, identity, task)
        result = None
        if receipt["missing"] and not previous.get("post_attempted", False):
            # Persist before POST; an ambiguous result never causes a second turn.
            previous["post_attempted"] = True
            save_probe(report_path, previous)
            request = bearer_request(publisher.url, publisher.token, previous["envelope"])
            result = post_once(request)
            receipt = lookup_receipt(publisher.url, publisher.token, identity, task)
        report = {"event_id": identity, "post_attempted": previous.get("post_attempted", False),
                  "checked_at": time(), "post": result, "receipt": receipt}
        save_probe(report_path, {**previous, **report})
        return {"event_ref": __import__("hashlib").sha256(identity.encode()).hexdigest()[:12],
                "post": result, "receipt": receipt}

    async def test_probe(call):
        if publisher is None:
            return {"error": "publisher_unavailable"}
        async with lock:
            return await hass.async_add_executor_job(probe_once, "test_ping", call.data.get("new_probe", False))

    async def demo_probe(call):
        if publisher is None:
            return {"error": "publisher_unavailable"}
        async with lock:
            return await hass.async_add_executor_job(probe_once, "demo_ping", call.data.get("new_probe", False))

    hass.services.async_register("ftms", "get_coach_delivery", status,
                                 schema=vol.Schema({}), supports_response=SupportsResponse.ONLY)
    probe_schema = vol.Schema({vol.Optional("new_probe", default=False): bool})
    hass.services.async_register("ftms", "test_coach_wake", test_probe,
                                 schema=probe_schema, supports_response=SupportsResponse.ONLY)
    hass.services.async_register("ftms", "demo_coach_ping", demo_probe,
                                 schema=probe_schema, supports_response=SupportsResponse.ONLY)
    await publish_status(error=setup_error)
    if publisher is None:
        return
    unsub_interval = async_track_time_interval(hass, tick, timedelta(seconds=15))
    unsub_event = hass.bus.async_listen("ftms_activity", tick)

    async def stop(event):
        nonlocal stopping
        stopping = True
        unsub_interval()
        unsub_event()
        # A running executor request is bounded; preserve its durable pending state.
        async with lock:
            pass

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop)
    hass.async_create_task(tick())
