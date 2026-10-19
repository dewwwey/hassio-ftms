# Direct Wear OS heart-rate prerequisite

The administrator requested repair of the Pixel Watch 2 HA app entity-list error
and evaluation of the direct watch HR sensor as a secondary source. This does not
replace the primary chest strap or enable automatic source failover/control.

The Wear OS companion app exposes a native heart-rate sensor with an accuracy
attribute. This is separate from the Android phone Health Connect heart-rate
sensor. Enable it in the watch app and grant the required sensor/background
permissions; enabling an entity registry entry alone does not establish a working
watch data path. The app needs connectivity and permission to send updates.

A loaded mobile_app registration or an old battery state does not prove current
watch connectivity. Diagnose the actual saved app server URL, watch Wi-Fi versus
phone Bluetooth-proxy transport, authentication and certificate errors separately.
A working phone app does not establish that its VPN route is shared with a watch.
Avoid changing HA-wide external access, proxy trust or authentication merely to
work around an unconfirmed watch route. Do not delete the existing device before
its app connection and saved settings have been inspected.

Acceptance must measure fresh HR observations, accuracy metadata, update gaps and
latency with the watch app open and in the background/screen-off, loss of network,
off-wrist state and recovery. The official documentation does not promise
continuous low-latency delivery. HA state timestamps or a forced sensor refresh
alone are not necessarily physiological sample timestamps. Keep the source
identity explicit and reject stale/missing values rather than substituting zero.
Agree fallback and override behavior with the coach before using it for control.

Private diagnosis details remain in the investigation's ignored private folder.
No health samples, device identifiers or credentials belong in NEXUS.

Sources: [Wear OS overview](https://companion.home-assistant.io/docs/wear-os/),
[Wear OS sensors](https://companion.home-assistant.io/docs/wear-os/sensors/),
[Companion networking](https://companion.home-assistant.io/docs/troubleshooting/networking/).
