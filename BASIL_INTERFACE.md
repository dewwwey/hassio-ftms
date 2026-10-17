# Private Home Assistant FTMS interface, schema 2

The revised desired workflow is specified in [USER_STORY.md](USER_STORY.md):
reliable pre-ride connection, durable source telemetry, private coaching events,
and eventually bounded automatic intensity control. Explicit Finish is optional.
The current implementation described below does not yet provide all those features.

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
`telemetry_observed=true`, `automatic_control=false`, and
`control_scope=["finish_workout"]`. Consumers must not use read_only alone as a
data-quality gate. Samples remain observed facts, and quality/intent/storage
requirements still apply. No resistance, target-power, reset or start command is
exposed. No agent is required to end a workout or manage the connection.

All values stay in HA and its private configuration share. This document contains
no health observations. Posting any resulting health data to NEXUS or another
recipient requires the administrator's package-specific approval. NEXUS thread 5
is an engineering discussion, not a telemetry transport.

## Current state

The integration creates a `Telemetry status` sensor. Discover its entity ID via
the HA entity registry for platform `ftms`; never assume a particular generated
slug. Its state is `disconnected`, `stale`, `idle`, `riding`, or `paused`.
HA unloads entities during config-entry retry; in that case state is
`unavailable` and consumers must not interpret restored attributes as live data.

Attributes:

| Attribute | Meaning |
| --- | --- |
| schema_version | 2 |
| last_received_ts | UTC Unix seconds of last actual realtime frame, or null |
| observed_metrics | Names observed on this connection; not capability guarantees |
| current_session | Active/pending session object, or null |
| last_session | Most recent finalized observation, or null |
| completed_count | Number of finalized records, including partial records |
| storage_error | null on healthy storage; error/recovery indicator otherwise |
| read_only | false: explicit Finish is available |
| telemetry_observed | true: values come from received measurements |
| automatic_control | false |
| control_scope | finish_workout only |

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
After entry unload/setup retry, restored entities can expose only `restored=true`.
Persistent offline last-seen metadata is not implemented; restored attributes
must not be read as current observations.

Current implementation replays the full journal when loading/exporting. Automatic
retention, compaction, multi-user attribution, clock-jump reconciliation and
durable human intent confirmation are not implemented. A crash can lose queued
records not yet fsynced; restart quality flags keep those sessions under review.
No exactly-once monetary claim is made. The consumer's ledger must enforce it.
