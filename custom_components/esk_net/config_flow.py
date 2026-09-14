"""UI setup, credential recovery and polling options."""

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .api import CannotConnect, EskClient
from .const import CONF_ACCOUNT, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL, DOMAIN
from .parser import AuthenticationError, ParseError
from .session import create_session


def credentials_schema(username=""):
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME, default=username): str,
            vol.Required(CONF_PASSWORD): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
        }
    )


class EskConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _validate(self, user_input):
        session = create_session(self.hass)
        try:
            return await EskClient(
                session, user_input[CONF_USERNAME].strip(), user_input[CONF_PASSWORD]
            ).async_fetch()
        finally:
            session.detach()

    async def async_step_user(self, user_input=None):
        return await self._credentials_step("user", user_input)

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        return await self._credentials_step("reauth_confirm", user_input)

    async def _credentials_step(self, step, user_input):
        errors = {}
        reauth = step == "reauth_confirm"
        entry = self._get_reauth_entry() if reauth else None
        if user_input is not None:
            try:
                data = await self._validate(user_input)
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except ParseError:
                errors["base"] = "cannot_parse"
            else:
                await self.async_set_unique_id(data.account)
                saved = {
                    CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_ACCOUNT: data.account,
                }
                if reauth:
                    self._abort_if_unique_id_mismatch()
                    return self.async_update_reload_and_abort(entry, data_updates=saved)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=f"ЕСК {data.account}", data=saved)
        username = (
            user_input.get(CONF_USERNAME, "")
            if user_input
            else (entry.data[CONF_USERNAME] if entry else "")
        )
        return self.async_show_form(
            step_id=step, data_schema=credentials_schema(username), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return EskOptionsFlow()


class EskOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=30, max=1440)),
                }
            ),
        )
