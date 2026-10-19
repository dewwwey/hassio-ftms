"""Select advertised FTMS machine; verify capabilities on connection."""
import voluptuous as vol
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_ADDRESS
from ._vendor import pyftms


class FTMSConfigFlow(ConfigFlow, domain="ftms"):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        devices = {}
        for info in bluetooth.async_discovered_service_info(self.hass, connectable=True):
            try:
                pyftms.get_machine_type_from_service_data(info.advertisement)
            except pyftms.NotFitnessMachineError:
                continue
            devices[info.address] = info.name
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            if address not in devices:
                return self.async_abort(reason="no_devices_found")
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=devices[address], data={CONF_ADDRESS: address})
        if not devices:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(step_id="user", data_schema=vol.Schema({
            vol.Required(CONF_ADDRESS): vol.In(devices),
        }))

    async def async_step_bluetooth(self, discovery_info):
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        return await self.async_step_user()
