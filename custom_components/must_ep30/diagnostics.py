"""Diagnostics support for the MUST EP30/EP3000 integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_DEVICE_PATH, CONF_HOST
from .coordinator import MustEp30DataUpdateCoordinator

TO_REDACT = {CONF_HOST, CONF_DEVICE_PATH}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    Includes the last raw poll result (register list / decoded ASCII
    fields) so a bug report can show exactly what the device returned --
    useful given neither protocol carries a checksum, so "the sensor shows
    a garbage value" reports are otherwise hard to diagnose remotely.
    """
    coordinator: MustEp30DataUpdateCoordinator = entry.runtime_data
    data = coordinator.data

    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "profile": coordinator.profile.key,
        "last_update_success": coordinator.last_update_success,
        "values": dict(data.values) if data else None,
        "raw": dict(data.raw) if data else None,
    }
