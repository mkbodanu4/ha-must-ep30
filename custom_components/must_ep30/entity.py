"""Shared entity base class for the MUST EP30/EP3000 integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import MustEp30DataUpdateCoordinator


class MustEp30Entity(CoordinatorEntity[MustEp30DataUpdateCoordinator]):
    """Base entity grouping all platform entities under one device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MustEp30DataUpdateCoordinator,
        description,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        entry = coordinator.config_entry
        entry_identifier = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{entry_identifier}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_identifier)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=coordinator.profile.model_name,
            sw_version=_software_version(coordinator),
        )


def _software_version(coordinator: MustEp30DataUpdateCoordinator) -> str | None:
    if coordinator.data is None:
        return None
    value = coordinator.data.values.get("software_version")
    return str(value) if value is not None else None
