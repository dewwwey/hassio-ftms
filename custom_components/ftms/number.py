"""Acknowledged FTMS target controls for resistance and power."""
from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.core import callback

from . import FtmsConfigEntry
from .entity import FtmsEntity


TARGETS = {
    "target_resistance": {
        "name": "Target resistance",
        "unit": None,
        "icon": "mdi:dumbbell",
    },
    "target_power": {
        "name": "Target power",
        "unit": "W",
        "icon": "mdi:flash",
    },
}


async def async_setup_entry(hass, entry: FtmsConfigEntry, async_add_entities):
    """Create controls only when the bike advertises a supported range."""
    ftms = entry.runtime_data.ftms
    entities = [
        FtmsTargetNumber(entry, setting)
        for setting in TARGETS
        if setting in ftms.supported_settings and setting in ftms.supported_ranges
    ]
    async_add_entities(entities)


class FtmsTargetNumber(FtmsEntity, NumberEntity):
    """Manual setpoint control, bounded by the range advertised by the bike."""

    _attr_mode = NumberMode.SLIDER
    _attr_translation_key = None

    def __init__(self, entry: FtmsConfigEntry, setting: str) -> None:
        self.setting = setting
        config = TARGETS[setting]
        machine_range = entry.runtime_data.ftms.supported_ranges[setting]
        super().__init__(entry, NumberEntityDescription(key=setting))
        self._attr_name = config["name"]
        self._attr_native_min_value = machine_range.min_value
        self._attr_native_max_value = machine_range.max_value
        self._attr_native_step = machine_range.step
        self._attr_native_unit_of_measurement = config["unit"]
        self._attr_icon = config["icon"]
        self._attr_native_value = self.coordinator.target_values.get(setting)

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.fresh

    async def async_set_native_value(self, value: float) -> None:
        """Write the target and update HA only after a successful FTMS response."""
        await self.coordinator.async_set_target(self.setting, value)
        self._attr_native_value = float(value)
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_native_value = self.coordinator.target_values.get(self.setting)
        self.async_write_ha_state()
