"""Sensor platform for the MUST EP30/EP3000 integration.

Generic: entities are created directly from the active device profile's
``sensors`` descriptor tuple (see ``devices/models.py``), so adding a new
device profile never requires touching this file.
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import MustEp30DataUpdateCoordinator
from .devices.models import MustSensorEntityDescription
from .entity import MustEp30Entity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from the config entry's device profile."""
    coordinator: MustEp30DataUpdateCoordinator = entry.runtime_data
    async_add_entities(
        MustSensor(coordinator, description) for description in coordinator.profile.sensors
    )


class MustSensor(MustEp30Entity, SensorEntity):
    """Sensor entity driven by a MustSensorEntityDescription.value_fn."""

    entity_description: MustSensorEntityDescription

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
