"""On-demand payment state and HA entities without real payment requests."""

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.esk_net.api import CannotConnect
from custom_components.esk_net.button import SbpGenerate
from custom_components.esk_net.image import SbpImage
from custom_components.esk_net.number import SbpAmount
from custom_components.esk_net.parser import AuthenticationError
from custom_components.esk_net.payment import SbpPayment


class PaymentTests(unittest.IsolatedAsyncioTestCase):
    def make_payment(self):
        return SbpPayment(
            Mock(), Mock(), Mock(async_generate_qr=AsyncMock(return_value=b"png")), "001"
        )

    async def test_amount_and_image_reads_do_not_request(self):
        payment = self.make_payment()
        number = SbpAmount(payment)
        await number.async_set_native_value(1001)
        self.assertEqual(number.native_value, 1001)
        with patch("homeassistant.components.image.get_async_client", return_value=Mock()):
            image = SbpImage(payment.hass, payment)
        self.assertIsNone(await image.async_image())
        self.assertFalse(image.available)
        payment.client.async_generate_qr.assert_not_awaited()
        await SbpGenerate(payment).async_press()
        payment.client.async_generate_qr.assert_awaited_once_with(1001, "001")
        self.assertEqual(await image.async_image(), b"png")
        self.assertEqual(image.extra_state_attributes["amount"], 1001)
        self.assertIsNotNone(image.image_last_updated)
        payment.set_amount(10)
        self.assertIsNone(await image.async_image())
        self.assertFalse(image.available)

    async def test_failure_clears_old_qr(self):
        payment = self.make_payment()
        await payment.async_generate()
        payment.client.async_generate_qr.side_effect = CannotConnect()
        with self.assertRaises(HomeAssistantError):
            await payment.async_generate()
        self.assertIsNone(payment.qr)
        self.assertIsNone(payment.created_at)
        self.assertFalse(payment.busy)

    async def test_busy_prevents_duplicate_and_amount_changes(self):
        payment = self.make_payment()
        entered, release = asyncio.Event(), asyncio.Event()

        async def generate(*args):
            entered.set()
            await release.wait()
            return b"png"

        payment.client.async_generate_qr.side_effect = generate
        task = asyncio.create_task(payment.async_generate())
        await entered.wait()
        try:
            with self.assertRaises(ServiceValidationError):
                payment.set_amount(1001)
            with self.assertRaises(ServiceValidationError):
                await payment.async_generate()
        finally:
            release.set()
            await task
        self.assertEqual(payment.amount, 10)
        payment.client.async_generate_qr.assert_awaited_once()

    async def test_auth_failure_starts_reauth(self):
        payment = self.make_payment()
        payment.client.async_generate_qr.side_effect = AuthenticationError()
        with self.assertRaises(HomeAssistantError):
            await payment.async_generate()
        payment.entry.async_start_reauth.assert_called_once_with(payment.hass)

    async def test_listener_unsubscribe(self):
        payment = self.make_payment()
        listener = Mock()
        unsubscribe = payment.subscribe(listener)
        payment.set_amount(50)
        listener.assert_called_once()
        unsubscribe()
        payment.set_amount(60)
        listener.assert_called_once()
