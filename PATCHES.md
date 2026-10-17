# Read-only FTMS compatibility branch

Local implementation owner: `homeassistant-dev`, NEXUS discussion 5.
Branch: `homeassistant-dev/ftms-readonly`.

## Provenance and reason for the patch

- Integration baseline: dudanov/hassio-ftms commit
  `15aeb798dea9206929fce417e6bceefe43e352f2`, version 0.24.6.
- Vendored library: dudanov/python-pyftms commit
  `2d60298fb8869f833c8a9c7f16f246b93d2f50a0`, version 0.4.15.
  Apache-2.0 license retained under `_vendor/PYFTMS-LICENSE`.
- Upstream integration requires pyftms 0.4.10, whose wheel requires Python
  >=3.12,<3.14. Current upstream 0.4.15 also excludes 3.14. The actual HA
  installation uses Python 3.14.6. No system package constraints were overridden.
  Sources are pinned locally and validated with Python 3.14 before deployment.
- Vendoring is an interim compatibility measure, not a claim of upstream support.
  Replace it with a released dependency after upstream Python 3.14 support and
  the packet regressions are addressed.

## Changes

- Sensor platform only. Button, switch and number platforms removed; all
  library command calls raise PermissionError. No request-control, resistance,
  start/stop/reset or other application control writes. BLE notification
  subscription still writes the standard CCCD, as required by BLE.
- Use HA's shared scanner and connectable BLE device, refreshed via advertisement
  callbacks; BleakClientWithServiceCache; two connector attempts, 40-second setup
  timeout, HA-managed retry/backoff on setup failure. No reset of the shared adapter
  or indiscriminate close_stale_connections call.
- Full realtime frames are delivered, including repeated and all-zero frames.
  Removed upstream set-difference logic that could reference missing fields.
  Malformed packets clear the assembly and produce a quality event.
- No fabricated startup zeros. Each metric expires ten seconds after its own last
  notification. Status or RSSI updates cannot refresh exercise measurements.
  A 30-second notification stall reloads the config entry.
- Private append-only sample journal, fsync on each record, bounded write queue,
  deterministic session replay, and explicit storage-error status.
- Corrected energy-rate sensor units to kcal/h and kcal/min.
- Simplified config flow compatible with current HA, with duplicate entry checks.
- Verify the FTMS realtime GATT characteristic and choose its decoder rather than
  trusting advertised machine type; fail closed on ambiguity. A captured bike
  advertisement reports treadmill. The bike's actual GATT type is still to be
  verified in live acceptance.

## Installation and rollback

Copy `custom_components/ftms` to `/config/custom_components/ftms`, run HA's config
check, restart HA, enable its Bluetooth adapter and select active scanning, then
add the FTMS integration. Select the actual bike. Keep other fitness clients
disconnected during initial tests. Do not enable control platforms from upstream.

This is a manually installed local branch. HACS must not overwrite it. No other
integration or Python installation was replaced.

Rollback: disable the FTMS config entry, preserve `/config/.storage/ftms/` if its
private records are wanted, remove only `/config/custom_components/ftms`, and
restart HA. The pre-investigation state had no installed FTMS component. The
Bluetooth entry was disabled with mode `auto`; restore those settings if desired.
Do not edit HA's live `.storage/core.config_entries` file manually.

## Upstream recommendations

- Python 3.14 compatibility/package support: library scope; see existing PR 60.
- Preserve zero packets and snapshot/diff correctness: library scope; compare
  PRs 61 and 69. This deployment emits full frames because timestamps require
  receipt evidence even when a value is unchanged.
- Bound startup, clean up partial connections, and retry errors: integration
  scope; compare existing PR 53.
- Explicit sensor freshness and a read-only option: integration scope.
- Discovery matcher changes are unnecessary for this bike once active scanning
  supplies its service data; no name-based discovery exception was added.

The earlier historical hard-reset failures remain unexplained until reproduced.
Weak radio reception is a hypothesis, not a demonstrated root cause.
