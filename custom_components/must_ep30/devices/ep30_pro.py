"""EP30 Pro device profile: ASCII serial protocol.

Sensor/binary_sensor descriptions map 1:1 onto the fields decoded by
``protocol/ascii_serial.py``. Three sensors are computed here rather than
read directly, because they need config-entry options (battery-curve
thresholds, ADC scaling max) that the protocol client itself doesn't have
access to: ``output_power``, ``battery_level``, and
``charger_battery_voltage``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.helpers.typing import StateType

from ..const import (
    CONF_ADC_BATTERY_VOLTAGE_MAX,
    CONF_CHARGE_BOOST_VOLTAGE,
    CONF_CHARGE_EMPTY_VOLTAGE,
    CONF_CHARGE_FLOAT_CURRENT,
    CONF_CHARGE_FULL_VOLTAGE,
    CONF_DEVICE_PATH,
    CONF_DISCHARGE_EMPTY_VOLTAGE,
    CONF_DISCHARGE_FULL_VOLTAGE,
    CONNECTION_SERIAL,
    DEFAULT_ADC_BATTERY_VOLTAGE_MAX,
    PROFILE_EP30_PRO,
)
from ..protocol.ascii_serial import AsciiSerialClient
from .models import (
    BATTERY_CURVE_24V,
    DeviceProfile,
    MustBinarySensorEntityDescription,
    MustSensorEntityDescription,
    battery_curve_defaults_for_nominal_voltage,
    battery_level_curve,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from ..protocol.base import MustDeviceClient, MustPollResult


def _value(key: str):
    def _get(result: MustPollResult) -> StateType:
        return result.values.get(key)

    return _get


def _flag_is(key: str, expected: int):
    def _get(result: MustPollResult) -> bool | None:
        value = result.values.get(key)
        if value is None:
            return None
        return value == expected

    return _get


def _flag_is_not(key: str, excluded: int):
    def _get(result: MustPollResult) -> bool | None:
        value = result.values.get(key)
        if value is None:
            return None
        return value != excluded

    return _get


def _nominal_voltage(result: MustPollResult) -> float | None:
    return result.values.get("nominal_battery_voltage")


def _compute_values(result: MustPollResult, options: Mapping[str, Any]) -> dict[str, StateType]:
    values = result.values
    computed: dict[str, StateType] = {}

    rating_current = values.get("rating_current")
    load_level = values.get("load_level")
    output_voltage = values.get("output_voltage")
    if rating_current is not None and load_level is not None and output_voltage is not None:
        computed["output_power"] = rating_current * (load_level / 100.0) * output_voltage

    battery_voltage = values.get("battery_voltage")
    if battery_voltage is not None:
        # Pick starting defaults from the device's own nominal-voltage
        # reading (falls back to the static 24V-bank defaults if the F
        # command hasn't succeeded yet this cycle) -- see
        # battery_curve_defaults_for_nominal_voltage()'s docstring for why:
        # otherwise every 12V system's battery_level was badly wrong.
        curve_defaults = battery_curve_defaults_for_nominal_voltage(_nominal_voltage(result))
        computed["battery_level"] = battery_level_curve(
            voltage=battery_voltage,
            is_charging=bool(values.get("is_charging", False)),
            charging_current=values.get("charging_current"),
            charge_float_current=options.get(
                CONF_CHARGE_FLOAT_CURRENT, curve_defaults.charge_float_current
            ),
            charge_full_voltage=options.get(
                CONF_CHARGE_FULL_VOLTAGE, curve_defaults.charge_full_voltage
            ),
            charge_boost_voltage=options.get(
                CONF_CHARGE_BOOST_VOLTAGE, curve_defaults.charge_boost_voltage
            ),
            charge_empty_voltage=options.get(
                CONF_CHARGE_EMPTY_VOLTAGE, curve_defaults.charge_empty_voltage
            ),
            discharge_full_voltage=options.get(
                CONF_DISCHARGE_FULL_VOLTAGE, curve_defaults.discharge_full_voltage
            ),
            discharge_empty_voltage=options.get(
                CONF_DISCHARGE_EMPTY_VOLTAGE, curve_defaults.discharge_empty_voltage
            ),
        )

    charging_value4 = values.get("charging_value4")
    if charging_value4 is not None:
        adc_max = options.get(CONF_ADC_BATTERY_VOLTAGE_MAX, DEFAULT_ADC_BATTERY_VOLTAGE_MAX)
        computed["charger_battery_voltage"] = (adc_max * charging_value4) / 255

    return computed


def _client_factory(hass: HomeAssistant, entry: ConfigEntry) -> MustDeviceClient:
    return AsciiSerialClient(device_path=entry.data[CONF_DEVICE_PATH])


SENSORS: tuple[MustSensorEntityDescription, ...] = (
    MustSensorEntityDescription(
        key="rating_voltage",
        translation_key="rating_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_value("rating_voltage"),
    ),
    MustSensorEntityDescription(
        key="rating_current",
        translation_key="rating_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_value("rating_current"),
    ),
    MustSensorEntityDescription(
        key="nominal_battery_voltage",
        translation_key="nominal_battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_value("nominal_battery_voltage"),
    ),
    MustSensorEntityDescription(
        key="nominal_frequency",
        translation_key="nominal_frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_value("nominal_frequency"),
    ),
    MustSensorEntityDescription(
        key="input_voltage",
        translation_key="input_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("input_voltage"),
    ),
    MustSensorEntityDescription(
        key="fault_voltage",
        translation_key="fault_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("fault_voltage"),
    ),
    MustSensorEntityDescription(
        key="output_voltage",
        translation_key="output_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("output_voltage"),
    ),
    MustSensorEntityDescription(
        key="load_level",
        translation_key="load_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("load_level"),
    ),
    MustSensorEntityDescription(
        key="output_frequency",
        translation_key="output_frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("output_frequency"),
    ),
    MustSensorEntityDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_value("battery_voltage"),
    ),
    MustSensorEntityDescription(
        key="ups_temperature",
        translation_key="inverter_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        # The original script omitted state_class here; adding it is a
        # deliberate improvement so HA's long-term statistics cover it.
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("ups_temperature"),
    ),
    MustSensorEntityDescription(
        key="working_status",
        translation_key="working_status",
        # Deliberately NOT device_class=ENUM: only ASCII code 30
        # ("battery_priority") is empirically validated, so this can
        # legitimately emit "unknown_code_N" for the other 5 documented
        # states, which would violate ENUM's static-options contract.
        value_fn=_value("working_status"),
    ),
    MustSensorEntityDescription(
        key="fault_state",
        translation_key="fault_state",
        value_fn=_value("fault_state"),
    ),
    MustSensorEntityDescription(
        key="charging_current",
        translation_key="battery_charging_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("charging_current"),
    ),
    MustSensorEntityDescription(
        key="charger_battery_voltage",
        translation_key="charger_battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_value("charger_battery_voltage"),
    ),
    MustSensorEntityDescription(
        key="charging_value1",
        translation_key="charger_value1",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_value("charging_value1"),
    ),
    MustSensorEntityDescription(
        key="charging_value2",
        translation_key="charger_value2",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_value("charging_value2"),
    ),
    MustSensorEntityDescription(
        key="charging_value3",
        translation_key="charger_value3",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_value("charging_value3"),
    ),
    MustSensorEntityDescription(
        key="charging_value4",
        translation_key="charger_value4",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_value("charging_value4"),
    ),
    MustSensorEntityDescription(
        key="battery_level",
        translation_key="battery_level",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_value("battery_level"),
    ),
    MustSensorEntityDescription(
        key="output_power",
        translation_key="output_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_value("output_power"),
    ),
)

BINARY_SENSORS: tuple[MustBinarySensorEntityDescription, ...] = (
    MustBinarySensorEntityDescription(
        key="utility_power_present",
        translation_key="utility_power_present",
        device_class=BinarySensorDeviceClass.POWER,
        # Original entity was misleadingly named "Utility Fail (Immediate)"
        # while already reporting the inverted (correct) polarity -- ON
        # means utility power IS present (flag != 1). Renamed for clarity,
        # polarity preserved.
        value_fn=_flag_is_not("utility_fail", 1),
    ),
    MustBinarySensorEntityDescription(
        key="battery_low",
        translation_key="battery_low",
        device_class=BinarySensorDeviceClass.BATTERY,
        value_fn=_flag_is("battery_low", 1),
    ),
    MustBinarySensorEntityDescription(
        key="ups_failed",
        translation_key="ups_failed",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_flag_is("ups_failed", 1),
    ),
    MustBinarySensorEntityDescription(
        key="ups_type",
        translation_key="line_interactive_type",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_flag_is("ups_type", 1),
    ),
    MustBinarySensorEntityDescription(
        key="test_in_progress",
        translation_key="test_in_progress",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_flag_is("test_in_progress", 1),
    ),
    MustBinarySensorEntityDescription(
        key="shutdown_active",
        translation_key="shutdown_active",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_flag_is("shutdown_active", 1),
    ),
    MustBinarySensorEntityDescription(
        key="beeper_on",
        translation_key="beeper_on",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_flag_is("beeper_on", 1),
    ),
    MustBinarySensorEntityDescription(
        key="is_charging",
        translation_key="charger_action",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=_value("is_charging"),
    ),
)

EP30_PRO_PROFILE = DeviceProfile(
    key=PROFILE_EP30_PRO,
    model_name="EP30 Pro",
    connection_kinds=(CONNECTION_SERIAL,),
    client_factory=_client_factory,
    sensors=SENSORS,
    binary_sensors=BINARY_SENSORS,
    battery_curve_defaults=BATTERY_CURVE_24V,
    compute_values=_compute_values,
    nominal_voltage_fn=_nominal_voltage,
)
