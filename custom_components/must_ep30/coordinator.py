"""DataUpdateCoordinator for the MUST EP30/EP3000 integration.

One coordinator per config entry. It knows nothing about ASCII vs. Modbus
-- it only calls ``client.async_fetch()`` on whichever
:class:`~.protocol.base.MustDeviceClient` the device profile constructed,
then runs the profile's optional ``compute_values`` hook (for
config-option-dependent derived sensors like ``battery_level``) before
storing the result as ``coordinator.data``.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from pymodbus.exceptions import ModbusException

from .const import CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL, DOMAIN, LOGGER, POLL_TIMEOUT
from .devices.models import DeviceProfile
from .protocol.base import MustDeviceClient, MustPollResult
from .protocol.exceptions import MustConnectionError, MustProtocolError


class MustEp30DataUpdateCoordinator(DataUpdateCoordinator[MustPollResult]):
    """Polls one MUST device and exposes the latest decoded values."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: MustDeviceClient,
        profile: DeviceProfile,
    ) -> None:
        self.client = client
        self.profile = profile
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN} ({entry.title})",
            config_entry=entry,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
            ),
            always_update=True,
        )

    async def async_connect_or_raise(self) -> None:
        """Open the transport, raising ConfigEntryNotReady on failure."""
        try:
            await self.client.async_connect()
        except MustConnectionError as err:
            raise ConfigEntryNotReady(
                f"Could not connect to {self.profile.model_name}: {err}"
            ) from err

    async def _async_update_data(self) -> MustPollResult:
        try:
            async with asyncio.timeout(POLL_TIMEOUT):
                result = await self.client.async_fetch()
        except (
            MustConnectionError,
            MustProtocolError,
            ModbusException,
            OSError,
            TimeoutError,
        ) as err:
            raise UpdateFailed(
                f"Error communicating with {self.profile.model_name}: {err}"
            ) from err

        if self.profile.compute_values is not None:
            try:
                extra = self.profile.compute_values(result, self.config_entry.options)
            except Exception:  # noqa: BLE001 - never let a derived-sensor bug kill the poll
                LOGGER.exception("Error computing derived values for %s", self.profile.model_name)
            else:
                result.values.update(extra)

        return result
