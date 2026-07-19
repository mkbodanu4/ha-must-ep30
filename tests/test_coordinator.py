"""Unit tests for MustEp30DataUpdateCoordinator's error mapping.

Exercises the key reliability improvement over the original scripts: I/O
failures must become `UpdateFailed` (entities go unavailable) instead of
crashing the process, and a bug in a device profile's `compute_values`
hook must not take down the whole poll cycle.
"""

from __future__ import annotations

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.must_ep30.const import DOMAIN
from custom_components.must_ep30.coordinator import MustEp30DataUpdateCoordinator
from custom_components.must_ep30.devices.models import BatteryCurveDefaults, DeviceProfile
from custom_components.must_ep30.protocol.base import MustDeviceClient, MustPollResult
from custom_components.must_ep30.protocol.exceptions import MustProtocolError


class _FakeClient(MustDeviceClient):
    def __init__(self, *, fail: bool = False, result: MustPollResult | None = None) -> None:
        self.fail = fail
        self.result = result or MustPollResult(values={"foo": 1}, raw={})

    async def async_connect(self) -> None:
        pass

    async def async_close(self) -> None:
        pass

    async def async_fetch(self) -> MustPollResult:
        if self.fail:
            raise MustProtocolError("boom")
        return self.result


def _make_profile(compute_values=None) -> DeviceProfile:
    return DeviceProfile(
        key="fake",
        model_name="Fake Device",
        connection_kinds=("serial",),
        client_factory=lambda hass, entry: _FakeClient(),
        sensors=(),
        binary_sensors=(),
        battery_curve_defaults=BatteryCurveDefaults(
            charge_float_current=1.0,
            charge_full_voltage=27.2,
            charge_boost_voltage=28.8,
            charge_empty_voltage=11.0,
            discharge_full_voltage=25.6,
            discharge_empty_voltage=11.0,
        ),
        compute_values=compute_values,
    )


def _make_entry(hass, options: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=options or {})
    entry.add_to_hass(hass)
    return entry


async def test_update_data_success(hass) -> None:
    entry = _make_entry(hass)
    profile = _make_profile()
    client = _FakeClient(result=MustPollResult(values={"foo": 42}, raw={}))
    coordinator = MustEp30DataUpdateCoordinator(hass, entry, client, profile)

    result = await coordinator._async_update_data()

    assert result.values["foo"] == 42


async def test_update_data_raises_update_failed_on_protocol_error(hass) -> None:
    entry = _make_entry(hass)
    profile = _make_profile()
    client = _FakeClient(fail=True)
    coordinator = MustEp30DataUpdateCoordinator(hass, entry, client, profile)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_compute_values_merged_into_result(hass) -> None:
    entry = _make_entry(hass)

    def compute(result: MustPollResult, options) -> dict:
        return {"derived": result.values["foo"] * 2}

    profile = _make_profile(compute_values=compute)
    client = _FakeClient(result=MustPollResult(values={"foo": 5}, raw={}))
    coordinator = MustEp30DataUpdateCoordinator(hass, entry, client, profile)

    result = await coordinator._async_update_data()

    assert result.values["derived"] == 10
    assert result.values["foo"] == 5


async def test_compute_values_exception_does_not_crash_poll(hass) -> None:
    entry = _make_entry(hass)

    def compute(result: MustPollResult, options) -> dict:
        raise ValueError("bug in compute_values")

    profile = _make_profile(compute_values=compute)
    client = _FakeClient(result=MustPollResult(values={"foo": 5}, raw={}))
    coordinator = MustEp30DataUpdateCoordinator(hass, entry, client, profile)

    result = await coordinator._async_update_data()

    assert result.values["foo"] == 5


async def test_poll_interval_from_options(hass) -> None:
    entry = _make_entry(hass, options={"poll_interval": 42})
    profile = _make_profile()
    client = _FakeClient()
    coordinator = MustEp30DataUpdateCoordinator(hass, entry, client, profile)

    assert coordinator.update_interval.total_seconds() == 42
