"""Explicit user action to obtain a payment QR."""

from homeassistant.components.button import ButtonEntity

from .payment import PaymentEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([SbpGenerate(entry.runtime_data.payment)])


class SbpGenerate(PaymentEntity, ButtonEntity):
    _attr_icon = "mdi:qrcode-plus"

    def __init__(self, payment):
        self.setup_payment(payment, "sbp_generate")

    @property
    def available(self):
        return not self.payment.busy

    async def async_press(self):
        await self.payment.async_generate()
