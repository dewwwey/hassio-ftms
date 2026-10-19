# Engineering checkpoint: scoped Finish and reconnect repair

No personal observations, identifiers, credentials or raw logs are included.

## Consumer contract checkpoint, 2026-10-19

Coach Basil confirmed his own read-only diagnostics and Recorder-history access
in NEXUS #92 and accepted the corrected contract in #95. Current sessions are
provisional through last_sample; finalized history ends at end_ts. Match event
and session identities and keep Recorder gaps/pagination explicit. See
BASIL_INTERFACE.md. Coach Basil
identified the delivery gap in #97: the wake handler completes the turn but does
not proactively deliver its response; interactive contact grants an inbound lease
only. #98 requests separate delivered/failed/suppressed receipts and opt-in
outbound delivery. No production publisher or intensity writer is enabled.

A manually requested, expiring real-event sender is prepared in
examples/shell/ftms_wake_acceptance.py. It is separate from the synthetic
test_ping helper and has no recurring listener or worker. Private test evidence
is retained outside source control. The local suite now contains 93 passing
tests. Two tests cover recent-event/sample correlation and rejection of missing
samples, stale identities and old/future timestamps. Nine more cover the shared
control-point owner prepared in source: serialization, live authorization after
queueing and after Request Control, acknowledgement rejection/timeouts,
cancellation (including interrupted subscription setup), disconnect and Finish
session-guard checks. These protocol-owner
changes are not deployed; HA continues running the prior dev5 control code. See
CONTROL_PREREQUISITES.md for the remaining policy/controller requirements.

## Historical checkpoint, 2026-10-18

Version 0.24.9.dev5 is loaded after a Core restart. A prior live invocation of the
loaded `script.ftms_start_ride` recovered connected, fresh, recording-ready idle
telemetry with healthy storage and an advancing persisted timestamp. No activity
event or workout was created. Ordinary standby wake and exercised capture in
this deployment remain unverified. The older findings below are historical
context, not the current deployment version or a broader acceptance claim.

The full local source suite passes: 79 tests using the project Python environment
(run from `ftms-investigation/hassio-ftms` with a Linux venv:
`python -m unittest discover -s tests -v`).
Coverage includes packet decoding, session replay, reconnect timers, original
observation paging, idle heartbeat persistence, activity event durability and
resume debounce. These synthetic checks do not establish bike reliability,
chest-strap HR, live intensity control or private coaching delivery.
The extra eleven sender tests cover HMAC/Bearer wake request preparation,
described in `WAKE_TRANSPORT.md`. The adapter is deployed for scoped test-ping
actions only, without a production publisher. It distinguishes
HTTP acceptance from a correlated processing acknowledgement, refuses redirects
and uses a separate test-ping builder. Endpoint/response details are requested
in NEXUS #76. The administrator has now supplied a dedicated private Bearer
profile. PC-side acceptance/dedup/auth rejection and HA-side acceptance/dedup
passed. HA's first ping was suppressed by the test-task cooldown, so a matching
processed marker alone must not be claimed as an actual new agent wake.
After cooldown, a fresh HA-only test ID returned `accepted=true`, `woke=true`;
health matched that exact processed ID and pending returned to zero. Same-ID
replay returned duplicate with no second wake. This proves the scoped synthetic
HA route; no `ride_started` event was sent and no coaching/HR claim follows.
Eight further tests cover the prepared durable queue: restart, failed atomic
checkpoint, deduplication, explicit activation boundary, expiry, capacity,
source/corruption checks and strict thin-envelope recovery. No HA queue worker
or publisher is enabled; Pi-side persistence and delivery remain unverified.
Seven further tests cover a pure intensity-target validation/encoding helper.
It requires supplied device and policy ranges, uses exact arithmetic, and rejects
off-step, out-of-policy, nonfinite or unrepresentable targets. This helper performs
no I/O and is not deployed. `CONTROL_PREREQUISITES.md` lists the policy, telemetry,
HR, protocol acknowledgement and supervised acceptance gates before any write
action can be enabled. No exercise limits were chosen from test fixtures.

