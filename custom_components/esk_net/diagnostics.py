"""Minimal diagnostics; never export account, credentials, cookies or HTML."""

from .const import CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    return {
        "update_interval_minutes": entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        "last_update_success": coordinator.last_update_success,
        "available_fields": [
            key
            for key in (
                "balance",
                "days_left",
                "tariff",
                "tariff_price",
                "total_monthly_price",
                "active_services",
            )
            if coordinator.data and getattr(coordinator.data, key) is not None
        ],
    }
