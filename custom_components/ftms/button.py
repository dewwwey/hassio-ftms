"""Explicit Finish workout action; the connection remains enabled."""
from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import callback
from .entity import FtmsEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([FinishWorkoutButton(entry)])


class FinishWorkoutButton(FtmsEntity, ButtonEntity):
    _attr_name = "Finish workout"
    _attr_icon = "mdi:flag-checkered"
    _attr_translation_key = None

    def __init__(self, entry):
        super().__init__(entry, ButtonEntityDescription(key="finish_workout"))
        self._attr_translation_key = None

    async def async_press(self):
        await self.coordinator.async_finish_workout()

    @callback
    def _handle_coordinator_update(self):
        self.async_write_ha_state()
