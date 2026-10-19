# Private Home Assistant FTMS interface, schema 2

The revised desired workflow is specified in [USER_STORY.md](USER_STORY.md):
reliable pre-ride connection, durable source telemetry, private coaching events,
and eventually bounded automatic intensity control. Explicit Finish is optional.
The current implementation described below does not yet provide all those features.

Version `0.24.9.dev10` exposes manual HA number controls for the device-advertised
`target_resistance` and `target_power` settings. They are available only while
FTMS is connected and telemetry is fresh, and update after a successful bike
acknowledgement. Their limits come from the bike, not a training policy. No
target is replayed after reconnect; `automatic_control` remains false.

Leave FTMS enabled. The optional **Finish workout** action sends the FTMS Stop procedure and
waits for a positive bike acknowledgement. It does not disable the integration or
disconnect deliberately. Inactivity remains a logical-record fallback; it does
not silently send a device-control command. Bike sleep/power-off is ordinary
unavailability, with automatic reconnection expected on wake-up.

Acceptance warning for this development version: Request Control succeeds on the
idle real bike, but Stop has timed out. Post-ride Finish and its console effect
remain unverified and are no longer a first-release prerequisite. Ordinary
standby wake has also failed to reconnect and is the higher-priority defect.

Schema 2 replaces the old integration-wide `read_only=true` claim: an explicitly
invoked Finish action is now available, so `read_only=false`,
`telemetry_observed=true`, and `automatic_control=false`; `control_scope` lists
Finish plus live target settings when the bike advertises them. Consumers must not use read_only alone as a
data-quality gate. Samples remain observed facts, and quality/intent/storage
requirements still apply. The manual number entities expose advertised resistance
and power targets; reset and start commands are not exposed. No agent is required
to end a workout or manage the connection.

All values stay in HA and its private configuration share. This document contains
no health observations. Posting any resulting health data to NEXUS or another
recipient requires the administrator's package-specific approval. NEXUS thread 5
is an engineering discussion, not a telemetry transport.

## Consumer verification, 2026-10-19

Coach Basil confirmed his own read-only diagnostics and Recorder-history access
in NEXUS #92. `observed_metrics_scope` holds the string `journal_history` when
replayed offline; `journal_history` is not a separate entity attribute. Recorder
history is suitable for coaching inspection with explicit gaps and pagination,
but is not an exact raw-journal export and unchanged sensor states need not
represent each received notification.

A current session has `last_sample` and `last_activity`, but has no final
`end_ts` or `quality`. An onset consumer must accept this provisional schema.
Finalized history windows end at `end_ts` without an extra sixty seconds;
`last_persisted_ts` may reflect later metadata and is not a session boundary.
The prepared wake carries `event_id`, `status_entity` and `observed_at`, not a
session pointer. Correlate the diagnostic event identity and session identity;
never fall back to an unrelated latest ride after a delayed wake. Final reports
must wait for a matching finalized session. HR source validation and production
ride-wake acceptance remain pending. Engineering clarification is in #93.

## Current state

Version `0.24.9.dev10` is installed in HA. The pre-ride recovery script power-
cycled Smart Plug 5, reloaded the entry and restored fresh idle telemetry. HA
created `number.living_room_kettler_ftms_target_resistance` (1–20, step 1) and
`number.living_room_kettler_ftms_target_power` (25–1000 W, step 1), as advertised
by the bike. Both target values remain unknown until HA sends a target and the
bike acknowledges it. No target was sent during deployment validation.
`automatic_control=false`; no policy range, controller or HR-driven adjustment
was enabled. The offline status fields were also verified through the
independently loaded diagnostic entity while FTMS was unloaded. Offline
`last_persisted_ts`
recovery and the 30-second resume debounce are included in this version.
`script.ftms_start_ride` was reloaded and exercised on 2026-10-18: one bounded
plug cycle plus explicit config-entry reload recovered an idle connection with
`connected`, `fresh` and `recording_ready` true, no storage error, and an
advancing persisted timestamp. It created no activity event or workout. This
verifies that recovery attempt and idle persistence, not ordinary standby wake,
exercise capture in the new deployment, coaching delivery or post-ride Finish.

The integration creates a `Telemetry status` sensor. Discover its entity ID via
the HA entity registry for platform `ftms`; never assume a particular generated
slug. Its state is `disconnected`, `stale`, `idle`, `riding`, or `paused`.
HA unloads entities during config-entry retry; in that case state is
`unavailable` and consumers must not interpret restored attributes as live data.

The HA actions `ftms.get_status` and `ftms.get_observations` provide the private
incremental interface. They require a response-capable service caller. Discover
the entry ID locally; do not copy it into NEXUS. `get_status` waits for queued
journal writes before reporting health. When the entry is unloaded it reads the
append-only journal to recover last-seen, last-persisted, last-activity and latest
event metadata, while `connected`, `fresh`, and `recording_ready` stay false.

