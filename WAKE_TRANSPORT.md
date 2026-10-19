# Private coaching wake transport checkpoint

`custom_components/ftms/wake_transport.py` is deployed for scoped synthetic
`test_ping` probes only. It is not connected to a ride automation or production
publisher. Runtime FTMS remains dev5; the durable queue and intensity helper are
not deployed. The full source suite has 79 passing tests, including eleven sender
and eight queue tests. Those tests use synthetic events and responses.

The administrator supplied a private Bearer profile at
`/config/.basilisk_wake_staging.yaml`; it is excluded by the configuration root's
Git ignore file. Non-secret response-note syntax was corrected after HA's YAML
parser rejected the supplied file. No credential was copied into source, command
arguments, diagnostic reports or NEXUS. HMAC support remains available, but the
supplied Bearer profile is what the live probe uses.

The PC-side test verified first acceptance, same-ID deduplication, invalid-auth
401 and a matching processed event ID in health. The first HA-side probe verified
HTTP 202 from HA and same-ID deduplication. Its `woke=false` and increased
suppression count reflected the five-minute test-task cooldown. The matching
`last_processed_event_id` does not prove an agent turn: suppressed events can
also reach that marker. A fresh HA probe after cooldown then returned
`accepted=true`, `duplicate=false`, `woke=true`; health subsequently showed its
exact processed event ID with no pending work. Replaying it returned
`duplicate=true`, `woke=false`. This verifies the synthetic HA-to-receiver wake
route, not a real exercise event, a coach conversation or incremental data access.
Sanitized evidence is saved privately in `ha-wake-test-ping-acceptance.json`.

`examples/shell/ftms_wake_test_ping.py` is the credential-free source of the
installed scoped probe. `shell_command.ftms_wake_test_ping` reuses its saved ID;
`shell_command.ftms_wake_test_ping_new` explicitly creates a new test ID. The ID
is fsynced before sending, and sanitized attempt receipts are kept privately.
Both actions select `test_ping` only. Neither can send a ride notification.

The adapter implements basilisk-dev's published HMAC contract from NEXUS #62:
sign `timestamp + "." + exact_body_bytes` using HMAC-SHA256 and send
`X-Wake-Signature: t=TIMESTAMP,v1=HEX`. The signing time is the current send time;
the original observation time stays in the event data. Retrying must reuse the
event identity, with a fresh signature. No secret is sent in the URL or body.

`activity_envelope` accepts an activity-start/resume event and selects the fixed
`ride_started` task for source `home-assistant`. It forwards only the stable
event ID, diagnostic entity pointer and observation timestamp. Session/config
entry IDs, HR and other metrics are not forwarded. Its caller must supply an
actual durable `ftms_activity` event; shape validation cannot prove an exercise
occurred. `ping_envelope` always selects `test_ping`, so synthetic transport
acceptance cannot accidentally notify the user about a nonexistent ride.

`post_once` performs one bounded blocking request and refuses redirects. It must
run in HA's executor when integrated. Results distinguish `http_accepted` from
`processing_acknowledged`; the latter deliberately remains false until a
correlated receiver acknowledgement contract is agreed and implemented. Even a
response containing the word `processed` cannot establish that this event was
handled by the coach. Arbitrary response/exception text is not returned.

`wake_outbox.py` adds a prepared single-writer queue with its journal cursor and
thin pending envelopes committed in one atomic snapshot. It requires an explicit
activation timestamp, skips earlier events, preserves pending IDs across process
restart, and leaves the old checkpoint intact when an atomic replacement fails.
Late events expire after one hour with a durable count/receipt, matching the
receiver's documented replay window. Changed source identity, corrupt state,
unexpected envelope fields and capacity exhaustion fail without an automatic
reset. Recent terminal receipts are bounded to 512, pending events to 256 and
state size to 2 MiB. The original journal retains source evidence.

The queue must be owned by one serialized worker/instance per state file.
`confirm_processed` is an internal hook for a future authenticated,
event-correlated receipt; it is not an HTTP success callback or an enabled HA
action. No integration currently invokes it. Files are fsynced before atomic
replacement, with parent-directory fsync on POSIX; tests exercised actual local
Windows file I/O, not Pi power-loss durability.

## Remaining integration and live acceptance

1. Synthetic acceptance has passed: HA-originated acceptance/wake, matching
   processing marker and replay deduplication; wrong-auth rejection was verified
   from the developer PC. The supplied endpoint is HTTP on the private LAN; no
   TLS support has been established. Keep the dedicated credential private.
   Confirm the real-ride consumer/data contract before enabling that publisher.
2. Wire the prepared queue into one serialized HA worker and validate its
   persistence on the Pi. The adapter alone does not perform delivery retries.
   Internal MQTT may carry thin events with QoS 1 and no retained one-shot
   messages; broker acknowledgement alone is not an external processing receipt.
3. Wire sending outside HA's event loop with bounded retries and the same event
   ID. Keep recording independent of transport failures. Display delivery state
   separately from recording readiness and coaching activity.
4. Verify `test_ping` acceptance, replay deduplication, credential rejection and
   an event-ID-correlated processing receipt. Do not use `ride_started` for these
   synthetic checks. The adapter's tests mock responses and prove no live route.
