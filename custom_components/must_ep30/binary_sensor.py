"""Binary sensor platform for the MUST EP30/EP3000 integration.

Generic: entities are created directly from the active device profile's
``binary_sensors`` descriptor tuple. The EP3000 Plus profile currently
defines none (matching the original project, which never exposed binary
sensors for that device), so this platform is a no-op for that profile.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import MustEp30DataUpdateCoordinator
from .devices.models import MustBinarySensorEntityDescription
from .entity import MustEp30Entity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors from the config entry's device profile."""
    coordinator: MustEp30DataUpdateCoordinator = entry.runtime_data
    async_add_entities(
        MustBinarySensor(coordinator, description)
        for description in coordinator.profile.binary_sensors
    )


class MustBinarySensor(MustEp30Entity, BinarySensorEntity):
    """Binary sensor entity driven by a MustBinarySensorEntityDescription.value_fn."""

    entity_description: MustBinarySensorEntityDescription

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