The local HA configuration also provides `sensor.kettler_ftms_diagnostics`, a
trigger-based template sensor outside the FTMS entry lifecycle. It calls
`ftms.get_status` every ten seconds and exposes status, storage health, historical
timestamps and `latest_event` through ordinary entity reads. Version 0.24.9.dev4
also adds replayed `current_session`, `last_session`, `completed_count` and
`observed_metrics` to that status response. Historical observed metric names
carry `observed_metrics_scope=journal_history`; a loaded coordinator reports
`connection` scope. Names are historical evidence, never current freshness or
capability guarantees. Offline replay does not invent session completion, reset
intent confirmation or manufacture an onset event for older journal data.
The original diagnostic fields were verified
live while the FTMS entity was unavailable: it returned `disconnected`, false
readiness and the journal's retained timestamps. `checked_at` is the status
check time, not a sample time. Accept a snapshot only when
`0 <= now - checked_at <= 25` seconds and it is not restored; otherwise treat
diagnostics as stale regardless of its state/readiness attributes. An action
failure produces `diagnostic_error` with false readiness, rather than retaining
a previous Ready result. This sensor has up to ten seconds of polling latency
and does not carry raw sample pages or prove private coaching delivery.

The independent diagnostic entity was also verified through the existing
read-classified management route, using `ha_call_read_tool` with
`name="ha_eval_template"`, `arguments={"template": TEMPLATE, "strict": true}`.
`examples/read_offline_status.jinja` is the exact supported-function probe: it
returned a fresh diagnostic check, disconnected/false readiness and retained
session/count presence while FTMS was unloaded. No permission change or generic
write-classified action call was needed. Coach Basil confirmed this read route from his own client in NEXUS #92. It does
not make raw cursor pages readable through that route.

A reusable configuration is in `examples/ftms_diagnostics.yaml`. Replace its
entry-ID placeholder locally and include the file as an item in HA's `template`
list (`- !include ftms_diagnostics.yaml`). Validate configuration and reload
Template entities. This example contains no credentials or source identifiers.

Private journals replay summaries, counts and durable onset events through the
diagnostic sensor after Core restart. A journal predating durable onset events
correctly has `latest_event=null`; never manufacture an event from an old summary
to make that field non-null. Live acceptance evidence is retained privately.

Example status call:

```yaml
action: ftms.get_status
data:
  config_entry_id: SELECT_THE_FTMS_ENTRY
response_variable: bike
```

To page raw observations, pass the previous `next_cursor` on the next call and
continue until `has_more` is false:

```yaml
action: ftms.get_observations
data:
  config_entry_id: SELECT_THE_FTMS_ENTRY
  limit: 100
response_variable: page
```

Each returned journal record has its original UTC Unix-second `ts`; source
measurements remain the exact available FTMS fields. The response includes units,
storage health, a stable record ID and a cursor that fails closed on journal
replacement, truncation or corruption. `hr_validation` is `unvalidated` until
the bike's strap data path is proven end to end.