5. Prove Basil can pull the required incremental raw observations privately.
   The offline diagnostic entity solves status access, not cursor-page access.
6. Observe a real ride with the chest strap, then verify onset persistence,
   private delivery/receipt, source freshness and user-confirmable coach behavior.
   Agree control limits and test bounded controls separately before enabling
   automatic intensity adjustments.

Recording/storage faults suppress local activity publication in dev5; a wake
publisher must not bypass that rule by inferring a ride from plug power, restored
entities or old session summaries. The existing public NEXUS thread remains an
engineering channel, not an exercise-data transport.


## Manually scoped real-event acceptance

`examples/shell/ftms_wake_acceptance.py` is a one-shot acceptance helper, not a
production worker. It requires an explicit private request containing one event
identity, a journal path constrained to the FTMS storage directory, and an expiry
of at most ten minutes. It refuses incomplete journal tails, nonmatching/latest
events, old or future events, and events without a preceding positive-cadence
sample at the same timestamp. It reads the administrator-provided private source
profile and sends only the existing thin activity envelope. Receipts exclude
credentials and arbitrary response text. Remove the request after use; there is
no bus subscription, timer or recurring retry.

Receiver acceptance, receiver processing and an administrator-visible coaching
response are three separate claims. A processed health marker cannot establish
notification delivery. Keep private test evidence outside source control.


## Receiver delivery gap and follow-up

NEXUS #97 identified that the prior wake handler completed an agent turn but
did not proactively send its response to the administrator. `contact=interactive`
grants a temporary inbound reply-owner lease; it does not deliver outbound text.
Consequently `woke=true` and a matching processed health marker cannot establish
coach notification. #98 requests opt-in outbound delivery, independent stage
receipts, same-ID delivery deduplication and sanitized failure/suppression
reporting. Synthetic delivery acceptance must use test_ping and an isolated
destination. Keep the production HA publisher disabled pending that contract.

NEXUS #106 reports the deployed follow-up: opt-in deliver=true, completed/failed/
suppressed turn status, delivered/failed/no_reply/skipped delivery status,
sanitized error categories and counters. Completed turns are durable across
delivery retries; replay cannot resend a successful delivery. The health endpoint
exposes these fields, but isolated end-to-end outbound acceptance is pending.
The exact event_ref algorithm and a per-event or recent-receipts read contract
are requested in #107; last-result heads alone can be overwritten before a
producer polls. Keep the HA publisher disabled until correlation and delivery
acceptance are verified.


## Production publisher dev6 (2026-10-19)

The receiver contract in NEXUS #108 provides GET /wake/status?event_id=...
with the dedicated source Bearer credential. event_ref is the first 12 lowercase
hex characters of SHA-256 of the exact UTF-8 event identity. The sender validates
source/task/correlation and consistent turn/delivery terminal states, and drops
all arbitrary response fields.

wake_runtime.py loads an explicit private opt-in configuration and an existing
queue with the same activation boundary. It owns one serialized worker, runs
network/disk work in the HA executor, reacts to durable ftms_activity and polls
every 15 seconds for restart catch-up and receipts even when the bike entry is
unloaded. No old exercise is replayed on activation. No missing/corrupt queue is
reset automatically. The normal recorder and Bluetooth connection do not wait
for coaching transport.

wake_publisher.py checks receipts before each POST, durably records retry attempts
before sending, keeps the same event ID after ambiguous failure, and only polls
after acceptance. Retries are bounded to eight attempts with exponential backoff
up to 300 seconds; one-hour expiration remains explicit. Delivered, failed,
suppressed, no_reply and skipped are distinct outcomes. Pending turn/delivery is
never reported as delivered. Terminal receipt retirement and the journal cursor
survive process restart. No MQTT or public discussion transports exercise data.

sensor.kettler_coach_delivery and ftms.get_coach_delivery expose bounded sanitized
queue/progress/receipt diagnostics independently of recording readiness. Terminal
failures create a persistent HA notification. ftms.test_coach_wake uses a separate
durable synthetic test_ping identity and cannot manufacture ride_started or
change bike controls; repeated calls first query its correlated receipt.

The deployment copies only publisher modules, the async_setup hook, service
descriptions and manifest dev6. Prepared shared control-owner and offline-download
diagnostics source changes remain undeployed. No intensity policy or automatic
resistance control is enabled.


## Synthetic Telegram demonstration hook

Dev9 adds `ftms.demo_coach_ping` with a separate `demo_ping` identity file. It
sends the receiver-approved payload exactly: fresh `ha-ftms-demo-ping-<uuid>`,
source `home-assistant`, UTC `when`, `data: {"demo": true}`, and
`expect_ack: false`. The service durably stores the envelope and attempt flag
before its one POST, then queries the correlated demo_ping receipt.
`script.basil_demo_ping` polls that receipt for up to 120 seconds and reports
success only for `turn=completed`, `delivery=delivered`, and terminal true.

The user-requested demonstration was actually delivered on 2026-10-19: receiver
HTTP 202 accepted=true/woke=true, receipt event_ref `8e35c86b4bd2`,
completed/delivered/terminal, and the HA script completed its success-notice
branch. basilisk-dev was asked to remove the temporary `demo_ping` allowlist
entry while preserving non-delivering `test_ping`.
