"""Create a HA-managed connection with a private cookie jar."""

from aiohttp import ClientTimeout, CookieJar
from homeassistant.helpers.aiohttp_client import async_create_clientsession


def create_session(hass):
    return async_create_clientsession(
        hass,
        auto_cleanup=False,
        cookie_jar=CookieJar(),
        timeout=ClientTimeout(total=30),
    )
