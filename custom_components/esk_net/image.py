"""Serve the QR through HA's image entity, without public files or URLs."""

from homeassistant.components.image import ImageEntity

from .payment import PaymentEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([SbpImage(hass, entry.runtime_data.payment)])


class SbpImage(PaymentEntity, ImageEntity):
    _attr_content_type = "image/png"
    _attr_icon = "mdi:qrcode"

    def __init__(self, hass, payment):
        ImageEntity.__init__(self, hass)
        self.setup_payment(payment, "sbp_qr")

    @property
    def available(self):
        return self.payment.qr is not None

    @property
    def image_last_updated(self):
        return self.payment.created_at

    @property
    def extra_state_attributes(self):
        return {
            "amount": self.payment.amount if self.payment.qr is not None else None,
            "currency": "RUB",
        }

    async def async_image(self):
        return self.payment.qr
