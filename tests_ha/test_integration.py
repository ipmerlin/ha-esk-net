"""Tests against actual HA classes in Linux CI; no live credentials."""

import unittest
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.esk_net import async_setup_entry, async_unload_entry
from custom_components.esk_net.config_flow import EskConfigFlow
from custom_components.esk_net.coordinator import EskCoordinator
from custom_components.esk_net.parser import (
    AccountData,
    ActiveService,
    AuthenticationError,
    ParseError,
)
from custom_components.esk_net.sensor import SENSORS, EskSensor, EskServiceSensor, service_map
from custom_components.esk_net.sensor import async_setup_entry as setup_sensors

DATA = AccountData("001", Decimal("120.50"), 7, "PRO100", Decimal("537"))


class SensorTests(unittest.TestCase):
    def test_individual_service_price_and_removal(self):
        coordinator = Mock(
            data=replace(DATA, active_services=(ActiveService("External IP", Decimal("400")),)),
            account="001",
            last_update_success=True,
        )
        key = next(iter(service_map(coordinator.data)))
        sensor = EskServiceSensor(coordinator, key, "External IP")
        self.assertEqual(sensor.name, "External IP")
        self.assertEqual(sensor.native_value, Decimal("400"))
        self.assertTrue(sensor.available)
        coordinator.data = replace(
            DATA, active_services=(ActiveService("External IP", Decimal("450")),)
        )
        self.assertEqual(sensor.native_value, Decimal("450"))
        coordinator.data = replace(DATA, active_services=())
        self.assertIsNone(sensor.native_value)
        self.assertFalse(sensor.available)

    def test_new_sensor_values_and_attributes(self):
        data = replace(
            DATA,
            total_monthly_price=Decimal("950"),
            active_services=(ActiveService("Test service", Decimal("400")),),
        )
        coordinator = Mock(data=data, account="001")
        sensors = {d.key: EskSensor(coordinator, d) for d in SENSORS}
        self.assertEqual(sensors["total_monthly_price"].native_value, Decimal("950"))
        self.assertEqual(sensors["tariff_price"].native_value, Decimal("537"))
        self.assertEqual(sensors["active_services"].native_value, 1)
        self.assertEqual(
            sensors["active_services"].extra_state_attributes,
            {"services": [{"name": "Test service", "monthly_price": 400.0}], "currency": "RUB"},
        )
        coordinator.data = DATA
        self.assertIsNone(sensors["active_services"].native_value)
        self.assertIsNone(sensors["active_services"].extra_state_attributes["services"])
        self.assertIsNone(sensors["total_monthly_price"].native_value)

    def test_empty_services(self):
        coordinator = Mock(data=replace(DATA, active_services=()), account="001")
        sensor = EskSensor(coordinator, next(d for d in SENSORS if d.key == "active_services"))
        self.assertEqual(sensor.native_value, 0)
        self.assertEqual(sensor.extra_state_attributes["services"], [])


class FlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_account(self):
        flow = EskConfigFlow()
        with (
            patch.object(flow, "_validate", AsyncMock(return_value=DATA)),
            patch.object(flow, "async_set_unique_id", AsyncMock()) as unique,
            patch.object(flow, "_abort_if_unique_id_configured"),
        ):
            result = await flow.async_step_user({"username": " login ", "password": "secret"})
        unique.assert_awaited_once_with("001")
        self.assertEqual(
            result["data"], {"username": "login", "password": "secret", "account": "001"}
        )

    async def test_form_errors(self):
        flow = EskConfigFlow()
        for error, expected in (
            (AuthenticationError(), "invalid_auth"),
            (ParseError(), "cannot_parse"),
        ):
            with (
                self.subTest(expected=expected),
                patch.object(flow, "_validate", AsyncMock(side_effect=error)),
                patch.object(flow, "async_show_form", Mock(return_value={})) as show,
            ):
                await flow.async_step_user({"username": "login", "password": "secret"})
                self.assertEqual(show.call_args.kwargs["errors"], {"base": expected})

    async def test_reauth_updates_existing_entry(self):
        flow = EskConfigFlow()
        entry = SimpleNamespace(data={"username": "old"})
        with (
            patch.object(flow, "_get_reauth_entry", return_value=entry),
            patch.object(flow, "_validate", AsyncMock(return_value=DATA)),
            patch.object(flow, "async_set_unique_id", AsyncMock()),
            patch.object(flow, "_abort_if_unique_id_mismatch") as mismatch,
            patch.object(flow, "async_update_reload_and_abort", return_value={}) as update,
            patch.object(flow, "async_create_entry") as create,
        ):
            await flow.async_step_reauth_confirm({"username": "new", "password": "secret"})
        mismatch.assert_called_once()
        create.assert_not_called()
        self.assertIs(update.call_args.args[0], entry)


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_services_discovered_after_setup(self):
        coordinator = Mock(data=DATA, account="001")
        entry = Mock(runtime_data=coordinator)
        add = Mock()
        await setup_sensors(Mock(), entry, add)
        add.reset_mock()
        coordinator.data = replace(
            DATA, active_services=(ActiveService("External IP", Decimal("400")),)
        )
        listener = coordinator.async_add_listener.call_args.args[0]
        listener()
        self.assertEqual(add.call_args.args[0][0].name, "External IP")
        listener()
        add.assert_called_once()

    async def test_setup_failure_detaches_session(self):
        session = Mock()
        entry = Mock(data={"username": "login", "password": "secret"})
        coordinator = Mock(
            async_config_entry_first_refresh=AsyncMock(side_effect=ConfigEntryNotReady)
        )
        with (
            patch("custom_components.esk_net.create_session", return_value=session),
            patch("custom_components.esk_net.EskCoordinator", return_value=coordinator),
            self.assertRaises(ConfigEntryNotReady),
        ):
            await async_setup_entry(Mock(), entry)
        session.detach.assert_called_once()

    async def test_setup_and_unload_callback(self):
        session = Mock()
        entry = Mock(data={"username": "login", "password": "secret"})
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(
                async_forward_entry_setups=AsyncMock(),
                async_unload_platforms=AsyncMock(return_value=True),
            )
        )
        coordinator = Mock(async_config_entry_first_refresh=AsyncMock())
        with (
            patch("custom_components.esk_net.create_session", return_value=session),
            patch("custom_components.esk_net.EskCoordinator", return_value=coordinator),
        ):
            self.assertTrue(await async_setup_entry(hass, entry))
        self.assertIs(entry.runtime_data, coordinator)
        session.detach.assert_not_called()
        self.assertTrue(await async_unload_entry(hass, entry))
        for call in entry.async_on_unload.call_args_list:
            call.args[0]()
        session.detach.assert_called_once()


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_account_mismatch_starts_reauth(self):
        coordinator = SimpleNamespace(
            account="different", client=SimpleNamespace(async_fetch=AsyncMock(return_value=DATA))
        )
        with self.assertRaises(ConfigEntryAuthFailed):
            await EskCoordinator._async_update_data(coordinator)

    async def test_parse_failure_marks_update_failed(self):
        coordinator = SimpleNamespace(
            account="001",
            client=SimpleNamespace(async_fetch=AsyncMock(side_effect=ParseError("Layout changed"))),
        )
        with self.assertRaises(UpdateFailed):
            await EskCoordinator._async_update_data(coordinator)

    async def test_successful_poll(self):
        coordinator = SimpleNamespace(
            account="001", client=SimpleNamespace(async_fetch=AsyncMock(return_value=DATA))
        )
        self.assertEqual(await EskCoordinator._async_update_data(coordinator), DATA)