Private incremental reads exist as HA response-capable actions, but Basil's
read-classified management surface has not yet been shown to support them.
The separate local `sensor.kettler_ftms_diagnostics` is now loaded and verified
while the FTMS status entity is unavailable. It polls the status action every
ten seconds; consumers must reject restored data and `checked_at` ages outside
0–25 seconds. This makes offline metadata available through ordinary entity
reads without granting a new caller permission. It does not provide raw pages.
Dev4 additionally recovers current/last session, completed count and observed
metric names from the journal. These fields and a fresh post-restart check time
were verified live while the bike remained disconnected. Historical metric
names are explicitly scoped to `journal_history`; they are not fresh values.
The existing journal has no durable onset event, so `latest_event` remains null.
An additional dev4 pre-ride recovery produced its first persisted idle sample
17.45 seconds after invocation and displayed Bike ready. A second invocation
while ready completed immediately with the already-ready message; the smart
plug's last-change timestamp remained unchanged. No onset event was generated.
This verifies idle recovery and idempotency, not ordinary standby wake, active
ride refusal, failure feedback or a real coaching wake.
Dev5 fixes a reproduced disk-failure edge case: if the onset sample write fails,
the subsequent activity event is suppressed while the recorder has a sticky
fault. A durable `activity_event_suppressed` marker replaces it, without firing
HA's activity bus or advancing `latest_event`. The regression first failed on
dev4 and passes with the fix. Real HA storage was not faulted. Post-restart
diagnostics resumed with a fresh check timestamp, correct offline readiness and
retained summary metadata; no synthetic ride was created.
Basilisk reports an authenticated webhook/MQTT wake receiver; no HA publisher,
private credential handoff or end-to-end delivery has been verified. Keep these
as open acceptance items rather than claiming that local durable events wake
the coach. NEXUS posting identity is `homeassistant-dev`, via the regular local
API and the workspace's gitignored profile, as specified in `AGENTS.md`.

Real-device acceptance now covers a clean observed recording, deterministic
summary replay, and an interrupted recording that preserves identity and flags
the unknown gap. No reward ledger was changed. Complete quality is an observation
property; intent remains unconfirmed.

A subsequent recovery failure is reproduced and remains under investigation.
A controlled power-loss test exposed an unmarked synchronous reconnect timer:
HA dispatched it to an executor, then rejected its event-loop-only reload call.
Version 0.24.8.dev2 marks that timer as a HA callback and checks shutdown state.
It passes 38 local tests, including this regression. Repeated live recovery is
still required; a single successful power cycle is insufficient acceptance.
Separate host diagnostics identify a missing Broadcom firmware patch. That is
not proof that firmware caused the observed failure. Independent
discovery on a Windows PC saw the bike when HA did not.

The administrator requested a usable Finish procedure while leaving FTMS enabled.
Schema 2 therefore declares `read_only=false`, `telemetry_observed=true`,
`automatic_control=false`, and `control_scope=["finish_workout"]`. The only
application writes are explicit Request Control (00) then Stop (08 01), each
requiring a matching successful indication. No automatic start/stop, resistance,
power target or reset. Request Control succeeds on the real idle device; Stop
times out in that idle state. A post-ride Finish remains unverified. Do not infer
device completion from a button's existence or from disconnection.

Consumers must use observed telemetry, quality, flags, storage health and intent
gates, rather than rejecting or approving evidence from `read_only` alone.
Stable ID derivation is unchanged. Replay adds schema metadata and finish reason;
source facts and IDs remain stable. No monetary or eligibility fields return.

## Reply to REQUEST-HA-SESSIONS-01

`ftms.get_sessions` is an HA action, not an MCP tool name. Its exact route through
the current management server is:

```python
ha_call_write_tool(name="ha_call_service", arguments={
    "domain": "ftms", "service": "get_sessions",
    "data": {"config_entry_id": FTMS_CONFIG_ENTRY_ID, "offset": 0, "limit": 50},
    "return_response": True,
})
```

Discover the entry with `ha_get_integration(domain="ftms")`. The action itself
only reads completed recordings. The MCP server categorizes all `ha_call_service`
calls as write tools and rejects its read proxy; that classification does not
make this action write a ledger. A client limited to MCP read tools needs the MCP
maintainer to add a dedicated wrapper. Do not expand permissions merely to work
around the category. This patch does not register MCP tools.

## Offline status and resets

`last_received_ts` is retained while the loaded coordinator is disconnected.
If HA unloads the entry or starts while the bike is absent, restored entities may
have only `restored=true`; persisted offline last-seen metadata is still open.
Never treat those restored attributes as current observations. Current metric
expiry and config-entry unload/reload can both cause `unavailable`; sensor
history alone does not distinguish their cause.

A real cumulative time/distance regression splits the active observation with
`counter_reset`, creating a different ID only on later positive cadence. A zero
at idle without positive cadence never creates a session. Disconnect/restart
alone preserve an active ID and exclude unknown intervals. Use completed-session
facts and flags, rather than reconstructing workouts from elapsed-sensor history.

The pre-existing `bike_gamification` entities and separate ledger changes remain
outside this component. Their presence alone does not prove active ledger writes;
their automations/scripts need a separate audit by the ledger owner.

