"""Declarative device-profile model shared by both device families.

A :class:`DeviceProfile` bundles the client factory for one device family
with a declarative table of sensor/binary_sensor descriptions (an entity
description plus a ``value_fn`` that extracts/derives a value from a
:class:`~..protocol.base.MustPollResult`). ``sensor.py``/``binary_sensor.py``
iterate a profile's descriptions generically, so adding a new model (e.g.
EP3300) is a new ``devices/epXXXX.py`` module plus a ``PROFILE_REGISTRY``
entry -- no changes to the coordinator or platform files.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import BinarySensorEntityDescription
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.helpers.typing import StateType

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from ..protocol.base import MustDeviceClient, MustPollResult


@dataclass(frozen=True, kw_only=True)
class MustSensorEntityDescription(SensorEntityDescription):
    """Sensor description with a value extractor bound to a MustPollResult."""

    value_fn: Callable[[MustPollResult], StateType]


@dataclass(frozen=True, kw_only=True)
class MustBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Binary sensor description with a value extractor."""

    value_fn: Callable[[MustPollResult], bool | None]


@dataclass(frozen=True, kw_only=True)
class BatteryCurveDefaults:
    """Default voltage-curve thresholds for the computed battery_level sensor.

    These are battery-chemistry-dependent (lead-acid vs. LiFePO4 have very
    different voltage-to-SoC curves), so they are user-overridable via the
    options flow rather than hardcoded. These values are only the starting
    defaults shown in that form, carried over from the original project's
    ``configuration.example.yaml`` (written for a 24V lead-acid bank).
    """

    charge_float_current: float
    charge_full_voltage: float
    charge_boost_voltage: float
    charge_empty_voltage: float
    discharge_full_voltage: float
    discharge_empty_voltage: float


# The original ep30_pro_mqtt project's configuration.example.yaml documented
# both a 12V and a 24V lead-acid reference config, as commented-out
# alternates on the same keys (e.g. `full_voltage: 25.6  # 12.8`). Both
# reference points are reused here rather than only the 24V one.
#
# NOTE: the predecessor project's own "24V" reference used empty_voltage
# 11.0 for BOTH the 12V and 24V configs -- correct for a 6-cell 12V bank
# (1.75V/cell x 6 = 10.5V, close enough) but wrong for a 12-cell 24V bank,
# whose equivalent low-voltage cutoff is 1.75V/cell x 12 = 21V, not 11V.
# Fixed here rather than perpetuated.
_BATTERY_CURVE_12V = BatteryCurveDefaults(
    charge_float_current=6.0,
    charge_full_voltage=13.6,
    charge_boost_voltage=14.4,
    charge_empty_voltage=10.5,
    discharge_full_voltage=12.8,
    discharge_empty_voltage=10.5,
)

BATTERY_CURVE_24V = BatteryCurveDefaults(
    charge_float_current=1.0,
    charge_full_voltage=27.2,
    charge_boost_voltage=28.8,
    charge_empty_voltage=21.0,
    discharge_full_voltage=25.6,
    discharge_empty_voltage=21.0,
)


def battery_curve_defaults_for_nominal_voltage(
    nominal_voltage: float | None,
) -> BatteryCurveDefaults:
    """Pick starting calibration defaults from a device-reported nominal voltage.

    Both device profiles report a nameplate/nominal battery voltage at
    runtime (EP30 Pro's ``nominal_battery_voltage`` from the ``F`` command;
    EP3000 Plus's ``battery`` class register) -- using it avoids silently
    assuming every bank is 24V, which previously made the computed
    battery_level sensor badly wrong for 12V systems out of the box (e.g. a
    resting ~13.6V 12V bank read as ~18% instead of ~100%). The 12V/24V
    values themselves are the two lead-acid reference points above; anything
    else (e.g. 48V) is linearly scaled from whichever reference is closer.
    This is still only a starting point for lead-acid chemistry -- LiFePO4 or
    other chemistries need manual calibration via the options flow regardless
    (see README).
    """
    if nominal_voltage is None or nominal_voltage <= 0:
        return BATTERY_CURVE_24V

    if nominal_voltage <= 18:
        base, reference = _BATTERY_CURVE_12V, 12.0
    else:
        base, reference = BATTERY_CURVE_24V, 24.0

    scale = nominal_voltage / reference
    if scale == 1.0:
        return base

    return BatteryCurveDefaults(
        # A current threshold doesn't scale with bank voltage.
        charge_float_current=base.charge_float_current,
        charge_full_voltage=base.charge_full_voltage * scale,
        charge_boost_voltage=base.charge_boost_voltage * scale,
        charge_empty_voltage=base.charge_empty_voltage * scale,
        discharge_full_voltage=base.discharge_full_voltage * scale,
        discharge_empty_voltage=base.discharge_empty_voltage * scale,
    )


