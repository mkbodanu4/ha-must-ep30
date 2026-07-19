"""The MUST EP30/EP3000 integration."""

from __future__ import annotations

import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_PROFILE
from .coordinator import MustEp30DataUpdateCoordinator
from .devices import get_profile

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

type MustConfigEntry = ConfigEntry[MustEp30DataUpdateCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: MustConfigEntry) -> bool:
    """Set up MUST EP30/EP3000 from a config entry."""
    profile = get_profile(entry.data[CONF_PROFILE])
    client = profile.client_factory(hass, entry)

    coordinator = MustEp30DataUpdateCoordinator(hass, entry, client, profile)
    try:
        await coordinator.async_connect_or_raise()
        await coordinator.async_config_entry_first_refresh()

        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except (Exception, asyncio.CancelledError):
        await client.async_close()
        raise

    return True


async def async_unload_entry(hass: HomeAssistant, entry: MustConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.client.async_close()
    return unloaded
