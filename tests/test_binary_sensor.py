"""Unit tests for the generic binary_sensor platform's entity wiring."""

from __future__ import annotations

from custom_components.must_ep30.binary_sensor import MustBinarySensor
from custom_components.must_ep30.devices.models import MustBinarySensorEntityDescription
from custom_components.must_ep30.protocol.base import MustPollResult


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


def test_is_on_delegates_to_value_fn() -> None:
    description = MustBinarySensorEntityDescription(key="foo", value_fn=lambda r: r.values["foo"])
    coordinator = _FakeCoordinator(MustPollResult(values={"foo": True}, raw={}))
    entity = MustBinarySensor(coordinator, description)
    assert entity.is_on is True


def test_is_on_none_without_data() -> None:
    description = MustBinarySensorEntityDescription(key="foo", value_fn=lambda r: r.values["foo"])
    coordinator = _FakeCoordinator(None)
    entity = MustBinarySensor(coordinator, description)
    assert entity.is_on is None
