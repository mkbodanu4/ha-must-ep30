"""Shared pytest fixtures for the MUST EP30/EP3000 test suite."""

from __future__ import annotations

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make custom_components/must_ep30 importable inside the test hass."""
    yield


def make_q1_response(
    *,
    input_voltage: str = "220.0",
    fault_voltage: str = "220.0",
    output_voltage: str = "230.0",
    load_level: str = "025",
    output_frequency: str = "50.0",
    battery_voltage: str = "27.2",
    temp_field: str = "25.3",
    utility_fail: str = "0",
    battery_low: str = "0",
    working_status_code: int = 30,
    ups_failed: str = "0",
    ups_type: str = "1",
    test_in_progress: str = "0",
    shutdown_active: str = "0",
    beeper_on: str = "0",
) -> bytes:
    """Build a synthetic Q1 response matching protocol/ascii_serial.py's
    ``_parse_q1`` slice offsets (in turn ported from mqtt.py):

    data[1:6]=input_voltage data[7:12]=fault_voltage data[13:18]=output_voltage
    data[19:22]=load_level data[23:27]=output_frequency data[28:32]=battery_voltage
    data[33:37]=temp_field data[38]=utility_fail data[39]=battery_low
    data[40]=working_status data[41]=ups_failed data[42]=ups_type
    data[43]=test_in_progress data[44]=shutdown_active data[45]=beeper_on

    ``temp_field`` is 4 chars: the first char's ASCII digit value * 10,
    plus the remaining 3 chars parsed as a float, e.g. "25.3" -> 2*10 +
    5.3 = 25.3 (the BCD-like encoding fixed by bugfix #1).
    """
    buf = list(" " * 46)
    buf[0] = "("
    buf[1:6] = input_voltage.ljust(5)[:5]
    buf[7:12] = fault_voltage.ljust(5)[:5]
    buf[13:18] = output_voltage.ljust(5)[:5]
    buf[19:22] = load_level.ljust(3)[:3]
    buf[23:27] = output_frequency.ljust(4)[:4]
    buf[28:32] = battery_voltage.ljust(4)[:4]
    buf[33:37] = temp_field.ljust(4)[:4]
    buf[38] = utility_fail
    buf[39] = battery_low
    buf[40] = chr(working_status_code)
    buf[41] = ups_failed
    buf[42] = ups_type
    buf[43] = test_in_progress
    buf[44] = shutdown_active
    buf[45] = beeper_on
    return ("".join(buf) + "\r").encode("utf-8")


def make_f_response(
    *,
    rating_voltage: str = "220.0",
    rating_current: str = "10.0",
    nominal_battery_voltage: str = "24.00",
    nominal_frequency: str = "50.0",
) -> bytes:
    """Build a synthetic F response: data[1:6],[7:10],[11:16],[17:21]."""
    buf = list(" " * 21)
    buf[0] = "#"
    buf[1:6] = rating_voltage.ljust(5)[:5]
    buf[7:10] = rating_current.ljust(3)[:3]
    buf[11:16] = nominal_battery_voltage.ljust(5)[:5]
    buf[17:21] = nominal_frequency.ljust(4)[:4]
    return ("".join(buf) + "\r").encode("utf-8")
