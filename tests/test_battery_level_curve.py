"""Unit tests for the shared battery_level_curve() function.

Formula shape ported from the original ep30_pro_mqtt project's
mqtt.py (lines 586-602) / ep3000_plus.py (lines 450-479); see
devices/models.py for the shared implementation both device profiles
call into.
"""

from __future__ import annotations

from custom_components.must_ep30.devices.models import (
    battery_curve_defaults_for_nominal_voltage,
    battery_level_curve,
)

CURVE_KWARGS = dict(
    charge_float_current=1.0,
    charge_full_voltage=27.2,
    charge_boost_voltage=28.8,
    charge_empty_voltage=11.0,
    discharge_full_voltage=25.6,
    discharge_empty_voltage=11.0,
)


def test_none_voltage_returns_none() -> None:
    assert (
        battery_level_curve(voltage=None, is_charging=False, charging_current=None, **CURVE_KWARGS)
        is None
    )


def test_discharging_above_full_voltage_is_100_percent() -> None:
    level = battery_level_curve(
        voltage=26.0, is_charging=False, charging_current=None, **CURVE_KWARGS
    )
    assert level == 100.0


def test_discharging_at_empty_voltage_is_zero_percent() -> None:
    level = battery_level_curve(
        voltage=11.0, is_charging=False, charging_current=0.0, **CURVE_KWARGS
    )
    assert level == 0.0


def test_discharging_midpoint() -> None:
    # midpoint between empty (11.0) and full (25.6) -> 50%
    voltage = (11.0 + 25.6) / 2
    level = battery_level_curve(
        voltage=voltage, is_charging=False, charging_current=0.0, **CURVE_KWARGS
    )
    assert level == 50.0


def test_charging_below_float_current_is_treated_as_discharging_curve() -> None:
    # is_charging=True but current below the float threshold -> falls
    # through to the discharge curve, matching the original's branching.
    level = battery_level_curve(
        voltage=26.0, is_charging=True, charging_current=0.5, **CURVE_KWARGS
    )
    assert level == 100.0


def test_charging_above_full_voltage_scales_into_95_to_100_band() -> None:
    level = battery_level_curve(
        voltage=28.0, is_charging=True, charging_current=2.0, **CURVE_KWARGS
    )
    assert 95.0 < level < 100.0


def test_charging_at_boost_voltage_is_100_percent() -> None:
    level = battery_level_curve(
        voltage=28.8, is_charging=True, charging_current=2.0, **CURVE_KWARGS
    )
    assert level == 100.0


def test_result_is_clamped_to_0_100() -> None:
    # Voltage far below empty -> would go negative without clamping.
    level = battery_level_curve(
        voltage=0.0, is_charging=False, charging_current=None, **CURVE_KWARGS
    )
    assert level == 0.0

    level_high = battery_level_curve(
        voltage=999.0, is_charging=True, charging_current=2.0, **CURVE_KWARGS
    )
    assert level_high == 100.0


# battery_curve_defaults_for_nominal_voltage() -- regression coverage for a
# real-world bug report: a 12V system's battery_level computed as ~18% for a
# resting 13.6V battery, because the (only) hardcoded defaults were tuned
# for a 24V bank. See devices/ep30_pro.py's diagnostics dump in that report:
# nominal_battery_voltage=12.0, battery_voltage=13.6, is_charging=False.


def test_defaults_none_nominal_voltage_falls_back_to_24v() -> None:
    defaults = battery_curve_defaults_for_nominal_voltage(None)
    assert defaults.discharge_full_voltage == 25.6
    assert defaults.discharge_empty_voltage == 21.0


def test_defaults_zero_or_negative_nominal_voltage_falls_back_to_24v() -> None:
    assert battery_curve_defaults_for_nominal_voltage(0).discharge_full_voltage == 25.6
    assert battery_curve_defaults_for_nominal_voltage(-5).discharge_full_voltage == 25.6


def test_defaults_for_12v_system() -> None:
    defaults = battery_curve_defaults_for_nominal_voltage(12.0)
    assert defaults.discharge_full_voltage == 12.8
    assert defaults.discharge_empty_voltage == 10.5
    assert defaults.charge_full_voltage == 13.6
    assert defaults.charge_boost_voltage == 14.4
    assert defaults.charge_float_current == 6.0


def test_defaults_for_24v_system() -> None:
    defaults = battery_curve_defaults_for_nominal_voltage(24.0)
    assert defaults.discharge_full_voltage == 25.6
    # 12-cell lead-acid bank: 1.75V/cell x 12 = 21V, not the 11V the
    # predecessor project's own "24V" reference config used (a bug there,
    # not perpetuated here -- see BATTERY_CURVE_24V's comment).
    assert defaults.discharge_empty_voltage == 21.0
    assert defaults.charge_float_current == 1.0


def test_defaults_scale_for_48v_system() -> None:
    # No 48V reference exists, so it's linearly scaled from the 24V one.
    defaults = battery_curve_defaults_for_nominal_voltage(48.0)
    assert defaults.discharge_full_voltage == 51.2  # 25.6 * 2
    assert defaults.discharge_empty_voltage == 42.0  # 21.0 * 2
    # A current threshold must not scale with bank voltage.
    assert defaults.charge_float_current == 1.0


def test_regression_12v_resting_battery_reads_near_full_not_18_percent() -> None:
    """Reproduces the exact reported bug: a 12V bank misread as ~18%."""
    defaults = battery_curve_defaults_for_nominal_voltage(12.0)
    level = battery_level_curve(
        voltage=13.6,
        is_charging=False,
        charging_current=None,
        charge_float_current=defaults.charge_float_current,
        charge_full_voltage=defaults.charge_full_voltage,
        charge_boost_voltage=defaults.charge_boost_voltage,
        charge_empty_voltage=defaults.charge_empty_voltage,
        discharge_full_voltage=defaults.discharge_full_voltage,
        discharge_empty_voltage=defaults.discharge_empty_voltage,
    )
    assert level == 100.0

    # The bug as originally reported: using the 24V defaults regardless of
    # the device's actual 12V nominal voltage.
    wrong_defaults = battery_curve_defaults_for_nominal_voltage(24.0)
    wrong_level = battery_level_curve(
        voltage=13.6,
        is_charging=False,
        charging_current=None,
        charge_float_current=wrong_defaults.charge_float_current,
        charge_full_voltage=wrong_defaults.charge_full_voltage,
        charge_boost_voltage=wrong_defaults.charge_boost_voltage,
        charge_empty_voltage=wrong_defaults.charge_empty_voltage,
        discharge_full_voltage=wrong_defaults.discharge_full_voltage,
        discharge_empty_voltage=wrong_defaults.discharge_empty_voltage,
    )
    # 13.6V read against 24V-bank thresholds (full=25.6V, empty=21.0V) is
    # below even "empty" for a 24V bank, clamped to 0% -- still clearly
    # wrong, just a different wrong number than before the empty_voltage
    # fix (was 17.8%, using the previously-buggy 11.0V empty threshold).
    assert wrong_level == 0.0
