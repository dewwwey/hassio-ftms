"""One manually requested real-event delivery; no timer, bus listener or polling worker."""
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path('/config')

def save(path, value):
    tmp = path.with_suffix('.tmp')
    with tmp.open('w') as stream:
        json.dump(value, stream, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)

def select_event(journal, event_id, now):
    if not re.fullmatch(r'[0-9a-f]{24}', event_id):
        raise ValueError('Invalid event identity')
    latest = None
    sample_times = set()
    matched_sample = False
    for line in journal.splitlines():
        record = json.loads(line)
        if record.get('kind') == 'sample':
            cadence = record.get('metrics', {}).get('cadence_instant')
            if type(cadence) in (int, float) and math.isfinite(cadence) and cadence > 0:
                sample_times.add(record['ts'])
        elif record.get('kind') in ('activity_started', 'activity_resumed'):
            latest = record
            matched_sample = record.get('ts') in sample_times
    if latest is None or latest.get('event_id') != event_id:
        raise ValueError('Requested event is not latest durable activity')
    ts = latest.get('ts')
    if type(ts) not in (int, float) or not math.isfinite(ts) or not 0 <= now-ts <= 600:
        raise ValueError('Activity is outside supervised acceptance window')
    if not matched_sample:
        raise ValueError('No matching activity sample')
    if not re.fullmatch(r'[0-9a-f]{24}', latest.get('session_id', '')):
        raise ValueError('No valid recorded session')
    return latest

def main():
    import yaml
    request = json.loads((ROOT/'.storage/ftms_wake_acceptance_request.json').read_text())
    now = time.time()
    expires = request.get('expires_at')
    if type(expires) not in (int, float) or not math.isfinite(expires) or not now < expires <= now+600:
        raise ValueError('Acceptance request expired or invalid')
    journal_path = Path(request['journal']).resolve()
    expected_parent = (ROOT/'.storage/ftms').resolve()
    if journal_path.parent != expected_parent or journal_path.suffix != '.jsonl':
        raise ValueError('Unexpected journal path')
    journal = journal_path.read_text()
    if journal and not journal.endswith('\n'):
        raise ValueError('Journal has an incomplete trailing record')
    event = select_event(journal, request['event_id'], now)
    spec = importlib.util.spec_from_file_location('acceptance_wake_transport', ROOT/'custom_components/ftms/wake_transport.py')
    transport = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(transport)
    profile = yaml.safe_load((ROOT/'.basilisk_wake_staging.yaml').read_text())
    if profile.get('source') != 'home-assistant' or profile['auth']['type'] != 'bearer':
        raise ValueError('Unsupported private source profile')
    envelope = transport.activity_envelope(event, 'sensor.kettler_ftms_diagnostics')
    result = {'event_id':event['event_id'], 'sent_at': now,
              **transport.post_once(transport.bearer_request(profile['receiver']['url'], profile['auth']['token'], envelope))}
    save(ROOT/'.storage/ftms_wake_acceptance_receipt.json', result)
    print(json.dumps(result, sort_keys=True))
    return 0 if result['http_accepted'] and result['error'] is None else 1

if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({'error_type':type(exc).__name__, 'acceptance_failed':True}))
        sys.exit(1)
