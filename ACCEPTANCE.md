# Acceptance checklist

Status must be based on real results, with private observations kept out of
public reports. Synthetic tests do not prove bike behavior.

The administrator's revised priorities are in USER_STORY.md. Reliable capture and
coaching access take priority over formal session boundaries and explicit Finish.
The latest wake-by-pedalling test produced no new exercise samples in the private
journal; cold power-cycle success does not close standby-wake acceptance.
Private start notification, incremental raw-data access, verified chest-strap HR
and approved bounded intensity control are new acceptance work, not implemented
capabilities of version 0.24.8.dev2.

## Verified baseline (2026-10-17)

Current follow-up (2026-10-18): 53 local tests pass under the existing project
Python environment. Dev4 adds offline session/count/metric-name recovery and
checks that a persisted onset event survives replay while disconnect alone
cannot invent a completed workout. The existing private journal replays and has
a completed summary but no durable onset event; a null `latest_event` is correct
for that older data. These checks do not establish real-bike onset delivery or
coaching receipt. A separate template diagnostic entity exposes status through
ordinary entity reads outside the FTMS entry lifecycle.
Dev5's added fault-injection test first reproduced an onset event being emitted
after its sample write failed. The corrected writer suppresses that event,
retains a suppression marker and storage fault, and keeps later samples marked
with the storage gap. HA's real disk was not deliberately faulted.

- [x] HA Core 2026.10.1 / HAOS 18.3 / Pi 4 / Python 3.14.6; HACS 2.0.5.
- [x] Local bcm43438-bt UART adapter; no active proxy scanner in HA diagnostics.
- [x] Initially Bluetooth entry disabled, no installed FTMS component or entry.
- [x] User reported bike awake and other fitness applications disconnected.
- [x] Passive mode saw bike name but missed FTMS scan-response data.
- [x] Active mode saw FTMS 1826 service data and Device Information 180a.
- [x] Weak reception observed. Its causal role is unverified.
- [x] Exact upstream requirement excludes Python 3.14; current upstream too.
- [x] Local suite: 38 tests pass under Python 3.14.0, bleak 3.0.2,
      bleak-retry-connector 4.7.1. Includes decoding, zero/repeated fields,
      disappearing fields, malformed frames, denied control, exact duration
      boundaries, gap/pause/reset/restart semantics, journal flush, truncated-tail
      recovery and preservation of corrupt complete records. Finish tests cover
      acknowledgement matching, rejected control/stop, bounded timeouts, cleanup,
      offline refusal, duplicate completion, idle rearming and the event-loop
      reconnect timer contract.
- [x] Initial HA config check passed after installation.

## Live acceptance to record

- [x] Explicit Start Ride recovery on dev4: first persisted idle sample 17.45
      seconds after invocation; script completed and displayed Bike ready.
      No activity event was generated. Private run evidence is saved locally.
- [x] Invoke Start Ride again while already ready: script completed immediately,
      reported existing fresh recording and left the plug's last-change timestamp
      unchanged. This verifies the no-reset path for an idle connected bike.
- [x] Controlled status-read failure probe: the real read action rejected an
      unknown entry; the production guard produced its expected error path and
      stopped. The isolated probe contained no hardware actions; plug state and
      journal bytes were unchanged, and the temporary script/notice were removed.
      This does not prove a real failed Bluetooth recovery or storage fault.
- [ ] Start Ride refuses recovery during a real recent ride or storage fault.
- [ ] Start Ride reports a real recovery failure clearly; no repeated cycling.

- [x] FTMS entry connects and GATT feature reads succeed on HA Python 3.14.6,
      including dev3 with real moving-bike telemetry.
- [x] Observe changing cadence, speed, power, distance and elapsed time. HR is
      absent/unavailable. Energy/MET and average fields are received but their
      accuracy has not been independently established; energy-rate fields are absent.
- [x] Observe idle zeros and fresh timestamps without phantom sessions (dev3).
- [x] Record a real start, ride, stop, two-minute idle finalization; inspect time
      series and summary privately against the user's timing.
- [x] Query completed sessions twice and verify stable IDs/summary/no duplicates.
- [ ] Pause/resume before idle timeout retains ID and excludes pause time.
- [x] Reload FTMS entry: automatic reconnect, fresh sensor values, same session
      ID with disconnect/restart flag when a ride was in progress.
- [x] Full bike power-off/on: user confirmed immediate automatic connection,
      with FTMS left enabled and no scanner or HA restart during the cycle.
- [x] Repair the reproduced reconnect timer failure: HA rejected a reload called
      from an executor thread. Dev2 uses a marked event-loop callback. Three
      subsequent controlled power cycles recovered automatically, including
      ASUS-only scanning and a 45-second powered-off interval; no entry/scanner
      reload was manually triggered during those cycles. No phantom sessions.
- [ ] Resolve intermittent discovery loss across repeated unattended sleep/wake
      and HA restarts. Three successful cycles do not prove long-term reliability.
- [ ] Ordinary unattended sleep/wake over repeated cycles and longer outages.
- [ ] Adapter disable/enable: recover with bounded retries; do not claim a ride
      ended successfully while radio transport was absent.
- [x] HA restart: connection and completed-journal replay recovered automatically
      on dev2. A real in-progress HA crash/restart remains untested separately.
- [ ] In-use phone app scenario: diagnose contention without resetting hardware.
- [ ] Storage faults do not produce unqualified reward evidence.
- [x] Custom diagnostic payload omits health measurements and device/session
      identifiers. HA's generic wrapper still includes its config-entry metadata.

The first live recorded segment has an unobserved start and a deliberate entry
reload. It finalized automatically after observed inactivity and correctly has
partial quality. An independent journal calculation verified observed start/end,
active/total time, distance deltas, interruption flags, healthy storage and absence
of monetary fields. Private samples and summaries are excluded from this repo.
A separate clean-start/full-finish ride also passed, with complete quality and
no flags. Its recorded boundaries, active/total time and observed distance deltas
match the independent journal calculation. Missing HR and energy-rate sensors
were confirmed unavailable while valid telemetry remained fresh.

The administrator reported that holding the console's play/pause button does not
finish the workout in FTMS mode. A diagnostic disconnect caused the console to
exit the workout; that is unsuitable for normal usage. FTMS was re-enabled and
stays enabled. Version 0.24.8.dev2 adds an explicit HA Finish workout action using
acknowledged Request Control then Stop. This is the only application control
scope; it is never sent automatically. Request Control succeeds on the idle bike,
but Stop times out without acknowledgement. Post-ride command/console acceptance
is pending; the installed action is experimental and reports this failure.

Not a prerequisite for Coach Basil launch. Reward ledger integration and any
private data-package handoff require separate verification and applicable consent.


Publisher dev6 acceptance: 106 source tests pass, HA restart loaded armed, durable
Pi-side queue cursor readback retains activation, no old event queued. HA-side
test_ping accepted/woke and subsequent same-identity receipt lookup confirms
completed/skipped/terminal with no second POST. This proves synthetic transport
and correlated receipt consumption; next genuine workout must still prove
automatic onset-to-private coaching response.