## Additional source and workflow work

The development diagnostics handler now returns explicit offline metadata for a
missing or closed entry runtime instead of dereferencing None. It preserves a
known recording fault without claiming freshness and omits measurements. Three
new tests cover missing/unloaded/closed and loaded runtime paths. This handler
change, like the shared control owner, is not deployed. The full source suite
passes 93 tests.

The loaded Start Ride workflow now replaces Connecting with a timestamped Ready
notice, guards status-read failures before any power recovery, and uses a
separate ready notification ID. A native state/startup automation clears only
that ready notice when either FTMS status loses readiness or availability. Failure
notices remain. The updated configuration round-tripped through the HA API; a
live idle run displayed Connecting followed by timestamped Ready. Natural
disconnect dismissal also passed: after idle standby, both readiness became false
and the ready notice disappeared; the cleanup automation has a matching trigger
time. Private proof is retained locally. Source examples are
examples/ftms_start_ride.json and examples/ftms_clear_ready_notice.json.

WATCH_HR.md tracks the additional direct Wear OS HR prerequisite. App connection
and measured background freshness remain unvalidated; no fallback is enabled.

## Receiver follow-up

Basilisk-dev reports #106 deployed opt-in outbound delivery and separate
last_turn/last_delivery states, counters, persisted turn completion and bounded
delivery retries without rerunning a turn. The authenticated health endpoint now
exposes those fields. No new end-to-end isolated destination test is accepted
yet. #107 requests the exact event_ref algorithm plus per-event/recent receipts
so another event cannot overwrite the only correlated result before HA polls.
It also asks the receiver maintainer to coordinate isolated test setup through
the established private administrator mechanism. Production publishing remains
disabled.

An isolated status-read failure probe also passed against the real HA script
engine: the registered status service rejected a deliberately missing entry,
the same guard used by Start Ride displayed its expected refusal and stopped.
The probe contained no power/device actions; plug change time and journal byte
count stayed unchanged. Its script and notice were removed after verification.
Private proof is stored outside source control. This does not replace real
Bluetooth recovery-failure or disk-fault acceptance.


## 2026-10-19 publisher dev6 deployed

Automatic future ride-start/resume publishing is enabled with a fresh explicit
activation boundary. Runtime dev6 includes only the publisher/outbox/receipt
modules, async_setup hook, service descriptions and manifest change; the prepared
control-owner and offline-download diagnostics changes remain source-only.
106 source tests pass. HA loaded the publisher armed after restart, checkpointed
the existing journal while skipping pre-activation events, and persisted its
queue on the Pi. A fresh HA test_ping was accepted/woke, then the same identity
was queried (no additional POST) with completed/skipped/terminal receipt.
The actual next workout must still confirm automatic onset-to-private coaching
message; no synthetic ride_started or old real event was replayed.

HA sensor.kettler_coach_delivery and ftms.get_coach_delivery separate pending,
accepted turn/delivery progress and terminal outcomes from recording readiness.
The Home View bike section now includes Start Ride, fresh recording status and
Basil coaching status. Errors create persistent HA notices, not Fold push.
Private activation/probe evidence is stored outside source control. NEXUS thread 5
was updated and Coach Basil asked to confirm readiness directly.


## 2026-10-19 Basil demo ping dev7

Added private HA script `script.basil_demo_ping` (Home View card “Demo ping Basil”).
It creates one fresh durable synthetic test_ping identity, waits up to 120 seconds
for a source-authenticated correlated terminal receipt, and creates a success
notification only when delivery=delivered. Other outcomes are reported as not
delivered. The probe service durably records post_attempted before transmission;
repeat polls reuse that identity and never repost an ambiguous request. No ride
record or bike control is created.

HA config validation passed, manifest is 0.24.9.dev7, HA restarted, and runtime
readback confirms the demo script, Home View button, and publisher armed. The demo
was intentionally not run pending receiver-side readiness; test_ping remains
non-delivering by the last receipt.


## 2026-10-19 delivered Basil demo ping dev9

Followed basilisk-dev #119 exactly: dedicated `demo_ping` task, a new
`ha-ftms-demo-ping-<uuid>` event ID, UTC ISO `when`, `data: {"demo": true}`,
and `expect_ack: false`, using the existing source Bearer profile. The previous
demo script incorrectly sent test_ping; it was corrected with a dedicated HA
service and run as requested. The correlated receipt was turn=completed,
delivery=delivered, terminal=true, pending=false; HA trace confirms the success
notification branch. Agent received receipt summary at NEXUS #120 and was asked
to remove the temporary task. Final deployed version is 0.24.9.dev9.
