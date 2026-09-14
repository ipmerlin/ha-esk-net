"""One poll for all ESK entities."""

import logging
from datetime import timedelta

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_ACCOUNT, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL, DOMAIN
from .parser import AuthenticationError, EskError


class EskCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry, client):
        super().__init__(
            hass,
            logging.getLogger(__name__),
            config_entry=entry,
            name=DOMAIN,
            always_update=False,
            update_interval=timedelta(
                minutes=entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
            ),
        )
        self.client = client
        self.account = entry.data[CONF_ACCOUNT]

    async def _async_update_data(self):
        try:
            data = await self.client.async_fetch()
            if data.account != self.account:
                raise AuthenticationError("Account changed; check credentials")
            return data
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed("Check ESK credentials") from err
        except EskError as err:
            raise UpdateFailed(str(err)) from err
