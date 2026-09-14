"""Read-only ESK cabinet sensors."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BASE_URL, DOMAIN

PARALLEL_UPDATES = 0
SENSORS = (
    SensorEntityDescription(
        key="balance",
        translation_key="balance",
        icon="mdi:wallet",
        native_unit_of_measurement="RUB",
        device_class=SensorDeviceClass.MONETARY,
    ),
    SensorEntityDescription(
        key="days_left",
        translation_key="days_left",
        icon="mdi:calendar-clock",
        native_unit_of_measurement="d",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(key="tariff", translation_key="tariff", icon="mdi:ethernet"),
    SensorEntityDescription(
        key="tariff_price",
        translation_key="tariff_price",
        icon="mdi:cash",
        native_unit_of_measurement="RUB",
        device_class=SensorDeviceClass.MONETARY,
    ),
    SensorEntityDescription(key="account", translation_key="account", icon="mdi:identifier"),
    SensorEntityDescription(
        key="total_monthly_price",
        translation_key="total_monthly_price",
        icon="mdi:cash-multiple",
        native_unit_of_measurement="RUB",
        device_class=SensorDeviceClass.MONETARY,
    ),
    SensorEntityDescription(
        key="active_services",
        translation_key="active_services",
        icon="mdi:format-list-bulleted",
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(EskSensor(entry.runtime_data, description) for description in SENSORS)


class EskSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, description):
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.account}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.account)},
            name=f"ЕСК {coordinator.account}",
            manufacturer="ЕСК",
            model="Личный кабинет",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=BASE_URL,
        )

    @property
    def native_value(self):
        if self.entity_description.key == "active_services":
            services = self.coordinator.data.active_services
            return len(services) if services is not None else None
        return getattr(self.coordinator.data, self.entity_description.key)

    @property
    def extra_state_attributes(self):
        if self.entity_description.key == "active_services":
            services = self.coordinator.data.active_services
            return {
                "services": [
                    {
                        "name": service.name,
                        "monthly_price": float(service.monthly_price)
                        if service.monthly_price is not None
                        else None,
                    }
                    for service in services
                ]
                if services is not None
                else None,
                "currency": "RUB",
            }
        if self.entity_description.key == "tariff":
            price = self.coordinator.data.tariff_price
            return {"monthly_price": str(price) if price is not None else None, "currency": "RUB"}
        return None