The coordinator fires the local `ftms_activity` event only after both its
triggering sample and event are fsynced. `activity_started` is emitted on first
positive cadence. Version 0.24.9.dev2 adds a 30-second observed
idle/disconnect requirement for `activity_resumed`, suppressing duplicate
notifications from brief coasting once that version is loaded. Event IDs are
stable in the journal. This local event is not proof that Coach Basil received
a wake.
Version 0.24.9.dev5 fixes a fault-injection regression where a failed onset
sample write could be followed by a successful event write and notification.
Once recording reports a storage or queue fault, an activity event is replaced
with an `activity_event_suppressed` journal marker (`unhealthy_recording`) and
is neither exposed as `latest_event` nor fired on HA's bus. Later received
measurements can still be saved, but the sticky storage fault remains visible.
The normal durable event path and existing event IDs are unchanged. Synthetic
tests verify this behavior without inducing a fault on HA's real storage.
The HA MQTT broker was unreachable from Basilisk in the last connectivity test,
so no FTMS MQTT publisher or external wake path is enabled. Basilisk has since
reported a tested authenticated webhook and MQTT wake receiver (NEXUS #63), but
the administrator has now supplied a dedicated private Bearer profile. A scoped
HA-originated `test_ping` after cooldown returned `woke=true`, reached a matching
processed health marker and replayed as a duplicate without another wake.
Wrong-auth rejection was verified from the developer PC. No production ride publisher
is enabled. Basil confirmed read-only Recorder-history access in #92 and accepted
the corrected provisional/final session contract in #95. This is a coaching read
route, not an exact raw-journal export. NEXUS
carries engineering updates only.

Attributes:

| Attribute | Meaning |
| --- | --- |
| schema_version | 2 |
| last_received_ts | UTC Unix seconds of last actual realtime frame, or null |
| last_persisted_ts | UTC Unix seconds of the most recent fsynced journal record |
| last_activity_ts | UTC Unix seconds of the last positive-cadence observation |
| latest_event | Latest durable `activity_started` or `activity_resumed`, or null |
| observed_metrics | Names observed on this connection; not capability guarantees |
| current_session | Active/pending session object, or null |
| last_session | Most recent finalized observation, or null |
| completed_count | Number of finalized records, including partial records |
| storage_error | null on healthy storage; error/recovery indicator otherwise |
| read_only | false: explicit Finish is available |
| telemetry_observed | true: values come from received measurements |
| automatic_control | false |
| control_scope | `finish_workout`; live advertised target settings while connected |

Metric sensor attributes include `source=ftms_notification` and
`last_received_ts`. Each metric is unavailable before observation, after ten
seconds without its own field, or while disconnected. An advertised feature can
have a sensor that stays unavailable if the bike never sends that metric.
Heart rate is not useful evidence without a validated actual source; do not infer
a pulse from zero or from a feature bit. Names/units come from upstream FTMS
definitions: speed km/h, cadence rpm, power W, distance m, elapsed time s.

## Completed sessions

Call HA action `ftms.get_sessions` with a response:

```yaml
action: ftms.get_sessions
data:
  config_entry_id: SELECT_THE_FTMS_ENTRY
  offset: 0
  limit: 50
response_variable: rides
```

Through the current MCP server, use `ha_call_write_tool(name="ha_call_service",
arguments={"domain":"ftms", "service":"get_sessions", "data":{
"config_entry_id":FTMS_CONFIG_ENTRY_ID}, "return_response":true})`.
This HA action only reads data; MCP categorizes its generic service caller as a
write tool. A client restricted to read tools needs a dedicated MCP wrapper from
the MCP maintainer. `ftms.get_sessions` is not itself an MCP tool name.

Response: `schema_version`, `read_only`, `telemetry_observed`, `automatic_control`,
`control_scope`, `storage_error`, `total`, chronological
`sessions`, `has_more`.
Increment offset by the number returned while `has_more`. Consumers must upsert
by `session_id`; never pay rewards merely because an entry appears in a response.
No agent credentials or new external HA client are provisioned by this patch.

Session fields include stable `session_id`, source, `start_ts`, `end_ts`,
`active_seconds`, `total_seconds`, observed `distance_m` delta or null, sample
count, `flags`, `quality`, and `intent_confirmed`. UTC times are Unix seconds.
Distance is an observed lower bound
if samples are missing. No missing interval is interpolated.

The ID hashes the persisted source and first activity timestamp. Replaying the
same journal yields the same IDs and summaries. A new config entry is a new
source; migrations must preserve source identity and journal together.

The schema-2 replay adds a `finish_reason` field; source samples and stable IDs are
preserved. Summary schema metadata can change across software versions, while
repeated exports on one version remain identical.

## Finish action

Use the device's Finish workout button, or `ftms.finish_workout` with
`config_entry_id`. Only a connected device is accepted. The procedure subscribes
to control-point indications, sends Request Control (00), requires success, then
sends Stop (08 01) and requires success. It times out or reports rejection rather
than claiming success. It never uses disconnection as a finish mechanism.

A received machine-stop notification or acknowledged Finish finalizes the current
observation immediately. A stopped/paused ride ends at its first observed idle
sample; no unseen time is credited. Duplicate finish events cannot duplicate the
session. After finishing while moving, an idle sample is required before another
ride can begin. General library control methods remain blocked.

## Session and reward semantics

- Positive observed instantaneous cadence starts/resumes activity. Connection,
  power and speed alone cannot start a ride.
- Active duration credits only adjacent positive-cadence observations at most
  ten seconds apart. Pauses and unknown gaps receive no time credit.
- Two minutes of explicitly observed inactivity finalize at the first inactive
  timestamp. Disconnect alone does not finalize a successful workout.
- Thirty minutes without samples finalize a partial record at last activity.
- Counter resets split records; mid-ride attachment, reconnect/restart, malformed
  packets, missing cadence, clock regression and missing samples are flagged.
- `quality=complete` means complete under these observation rules, not proof of
  intentional training or medical accuracy.
- Every record starts with `intent_confirmed=false`. The interface sends no
  amounts or reward-eligibility verdicts. Intent confirmation, thresholds, payment
  and deduplication belong exclusively to the separate deterministic ledger.
  The requested policy is >=600 active seconds for EUR 2, plus EUR 1 at >=1200,
  with complete quality, no flags/storage errors, and user confirmation required.
  Compare seconds directly; never round to minutes before evaluating eligibility.
  Use `session_id` for deduplication, never timestamp display strings.

## Persistence and limits

Journal: `/config/.storage/ftms/CONFIG_ENTRY_ID.jsonl`. Only initial idle evidence
and workout/pause samples are retained; ordinary idle frames are not continuously
logged. UTC timestamps and original available fields support private time-series
inspection. The in-memory active record is recovered by replay after restart.
An incomplete final write is preserved in `.truncated` before recovery. Interior
corruption fails closed and leaves the file intact. Back up journals privately.

While the coordinator is loaded, disconnect retains last-received metadata.
After entry unload/setup retry, the status action recovers historical timestamps
from the journal, but `recording_ready` remains false and restored entity
attributes must not be read as current observations.

Current implementation replays the full journal when loading/exporting. Automatic
retention, compaction, multi-user attribution, clock-jump reconciliation and
durable human intent confirmation are not implemented. A crash can lose queued
records not yet fsynced; restart quality flags keep those sessions under review.
No exactly-once monetary claim is made. The consumer's ledger must enforce it.
