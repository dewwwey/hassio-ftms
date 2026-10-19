"""One scoped synthetic wake probe from HA. Never sends ride_started."""
import importlib.util
import argparse
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import yaml


def save(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--new-probe", action="store_true")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("ftms_wake_probe_transport", "/config/custom_components/ftms/wake_transport.py")
    transport = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(transport)
    profile = yaml.safe_load(Path("/config/.basilisk_wake_staging.yaml").read_text())
    if profile.get("source") != "home-assistant" or profile["auth"]["type"] != "bearer":
        raise ValueError("Unsupported private probe profile")
    report_path = Path("/config/.storage/ftms_wake_test_ping.json")
    if report_path.exists() and not args.new_probe:
        previous = json.loads(report_path.read_text())
        identity = previous["event_id"]
    else:
        identity = "ha-ftms-test-ping-" + uuid4().hex
        save(report_path, {"event_id": identity, "status": "prepared"})
    request = transport.bearer_request(profile["receiver"]["url"], profile["auth"]["token"],
                                       transport.ping_envelope(identity))
    result = {"event_id": identity, **transport.post_once(request)}
    # Diagnostic receipts contain no credential or arbitrary receiver text.
    save(report_path, result)
    with report_path.with_suffix(".jsonl").open("a") as history:
        history.write(json.dumps(result, sort_keys=True) + "\n")
        history.flush()
        os.fsync(history.fileno())
    print(json.dumps(result, sort_keys=True))
    return 0 if result["http_accepted"] and result["error"] is None else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        # No exception messages: they can contain URLs or private profile values.
        print(json.dumps({"error_type": type(exc).__name__, "probe_failed": True}))
        sys.exit(1)
