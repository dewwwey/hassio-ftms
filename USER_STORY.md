# Bike coaching workflow agreed in principle, 2026-10-17

The administrator has reprioritized the work. Fast, dependable connection,
timestamped source telemetry, clear feedback and practical coaching take priority
over formal session boundaries or a console Finish procedure. This file contains
requirements and proposals, not a claim that the full workflow is implemented.

## Starting and riding

Independent wake-by-pedalling is desirable. An explicit smart button or HA Start
ride action that power-cycles the bike before riding is also acceptable if quick
and reliable. Prefer an idempotent preflight: if telemetry is already connected,
fresh and being persisted, show Ready without resetting the bike. Otherwise an
explicit pre-ride start can perform one bounded recovery sequence. Avoid an
unattended power-cycle loop or an unexpected reset during exercise. The exact
readiness deadline and failure-feedback channel still need agreement and testing.

Ready must mean a recent real bike measurement and a healthy recording path, not
merely an enabled integration, Bluetooth icon, energized smart plug or existing
entity. Show Connecting, Ready/Recording, and a clear actionable failure. Do not
silently claim recording when the bike is absent or storage is unhealthy.

Record received telemetry with timestamps and distinguish absent/stale fields
from valid zero values. Keep interruption and diagnostic evidence so the coach
can combine fragments later. The administrator does not require preservation of
one session ID across every interruption. Preserve existing source facts and
flags; reconstructed coaching sessions must not invent unreceived measurements.

The administrator can stop pedalling and get off. Explicit Finish is optional,
and its device protocol is no longer a prerequisite for a usable first release.
Keep the existing inactivity summary as a convenience rather than a substitute
for the original measurements. Stop spending acceptance effort on console Finish
while wake/connect and actual data capture remain unreliable.

## Coach response and automatic intensity

Alert Coach Basil promptly on actual exercise onset, with recovery/resumption
events that do not cause duplicate starts. This needs a tested private delivery
path and confirmation that Basil received it. NEXUS discussion 5 is public to
participating agents and is not a channel for exercise events or health data.

The primary HR source is a chest strap connected to the bike. Verify that live
strap readings reach HA with timestamps; the existing HR field has so far only
shown unavailable/placeholder values. A watch can be supplementary if its actual
data route and latency are established. Do not assume continuous watch HR/SpO2
access, silently switch sources, or substitute a missing value with zero.

The administrator wants automatic intensity adjustment within agreed limits.
The current deployment still blocks general device controls; this is a new
implementation requirement, not an already functioning capability. Read the
advertised ranges and test acknowledged writes with the real bike before relying
on them. Capability flags and prior upstream behavior alone are insufficient.

Basil owns the exercise strategy, intended targets, and control algorithm. The
coach may implement HA automations, PID control or another local controller;
live coaching does not require a separate model tool call for every adjustment.
This task prepares the technical prerequisites and tested control primitives,
not the coach's training strategy or PID tuning. Agree and validate control
mode (resistance or target power), starting load, absolute bounds, change rate,
HR source/freshness, missing-HR and disconnect behavior, and a readily available
manual override. Do not invent HR targets or enable unbounded agent writes.
Transport recovery must not silently reapply an old exercise target on reconnect.

## Logging and plug measurements

Keep useful bounded connection/retry/failure diagnostics and durable telemetry.
Avoid leaving verbose logs of every personal measurement enabled indefinitely.
Expose last-seen and recording/storage health even while the integration is
offline, so users and the coach can tell failure from an idle bike.

Smart Plug 5 now provides voltage, current and input-power measurements. Compare
standby, awake idle and exercise against bike telemetry with matching timestamps
before using these as diagnostic hints. Supply voltage is not exercise evidence;
electrical input watts are not the rider's mechanical watts. Do not infer activity
or choose training intensity from an unvalidated plug-power threshold.

## Acceptance priorities

1. Repeated standby wake and explicit pre-ride recovery, with a measured deadline
   and unambiguous Ready/failure feedback. Three successful cold power cycles
   already exist; standby wake remains a reproduced failure case.
2. Persist live measurements and provide Basil a private incremental read path,
   including fragments, source timestamps, gaps and storage health. Completed
   summaries alone do not meet the revised requirement.
3. Prove private start-event delivery and acknowledgement. Failed delivery must
   not stop recording or falsely imply that coaching is active.
4. Validate chest-strap HR end to end, then test bounded device control with user
   override and stale-data/disconnection behavior. Enable the agreed policy only
   after these checks and limits are concrete.

Open design inputs: physical start button and feedback channel; readiness deadline;
Basil's private event/data transport; exact intensity policy and override behavior.
