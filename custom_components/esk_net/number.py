"""SBP amount input; changing it does not generate a payment request."""

from homeassistant.components.number import NumberEntity, NumberMode

from .payment import PaymentEntity
from .sbp import MAX_AMOUNT, MIN_AMOUNT

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([SbpAmount(entry.runtime_data.payment)])


class SbpAmount(PaymentEntity, NumberEntity):
    _attr_native_min_value = MIN_AMOUNT
    _attr_native_max_value = MAX_AMOUNT
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "RUB"
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:cash"

    def __init__(self, payment):
        self.setup_payment(payment, "sbp_amount")

    @property
    def native_value(self):
        return self.payment.amount

    async def async_set_native_value(self, value):
        self.payment.set_amount(value)
