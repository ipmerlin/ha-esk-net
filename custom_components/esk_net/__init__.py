"""ESK Net personal cabinet integration."""

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform

from .api import EskClient
from .coordinator import EskCoordinator
from .session import create_session

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass, entry):
    session = create_session(hass)
    coordinator = EskCoordinator(
        hass, entry, EskClient(session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    )
    try:
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        session.detach()
        raise
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    entry.async_on_unload(session.detach)
    return True


async def async_reload_entry(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
