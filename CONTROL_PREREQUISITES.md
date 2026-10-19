# Intensity controls

HA now exposes manual target controls as `number` entities for each target the
connected bike advertises. The values are bounded by the bike's advertised
minimum, maximum and step; each change is sent through the coordinator's shared
control-point owner and the entity updates only after the bike acknowledges it.
The controls are unavailable while disconnected or while telemetry is stale.
They are not automatically reapplied after reconnect.

`target_resistance` uses FTMS opcode 04 (signed 16-bit tenths) and
`target_power` uses opcode 05 (signed 16-bit whole watts), matching the pinned
vendor `models/control_point.py`. The pure `intensity_target.py` encoder rejects
missing/nonfinite values, off-step values, and protocol overflow. For manual HA
commands the approved input range is the machine-advertised range. This does not
authorize Basil's automatic controller or infer any training policy.

Automatic intensity control remains disabled. Before enabling Basil's controller,
agree bounded exercise limits, fresh and validated HR inputs, explicit arming,
per-change/dwell/rate limits, a known target baseline, manual override, stale-data
and disconnect behavior, and an audit trail. The LLM must remain outside the live
control loop.

## Shared protocol owner

`finish.py` contains `ControlPointOwner`, with one owner instantiated per
coordinator. Finish and target controls share its
transaction lock and one indication subscription. Targets accept only encoded
resistance/power payloads and require a synchronous authorization callback that
returns exactly true after acquiring the lock and immediately before each write.
Request Control and the target each require a matched successful indication.
Timeouts, rejection, cancellation and a disconnect cannot become success; cleanup
releases ownership. Finish also rechecks that its requested session is still
current and the coordinator is open before each command.

Nine synthetic tests verify serialization, queued gate revocation, gate revocation
after Request Control, rejection/timeouts, invalid inputs, disconnect, cancellation
cleanup (including interrupted notification setup) and Finish session-guard
revocation. The full source suite passes 106 tests.
A shared protocol owner does not itself implement approved automatic policy,
arming, HR source/freshness validation, ramp/dwell limits, a confirmed baseline,
or a Basil-specific control audit. Those remain required before automation.

Before connecting Basil's controller to the manual target entities, implement
and verify all of:

- Administrator-approved, versioned policy limits, with Coach Basil choosing
  strategy. The technical helper cannot establish that a supplied policy was
  approved.
- One serialized control-point owner shared with Finish, matching successful
  indications, bounded timeout and rejection reporting. No competing notification
  subscriptions or overlapping procedures; no automatic reapply after reconnect.
- Fresh observed telemetry and validated chest-strap HR, explicit control arming,
  per-change/dwell/rate limits and a known target baseline. Actual rider power is
  not a substitute for the last confirmed target-power command.
- Immediate manual override/disarm precedence, stale-data/disconnect handling,
  audit records and visible failure status. Keep the LLM outside the live loop.
- A supervised narrow-range real-bike test including successful acknowledgement,
  console behavior, override and deliberate stale/connection-loss scenarios.

The chest-strap check and device writes need a rider; protocol rejection and
timeout behavior can be tested with synthetic clients before that live trial.
Preparing this encoder does not establish any of those remaining requirements.

The interrupted-subscription regression first failed: start_notify can have
enabled indications before its await completes. The prepared owner now attempts
bounded stop_notify cleanup even if setup times out or is cancelled. The test
verifies both paths and subsequent owner reuse. This is not a real-radio result.
