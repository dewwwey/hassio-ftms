# Acceptance checklist

Status must be based on real results, with private observations kept out of
public reports. Synthetic tests do not prove bike behavior.

## Verified baseline (2026-10-17)

- [x] HA Core 2026.10.1 / HAOS 18.3 / Pi 4 / Python 3.14.6; HACS 2.0.5.
- [x] Local bcm43438-bt UART adapter; no active proxy scanner in HA diagnostics.
- [x] Initially Bluetooth entry disabled, no installed FTMS component or entry.
- [x] User reported bike awake and other fitness applications disconnected.
- [x] Passive mode saw bike name but missed FTMS scan-response data.
- [x] Active mode saw FTMS 1826 service data and Device Information 180a.
- [x] Weak reception observed. Its causal role is unverified.
- [x] Exact upstream requirement excludes Python 3.14; current upstream too.
- [x] Local suite: 25 tests pass under Python 3.14.0, bleak 3.0.2,
      bleak-retry-connector 4.7.1. Includes decoding, zero/repeated fields,
      disappearing fields, malformed frames, denied control, session/reward
      boundaries, gap/pause/reset/restart semantics, journal flush, truncated-tail
      recovery and preservation of corrupt complete records.
- [x] Initial HA config check passed after installation.

## Live acceptance to record

- [x] FTMS entry connects and GATT feature reads succeed on HA Python 3.14.6
      (initial dev1 connection); final dev2 restart recovery is pending.
- [ ] List actually observed metrics; distinguish capabilities from usable data.
- [x] Observe idle zeros and fresh timestamps without phantom sessions (dev1).
- [ ] Record a real start, ride, stop, two-minute idle finalization; inspect time
      series and summary privately against the user's timing.
- [ ] Query completed sessions twice and verify stable IDs/summary/no duplicates.
- [ ] Pause/resume before idle timeout retains ID and excludes pause time.
- [ ] Reload FTMS entry: automatic reconnect, fresh sensor values, same session
      ID with disconnect/restart flag when a ride was in progress.
- [ ] Bike sleep/wake and power cycle: recover without HA or bike reset beyond
      the deliberate test power cycle; time and quality reflect unknown gaps.
- [ ] Adapter disable/enable: recover with bounded retries; do not claim a ride
      ended successfully while radio transport was absent.
- [ ] HA restart: connection and journal replay recover automatically.
- [ ] In-use phone app scenario: diagnose contention without resetting hardware.
- [ ] Storage faults do not produce unqualified reward evidence.
- [ ] Read-only diagnostics omit health data and device identifiers.

Not a prerequisite for Coach Basil launch. Reward ledger integration and any
private data-package handoff require separate verification and applicable consent.
