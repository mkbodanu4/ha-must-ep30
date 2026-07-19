"""Unit tests for the generic sensor platform's entity wiring."""

from __future__ import annotations

from custom_components.must_ep30.devices.models import MustSensorEntityDescription
from custom_components.must_ep30.protocol.base import MustPollResult
from custom_components.must_ep30.sensor import MustSensor


class _FakeEntry:
    unique_id = "test-unique-id"
    entry_id = "test-entry-id"
    title = "Test Device"


class _FakeProfile:
    model_name = "Test Model"


class _FakeCoordinator:
    def __init__(self, data: MustPollResult | None) -> None:
        self.data = data
        self.config_entry = _FakeEntry()
        self.profile = _FakeProfile()


def test_native_value_delegates_to_value_fn() -> None:
    description = MustSensorEntityDescription(key="foo", value_fn=lambda r: r.values["foo"])
    coordinator = _FakeCoordinator(MustPollResult(values={"foo": 123}, raw={}))
    entity = MustSensor(coordinator, description)
    assert entity.native_value == 123


def test_native_value_none_without_data() -> None:
    description = MustSensorEntityDescription(key="foo", value_fn=lambda r: r.values["foo"])
    coordinator = _FakeCoordinator(None)
    entity = MustSensor(coordinator, description)
    assert entity.native_value is None


def test_unique_id_derived_from_entry_and_key() -> None:
    description = MustSensorEntityDescription(key="battery_voltage", value_fn=lambda r: 1)
    coordinator = _FakeCoordinator(MustPollResult(values={}, raw={}))
    entity = MustSensor(coordinator, description)
    assert entity.unique_id == "test-unique-id_battery_voltage"


def test_device_info_groups_under_entry() -> None:
    description = MustSensorEntityDescription(key="foo", value_fn=lambda r: 1)
    coordinator = _FakeCoordinator(MustPollResult(values={}, raw={}))
    entity = MustSensor(coordinator, description)
    assert entity.device_info["model"] == "Test Model"
    assert entity.device_info["name"] == "Test Device"
