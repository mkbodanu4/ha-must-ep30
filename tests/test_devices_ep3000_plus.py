"""Unit tests for the EP3000 Plus device profile's register decoding."""

from __future__ import annotations

from custom_components.must_ep30.devices.ep3000_plus import (
    SENSORS,
    SYSTEM_FAULT_MAP,
    _charging_current,
    _compute_values,
    _register,
    _register_enum,
    _software_version,
)
from custom_components.must_ep30.protocol.base import MustPollResult


def _registers(overrides: dict[int, int]) -> list[int]:
    # 26 zero-filled registers (offsets 0-25), with overrides applied.
    values = [0] * 26
    for offset, value in overrides.items():
        values[offset] = value
    return values


def test_register_scaling() -> None:
    result = MustPollResult(values={}, raw={"registers": _registers({5: 2200})})
    assert _register(5, 0.1)(result) == 220.0


def test_register_returns_none_without_registers() -> None:
    result = MustPollResult(values={}, raw={})
    assert _register(5, 0.1)(result) is None


def test_register_enum_known_code() -> None:
    result = MustPollResult(values={}, raw={"registers": _registers({21: 7})})
    assert _register_enum(21, SYSTEM_FAULT_MAP)(result) == "over_load"


def test_register_enum_unknown_code_falls_back() -> None:
    # code 99 is not in SYSTEM_FAULT_MAP
    result = MustPollResult(values={}, raw={"registers": _registers({21: 99})})
    assert _register_enum(21, SYSTEM_FAULT_MAP)(result) == "unknown"


def test_software_version_format() -> None:
    result = MustPollResult(values={}, raw={"registers": _registers({1: 12345})})
    assert _software_version(result) == "166-0012345"


def test_charging_current_zeroed_when_backup_discharging() -> None:
    # work_state (offset 2) == 1 -> BACKUP -> force charging_current to 0
    result = MustPollResult(values={}, raw={"registers": _registers({2: 1, 15: 55})})
    assert _charging_current(result) == 0.0


def test_charging_current_normal_when_not_backup() -> None:
    result = MustPollResult(values={}, raw={"registers": _registers({2: 2, 15: 55})})
    assert _charging_current(result) == 5.5


def test_compute_values_battery_level_present() -> None:
    # work_state=2 (LINE), battery_voltage register 14 -> 27.2V,
    # charging_current register 15 -> above float current default (1.0A)
    result = MustPollResult(values={}, raw={"registers": _registers({2: 2, 14: 272, 15: 20})})
    computed = _compute_values(result, {})
    assert "battery_level" in computed
    assert 0.0 <= computed["battery_level"] <= 100.0


def test_compute_values_empty_without_registers() -> None:
    result = MustPollResult(values={}, raw={})
    assert _compute_values(result, {}) == {}


def test_all_sensor_keys_are_unique() -> None:
    keys = [description.key for description in SENSORS]
    assert len(keys) == len(set(keys))


def test_sensor_count_matches_original_script() -> None:
    # 23 register-mapped + 1 computed (battery_level) = 24, matching the
    # original ep3000_plus.py `sensors` list length.
    assert len(SENSORS) == 24


def test_regression_12v_system_battery_level_via_compute_values() -> None:
    """Same class of bug as EP30 Pro's, via the Modbus "battery" class
    register (offset 3) instead of the ASCII F command's nominal voltage.
    """
    # offset 2 = LINE (2) not required for this to reproduce the bug since
    # the fix applies to is_charging=False (discharge branch) too; use a
    # resting/not-charging state matching the original report.
    result = MustPollResult(
        values={}, raw={"registers": _registers({2: 3, 3: 12, 14: 136})}
    )  # work_state=STOP, battery class=12V, battery_voltage=13.6V
    computed = _compute_values(result, {})
    assert computed["battery_level"] == 100.0