@dataclass(frozen=True, kw_only=True)
class DeviceProfile:
    """Everything needed to stand up one device family's client + entities."""

    key: str
    model_name: str
    connection_kinds: tuple[str, ...]
    client_factory: Callable[[HomeAssistant, ConfigEntry], MustDeviceClient]
    sensors: tuple[MustSensorEntityDescription, ...]
    binary_sensors: tuple[MustBinarySensorEntityDescription, ...] = ()
    battery_curve_defaults: BatteryCurveDefaults
    compute_values: Callable[[MustPollResult, Mapping[str, Any]], dict[str, StateType]] | None = (
        None
    )
    """Optional post-processing hook run by the coordinator after a
    successful fetch. Receives the raw poll result and the config entry's
    ``options`` mapping (poll interval, battery-curve thresholds, etc.) and
    returns extra derived values (e.g. ``battery_level``,
    ``charger_battery_voltage``) to merge into ``result.values`` before it
    becomes ``coordinator.data``. Kept separate from ``value_fn`` because
    those config-dependent values can't be derived from ``MustPollResult``
    alone.
    """
    nominal_voltage_fn: Callable[[MustPollResult], float | None] | None = None
    """Optional extractor for the device's own reported nominal/nameplate
    battery voltage (e.g. EP30 Pro's ``nominal_battery_voltage`` from the
    ``F`` command, or EP3000 Plus's ``battery`` class register). Used by
    ``compute_values`` and the options flow's battery-calibration step to
    pick sensible starting thresholds via
    ``battery_curve_defaults_for_nominal_voltage`` instead of always
    assuming a 24V bank.
    """


def battery_level_curve(
    *,
    voltage: float | None,
    is_charging: bool,
    charging_current: float | None,
    charge_float_current: float,
    charge_full_voltage: float,
    charge_boost_voltage: float,
    charge_empty_voltage: float,
    discharge_full_voltage: float,
    discharge_empty_voltage: float,
) -> float | None:
    """Piecewise battery-level (%) estimate from voltage and charge state.

    Ported from the original ``ep30_pro_mqtt`` project, which computed this
    with near-identical formulas in ``mqtt.py`` (lines 586-602) and
    ``ep3000_plus.py`` (lines 450-479), gated on a protocol-specific
    "is charging" signal (the ASCII protocol's ``D`` command ACK flag vs.
    the Modbus ``work_state`` register). This shared implementation is
    called by both ``devices/ep30_pro.py`` and ``devices/ep3000_plus.py``
    so the curve only needs to be gotten right once. Unlike the original,
    the result is clamped to [0, 100] -- a battery-percentage sensor should
    never report outside that range even at extreme edge voltages.
    """
    if voltage is None:
        return None

    if is_charging and charging_current is not None and charging_current > charge_float_current:
        if voltage > charge_full_voltage:
            span = charge_boost_voltage - charge_full_voltage
            level = 95.0 + (voltage - charge_full_voltage) / span * 5.0 if span else 95.0
        else:
            span = charge_full_voltage - charge_empty_voltage
            level = (voltage - charge_empty_voltage) / span * 95.0 if span else 0.0
    else:
        if voltage > discharge_full_voltage:
            return 100.0
        span = discharge_full_voltage - discharge_empty_voltage
        level = (voltage - discharge_empty_voltage) / span * 100.0 if span else 0.0

    return max(0.0, min(100.0, level))
