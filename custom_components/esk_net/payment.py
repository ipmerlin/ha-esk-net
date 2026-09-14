"""On-demand SBP QR state, held only in memory."""

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .parser import AuthenticationError, EskError
from .sbp import SbpError, validate_amount


class SbpPayment:
    def __init__(self, hass, entry, client, account):
        self.hass, self.entry, self.client, self.account = hass, entry, client, account
        self.amount = 10
        self.qr = None
        self.created_at = None
        self.busy = False
        self.listeners = set()

    @callback
    def subscribe(self, listener):
        self.listeners.add(listener)
        return lambda: self.listeners.discard(listener)

    @callback
    def notify(self):
        for listener in tuple(self.listeners):
            listener()

    @callback
    def set_amount(self, value):
        if self.busy:
            raise ServiceValidationError("Дождитесь получения QR")
        try:
            amount = validate_amount(value)
        except SbpError as err:
            raise ServiceValidationError("Введите целое число от 10 до 100000 рублей") from err
        if amount != self.amount:
            self.amount = amount
            self.qr = None
            self.created_at = None
            self.notify()

    async def async_generate(self):
        if self.busy:
            raise ServiceValidationError("QR уже запрашивается")
        self.busy = True
        self.qr = None
        self.created_at = None
        self.notify()
        try:
            self.qr = await self.client.async_generate_qr(self.amount, self.account)
            self.created_at = dt_util.utcnow()
        except AuthenticationError as err:
            self.entry.async_start_reauth(self.hass)
            raise HomeAssistantError("Проверьте учётные данные ЕСК") from err
        except EskError as err:
            raise HomeAssistantError(
                "Не удалось получить QR СБП. Попробуйте запросить его позже"
            ) from err
        finally:
            self.busy = False
            self.notify()


class PaymentEntity:
    """Shared push updates for the amount, button and image entities."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def setup_payment(self, payment, key):
        self.payment = payment
        self._attr_unique_id = f"{payment.account}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, payment.account)})

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.payment.subscribe(self.async_write_ha_state))
