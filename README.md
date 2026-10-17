# Fitness Machine Service

This local branch records observed Kettler HOI Ride+ telemetry and exposes one
optional, experimental **Finish workout** action. FTMS stays enabled between workouts.
See [USER_STORY.md](USER_STORY.md) for the revised connection-first coaching
workflow and its unimplemented requirements, including private start events,
incremental source-data access and bounded automatic intensity control.
See [PATCHES.md](PATCHES.md) for source provenance and rollback,
[BASIL_INTERFACE.md](BASIL_INTERFACE.md) for the private telemetry/session API,
and [ACCEPTANCE.md](ACCEPTANCE.md) for verified versus untested behavior.
General controls are disabled; Finish only requests control and sends FTMS Stop.
This branch is installed manually and is not an upstream
release or a published HACS repository.

[Home Assistant](https://www.home-assistant.io/) [HACS](https://hacs.xyz/) custom component for working with fitness equipment with a Bluetooth interface.

The component is based on the [pyftms](https://github.com/dudanov/pyftms) library, which complies with the [Bluetooth Fitness Machine Service v1.0 standard](https://www.bluetooth.com/specifications/specs/fitness-machine-service-1-0/).

Component capabilities:

1. Automatically detect Bluetooth fitness devices nearby, notifying the user about it;
2. Setup Wizard, which allows you to easily configure the device by determining its type and set of sensors in automatic or manual modes. The set of sensors can be changed.
3. Collects training data and provides an acknowledged Finish action; parameter controls remain disabled.

Supported fitness machines:

1. **Treadmill**
2. **Cross Trainer** (Elliptical Trainer)
3. **Rower** (Rowing Machine)
4. **Indoor Bike** (Spin Bike)

Device view example for `FitShow FS-BT-D2 Indoor bike` fitness machine:

![image](images/main.png)

## Installation

### HACS

Follow [this guide](https://hacs.xyz/docs/faq/custom_repositories/) to add this git repository as a custom HACS repository. Then install from HACS as normal.

### Manual Installation

Copy `custom_components/ftms` into your Home Assistant `$HA_HOME/config` directory, then restart Home Assistant.

## Disclaimer

Since there is a lot of different equipment that I do not own, and given the fact that not all manufacturers follow the FTMS standard strictly, some functions may not work correctly or not work at all.
Please create an [issue](https://github.com/dudanov/hassio-ftms/issues), and I will try to help solve the problem.

## Support

If you find the component useful and want to support me and my work, you can do this by sending me a donation in [TONs](https://ton.org/): `UQCji6LsYAYrJP-Rij7SPjJcL0wkblVDmIkoWVpvP2YydnlA`.
