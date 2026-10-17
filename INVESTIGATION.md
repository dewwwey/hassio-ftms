# Evidence and current limits — 2026-10-17

This report contains technical evidence only. Raw exercise observations, Bluetooth
addresses and credentials are excluded. Private source journal stays in HA.

## Findings

1. HA Core 2026.10.1 on Pi 4 / HAOS 18.3, Python 3.14.6; HACS 2.0.5.
   There initially was no installed FTMS component or entry. The built-in Pi
   Bluetooth entry was disabled. Historical failure logs from the old experiment
   were unavailable; unrelated old tracker errors are not evidence about FTMS.
2. Enabling the Pi adapter and active scanning exposed an FTMS candidate and its
   Device Information service. Passive scanning had omitted the scan response.
   Reception was weak and the candidate later disappeared from current discovery.
   One cached advertisement's machine-type bytes decoded as treadmill; a later
   advertisement decoded as indoor bike. The reason for that discrepancy is not
   established. Live GATT subsequently verified Indoor Bike.
3. The administrator reported about five metres separation and connected an ASUS
   USB dongle. HA identifies it as Broadcom BCM20702A0 (USB product 0b05:17cb).
   With its Bluetooth entry enabled and active scanning selected, the candidate
   reappeared. The Pi adapter was returned to disabled. Discovery improved;
   reception remained modest and long-term radio reliability is unproven.
4. The read-only custom component connected through the ASUS adapter and verified
   the Indoor Bike realtime GATT characteristic. Feature reads and notification
   decoding succeeded on actual HA Python 3.14.6. Fresh idle packets were received
   at approximately one per second. Cadence/speed/power/distance/time were idle,
   and no workout was created. Energy-rate fields were absent/unavailable.
   A heart-rate zero placeholder is not a validated pulse; dev2 suppresses it.
5. After roughly three idle minutes the connection disappeared. The retry raised
   BleakOutOfConnectionSlotsError. Diagnostics showed FIVE adapter slots and ZERO
   allocations, so that label did not demonstrate slot exhaustion. Connector logs
   instead said the device was absent from current scanner devices while an older
   advertisement remained in history. No manual bike reset was used. Sleep/radio
   loss versus firmware behavior is not yet isolated; no hard-reset root cause is
   claimed.
6. Dev2 requires current scanner discovery before attempting a connection,
   bounds reconnect scheduling and filters missing HR placeholders. It also adds
   explicit storage-health metadata to completed-session export and closes an
   over-30-minute outage before accepting a later ride, even without a running
   watchdog during setup retries. Those changes pass local regression tests.
7. Dev3 removes all proposed amounts and eligibility verdicts from telemetry.
   Coach Basil's synthetic validation found gaps in its separate ledger's schema,
   confirmation gate, second/minute conversion and timestamp-string deduplication.
   Those fixes belong to basilisk-dev; no real ledger was changed by this work.
   HA exports exact observed seconds, stable IDs and quality facts only.

## Available entities

Verified created under `sensor.kettler_ftms_`:
speed, speed_average, cadence, cadence_average, distance_total, resistance_level,
power, power_average, energy_total, energy_per_hour, energy_per_minute, heart_rate,
metabolic_equivalent, time_elapsed, telemetry_status.

Creation/feature support does not prove a usable metric. Moving-bike cadence,
power, speed, distance and time have now been observed. Calorie/MET accuracy and
an actual pulse source remain unvalidated. Unsent energy-rate metrics stay
unavailable. See the private interface document for freshness/absence rules.
Version 0.24.8 adds a scoped explicit Finish button; general controls stay absent.

## Subsequent live acceptance

The administrator rode while dev3 was connected. The integration received changing
cadence, speed, power, distance and elapsed time. Reloading only the FTMS entry
during riding automatically reconnected, preserved the session ID, excluded the
unknown interval and flagged the interruption. That deliberately partial record
then finalized correctly after observed inactivity. Repeated exports were identical.

A separate start/stop ride was observed from its beginning and finalized as
complete, with no flags. Independent calculation from the private journal matched
the summary's start/end, active/total time and observed distance. Neither summary
contains monetary fields or inferred intent. Actual measurements and IDs are
excluded from this report and repository.

The administrator confirmed immediate connection after one complete power cycle.
After a later HA restart, the awake bike disappeared from current discovery on
both the ASUS and temporarily enabled Pi scanners, while an independent Windows
scan received its FTMS advertisements. Reloading ASUS scanning did not immediately
recover it. It later connected through the Pi; the administrator had also moved
its supply to a smart plug, so this is not counted as unattended recovery.

The host kernel reports a missing BCM20702A1 firmware patch for the ASUS dongle.
HA documentation identifies this Broadcom firmware limitation on HAOS. This is
a diagnostic finding, not proof of the cause; an extension cable is already in
use. Both scanners were temporarily retained to compare discovery.

The first authorized smart-plug cycle exposed a distinct software bug in this
branch: an unmarked synchronous reconnect timer ran in an executor thread, and
HA rejected its event-loop-only reload call. The entry remained loaded but
disconnected after discovery returned. Dev2 marks the timer as `@callback`, clears
its handle and checks shutdown state. A regression verifies this dispatch
contract. Three subsequent controlled power cycles recovered automatically,
including ASUS-only scanning and a longer powered-off interval. FTMS stayed
enabled; no agent-triggered integration/scanner reload was needed during these
cycles. Completed records replayed after HA restart without phantom sessions.
The Pi scanner was restored to disabled. Intermittent discovery loss and
long-term sleep/wake reliability remain open.

The console's hold-play/pause finish action fails in FTMS mode. A diagnostic
disconnect made it exit to the start screen; this is unsuitable for normal use.
FTMS stays enabled. Version 0.24.8 introduces Request Control then Stop only on an
explicit Finish action. On the idle real device, Request Control was acknowledged
but Stop was not acknowledged before timeout. No success or final session was
fabricated. Dev2 reports the failing opcode in timeout errors. A post-ride test
and physical console confirmation remain required.

Other open checks include repeated sleep/wake and radio-loss recovery, paused
ride resumption, phone contention, persistent offline last-seen metadata,
multi-user identity and long-term durability. See ACCEPTANCE.md for exact status.
