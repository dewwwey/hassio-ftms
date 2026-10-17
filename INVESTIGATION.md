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

Creation/feature support does not prove a usable metric. No positive workout
values, calories, MET or pulse are validated yet. Unsent energy-rate metrics stay
unavailable. HR needs an actual source. See the private interface document for
freshness/absence rules. No controls are registered.

## Remaining live work

The administrator was asked to perform a short ride and leave the console awake
for two minutes afterward. A completed real ride, final session summary, full
time-series comparison, and interruption/recovery acceptance are still pending.
Local tests and an idle BLE connection cannot substitute for those observations.

The next checks are final-version startup, a real recorded ride, duplicate export,
entry reload, USB scanner disable/enable, and HA restart replay. Bike power cycling,
phone contention, multi-user identity, long-term durability and radio stability
remain explicit untested cases until exercised.
