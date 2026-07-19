"""Unit tests for the EP30 Pro device profile's computed sensors."""

from __future__ import annotations

from custom_components.must_ep30.devices.ep30_pro import (
    BINARY_SENSORS,
    SENSORS,
    _compute_values,
)
from custom_components.must_ep30.protocol.base import MustPollResult


def test_compute_output_power() -> None:
    result = MustPollResult(
        values={"rating_current": 10.0, "load_level": 50, "output_voltage": 230.0}, raw={}
    )
    computed = _compute_values(result, {})
    assert computed["output_power"] == 10.0 * 0.5 * 230.0


def test_compute_output_power_missing_inputs_omitted() -> None:
    result = MustPollResult(values={"rating_current": 10.0}, raw={})
    computed = _compute_values(result, {})
    assert "output_power" not in computed


def test_compute_battery_level_present_when_voltage_known() -> None:
    result = MustPollResult(
        values={"battery_voltage": 26.0, "is_charging": False, "charging_current": 0.0}, raw={}
    )
    computed = _compute_values(result, {})
    assert computed["battery_level"] == 100.0


def test_compute_charger_battery_voltage_adc_scaling() -> None:
    result = MustPollResult(values={"charging_value4": 255.0}, raw={})
    computed = _compute_values(result, {"adc_battery_voltage_max": 17.35})
    assert computed["charger_battery_voltage"] == 17.35


def test_compute_charger_battery_voltage_omitted_without_raw_value() -> None:
    result = MustPollResult(values={}, raw={})
    computed = _compute_values(result, {})
    assert "charger_battery_voltage" not in computed


def test_sensor_count_matches_original_script() -> None:
    assert len(SENSORS) == 21


def test_binary_sensor_count_matches_original_script() -> None:
    assert len(BINARY_SENSORS) == 8


def test_all_entity_keys_unique() -> None:
    sensor_keys = [d.key for d in SENSORS]
    binary_keys = [d.key for d in BINARY_SENSORS]
    assert len(sensor_keys) == len(set(sensor_keys))
    assert len(binary_keys) == len(set(binary_keys))


def test_utility_power_present_polarity() -> None:
    """flag==0 (no fail) -> power present == True; flag==1 -> False."""
    description = next(d for d in BINARY_SENSORS if d.key == "utility_power_present")

    present = MustPollResult(values={"utility_fail": 0}, raw={})
    failed = MustPollResult(values={"utility_fail": 1}, raw={})

    assert description.value_fn(present) is True
    assert description.value_fn(failed) is False


def test_regression_12v_system_battery_level_via_compute_values() -> None:
    """End-to-end reproduction of a real bug report: a 12V EP30 Pro read
    nominal_battery_voltage=12.0, battery_voltage=13.6, is_charging=False,
    with no options configured -- battery_level came out ~17.8% instead of
    ~100% because the (only) hardcoded defaults assumed a 24V bank.
    """
    result = MustPollResult(
        values={
            "nominal_battery_voltage": 12.0,
            "battery_voltage": 13.6,
            "is_charging": False,
        },
        raw={},
    )
    computed = _compute_values(result, {})
    assert computed["battery_level"] == 100.0
