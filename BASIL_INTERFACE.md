# Private Home Assistant FTMS interface, schema 1

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
| schema_version | 1 |
| last_received_ts | UTC Unix seconds of last actual realtime frame, or null |
| observed_metrics | Names observed on this connection; not capability guarantees |
| current_session | Active/pending session object, or null |
| last_session | Most recent finalized observation, or null |
| completed_count | Number of finalized records, including partial records |
| storage_error | null on healthy storage; error/recovery indicator otherwise |
| read_only | true |

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

Response: `schema_version`, `read_only`, `storage_error`, `total`, chronological
`sessions`, `has_more`.
Increment offset by the number returned while `has_more`. Consumers must upsert
by `session_id`; never pay rewards merely because an entry appears in a response.
No agent credentials or new external HA client are provisioned by this patch.

Session fields include stable `session_id`, source, `start_ts`, `end_ts`,
`active_seconds`, `total_seconds`, observed `distance_m` delta or null, sample
count, `flags`, `quality`, `duration_qualifies`, `intent_confirmed`, and reward
review status. UTC times are Unix seconds. Distance is an observed lower bound
if samples are missing. No missing interval is interpolated.

The ID hashes the persisted source and first activity timestamp. Replaying the
same journal yields the same IDs and summaries. A new config entry is a new
source; migrations must preserve source identity and journal together.

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
- `duration_qualifies` uses observed active_seconds >=600. A clean record has a
  deterministic proposed amount of 200 cents, plus 100 at >=1200 seconds.
  Partial records propose zero and require quality review. Every record starts
  with `intent_confirmed=false`. This patch never credits money or writes Basil's
  reward ledger. Intent confirmation and the authoritative reward ledger remain
  separate deterministic operations.

## Persistence and limits

Journal: `/config/.storage/ftms/CONFIG_ENTRY_ID.jsonl`. Only initial idle evidence
and workout/pause samples are retained; ordinary idle frames are not continuously
logged. UTC timestamps and original available fields support private time-series
inspection. The in-memory active record is recovered by replay after restart.
An incomplete final write is preserved in `.truncated` before recovery. Interior
corruption fails closed and leaves the file intact. Back up journals privately.

Current implementation replays the full journal when loading/exporting. Automatic
retention, compaction, multi-user attribution, clock-jump reconciliation and
durable human intent confirmation are not implemented. A crash can lose queued
records not yet fsynced; restart quality flags keep those sessions under review.
No exactly-once monetary claim is made. The consumer's ledger must enforce it.
