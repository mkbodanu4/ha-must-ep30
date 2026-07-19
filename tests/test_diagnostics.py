"""Unit tests for config entry diagnostics."""

from __future__ import annotations

from homeassistant.components.diagnostics import REDACTED

from custom_components.must_ep30.diagnostics import async_get_config_entry_diagnostics
from custom_components.must_ep30.protocol.base import MustPollResult


class _FakeProfile:
    key = "ep3000_plus"
    model_name = "EP3000 Plus"


class _FakeCoordinator:
    def __init__(self) -> None:
        self.data = MustPollResult(values={"battery_voltage": 27.2}, raw={"registers": [1, 2]})
        self.profile = _FakeProfile()
        self.last_update_success = True


class _FakeEntry:
    data = {"device": "/dev/ttyUSB0", "host": "10.0.0.5", "profile": "ep3000_plus"}
    options = {"poll_interval": 10}


async def test_diagnostics_redacts_sensitive_fields() -> None:
    entry = _FakeEntry()
    entry.runtime_data = _FakeCoordinator()

    diagnostics = await async_get_config_entry_diagnostics(hass=None, entry=entry)

    assert diagnostics["entry_data"]["device"] == REDACTED
    assert diagnostics["entry_data"]["host"] == REDACTED
    assert diagnostics["entry_data"]["profile"] == "ep3000_plus"
    assert diagnostics["values"]["battery_voltage"] == 27.2
    assert diagnostics["raw"]["registers"] == [1, 2]
    assert diagnostics["profile"] == "ep3000_plus"
