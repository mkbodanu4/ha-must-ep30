"""EP3000 Plus device profile: Modbus holding-register block 30000-30026.

Register offsets, multipliers, and enum tables are ported verbatim from
the original ``ep30_pro_mqtt`` project's ``ep3000_plus.py`` (the
``sensors`` list) -- this is the field-tested ground truth, independently
re-derived rather than reused from ``mukaschultze/ha-must-inverter``,
whose own register map is documented (issue #112) to produce garbled
reads against real EP3000 Plus hardware.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

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
    CONF_CHARGE_BOOST_VOLTAGE,
    CONF_CHARGE_EMPTY_VOLTAGE,
    CONF_CHARGE_FLOAT_CURRENT,
    CONF_CHARGE_FULL_VOLTAGE,
    CONF_CONNECTION_KIND,
    CONF_DEVICE_PATH,
    CONF_DISCHARGE_EMPTY_VOLTAGE,
    CONF_DISCHARGE_FULL_VOLTAGE,
    CONF_HOST,
    CONF_PORT,
    CONF_SLAVE_ID,
    CONNECTION_SERIAL,
    CONNECTION_TCP,
    CONNECTION_UDP,
    DEFAULT_MODBUS_SLAVE_ID,
    LOGGER,
    PROFILE_EP3000_PLUS,
)
from ..protocol.modbus import ModbusClient
from .models import (
    BATTERY_CURVE_24V,
    DeviceProfile,
    MustSensorEntityDescription,
    battery_curve_defaults_for_nominal_voltage,
    battery_level_curve,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from ..protocol.base import MustDeviceClient, MustPollResult

MACHINE_TYPE_MAP: dict[int, str] = {
    0: "ep2000_pro",
    1: "unspecified",
    2: "pv2000_pro",
    3: "ep3300",
}

WORK_STATE_MAP: dict[int, str] = {
    0: "self_check",
    1: "backup",
    2: "line",
    3: "stop",
    4: "charger",
    5: "soft_start",
    6: "power_off",
    7: "standby",
    8: "debug",
}

BUZZER_STATE_MAP: dict[int, str] = {0: "normal", 1: "silence"}

SYSTEM_FAULT_MAP: dict[int, str] = {
    0: "ok",
    1: "fan_error",
    2: "over_temperature",
    3: "battery_voltage_too_high",
    4: "battery_voltage_too_low",
    5: "short",
    6: "inverter_output_voltage_high",
    7: "over_load",
    11: "main_relay_failed",
    28: "rated_load_recognition_failed",
    41: "grid_voltage_low",
    42: "grid_voltage_high",
    43: "grid_under_frequency",
    44: "grid_over_frequency",
    51: "over_current",
    58: "output_voltage_low",
}

SYSTEM_ALARM_MAP: dict[int, str] = {
    0: "ok",
    1: "inverter_over_temperature",
    2: "battery_over_temperature",
    3: "battery_voltage_too_high",
    4: "battery_voltage_too_low",
    5: "over_load",
}

CHARGE_STAGE_MAP: dict[int, str] = {0: "cc", 1: "cv", 2: "fv"}
GRID_CHARGE_FLAG_MAP: dict[int, str] = {0: "grid_no_charge", 1: "grid_charge"}
GRID_STATE_MAP: dict[int, str] = {0: "disconnected", 1: "connected", 2: "warning"}

# Work states in which registers[15] (BatteryCurrent) does NOT reflect a
# real charging current -- ported verbatim from ep3000_plus.py's
# `if result.registers[2] == 1: charging_current = 0` special case.
_WORK_STATE_BACKUP = 1
_WORK_STATE_LINE = 2


def _registers(result: MustPollResult) -> list[int] | None:
    registers = result.raw.get("registers")
    return registers if registers else None


def _register(offset: int, multiplier: float = 1.0):
    def _value(result: MustPollResult) -> StateType:
        registers = _registers(result)
        if registers is None:
            return None
        return registers[offset] * multiplier

    return _value


def _enum_options(mapping: dict[int, str]) -> list[str]:
    # SensorDeviceClass.ENUM requires `native_value` to always be a member
    # of a static `options` list, which rules out a dynamic
    # "unknown_code_N" fallback (unlike the EP30 Pro ASCII protocol's
    # working_status, which is a plain string sensor for this reason).
    # These register tables come from the vendor's own decompiled enum
    # definitions (not reverse-engineered guesses), so they should be
    # complete, but a single static "unknown" bucket covers any reserved
    # or undocumented code defensively.
    return sorted({*mapping.values(), "unknown"})


def _register_enum(offset: int, mapping: dict[int, str]):
    def _value(result: MustPollResult) -> StateType:
        registers = _registers(result)
        if registers is None:
            return None
        code = registers[offset]
        if code not in mapping:
            LOGGER.debug("Unmapped EP3000 Plus register value %s at offset %s", code, offset)
            return "unknown"
        return mapping[code]

    return _value


def _software_version(result: MustPollResult) -> StateType:
    registers = _registers(result)
    if registers is None:
        return None
    # Verbatim port of the original's bare-concatenation format. The
    # decompiled C# reference (Ep3300M.txt/Ep3300TlvM.txt) suggests a
    # dash-formatted "166-00XXX-YY" variant instead -- unconfirmed on
    # plain EP3000 Plus firmware, see README open items before changing.
    return f"166-00{registers[1]}"


def _charging_current(result: MustPollResult) -> StateType:
    registers = _registers(result)
    if registers is None:
        return None
    if registers[2] == _WORK_STATE_BACKUP:
        return 0.0
    return registers[15] * 0.1


def _nominal_voltage(result: MustPollResult) -> float | None:
    # registers[3] is the "battery" class (nameplate/nominal voltage, e.g.
    # 12/24/48V).
    registers = _registers(result)
    return registers[3] * 1.0 if registers is not None else None


def _compute_values(result: MustPollResult, options: Mapping[str, Any]) -> dict[str, StateType]:
    registers = _registers(result)
    if registers is None:
        return {}

    battery_voltage = registers[14] * 0.1
    charging_current = 0.0 if registers[2] == _WORK_STATE_BACKUP else registers[15] * 0.1
    is_charging = registers[2] == _WORK_STATE_LINE

    # See battery_curve_defaults_for_nominal_voltage()'s docstring for why
    # this matters (otherwise every non-24V bank's battery_level was badly
    # wrong using the 24V-tuned static defaults).
    curve_defaults = battery_curve_defaults_for_nominal_voltage(_nominal_voltage(result))

    level = battery_level_curve(
        voltage=battery_voltage,
        is_charging=is_charging,
        charging_current=charging_current,
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
    return {"battery_level": level}


def _client_factory(hass: HomeAssistant, entry: ConfigEntry) -> MustDeviceClient:
    data = entry.data
    connection_kind = data[CONF_CONNECTION_KIND]
    return ModbusClient(
        connection_kind=connection_kind,
        device_path=data.get(CONF_DEVICE_PATH),
        host=data.get(CONF_HOST),
        port=data.get(CONF_PORT),
        slave_id=data.get(CONF_SLAVE_ID, DEFAULT_MODBUS_SLAVE_ID),
    )


SENSORS: tuple[MustSensorEntityDescription, ...] = (
    MustSensorEntityDescription(
        key="machine_type",
        translation_key="machine_type",
        device_class=SensorDeviceClass.ENUM,
        options=_enum_options(MACHINE_TYPE_MAP),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_register_enum(0, MACHINE_TYPE_MAP),
    ),
    MustSensorEntityDescription(
        key="software_version",
        translation_key="software_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_software_version,
    ),
    MustSensorEntityDescription(
        key="work_state",
        translation_key="work_state",
        device_class=SensorDeviceClass.ENUM,
        options=_enum_options(WORK_STATE_MAP),
        value_fn=_register_enum(2, WORK_STATE_MAP),
    ),
    MustSensorEntityDescription(
        key="battery",
        translation_key="battery_class",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_register(3, 1.0),
    ),
    MustSensorEntityDescription(
        key="rated_power",
        translation_key="rated_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_register(4, 1.0),
    ),
    MustSensorEntityDescription(
        key="input_voltage",
        translation_key="grid_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_register(5, 0.1),
    ),
    MustSensorEntityDescription(
        key="input_frequency",
        translation_key="grid_frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_register(6, 0.1),
    ),
    MustSensorEntityDescription(
        key="output_voltage",
        translation_key="output_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_register(7, 0.1),
    ),
    MustSensorEntityDescription(
        key="output_frequency",
        translation_key="output_frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_register(8, 0.1),
    ),
    MustSensorEntityDescription(
        key="load_current",
        translation_key="load_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_register(9, 0.1),
    ),
    MustSensorEntityDescription(
        key="output_power",
        translation_key="load_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_register(10, 1.0),
    ),
    MustSensorEntityDescription(
        key="load_level",
        translation_key="load_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_register(12, 1.0),
    ),
    MustSensorEntityDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_register(14, 0.1),
    ),
    MustSensorEntityDescription(
        key="charging_current",
        translation_key="battery_charging_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_charging_current,
    ),
    MustSensorEntityDescription(
        key="battery_temperature",
        translation_key="battery_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_register(16, 1.0),
    ),
    MustSensorEntityDescription(
        key="battery_soc",
        translation_key="battery_soc",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_register(17, 1.0),
    ),
    MustSensorEntityDescription(
        key="ups_temperature",
        translation_key="inverter_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_register(18, 1.0),
    ),
    MustSensorEntityDescription(
        key="buzzer_state",
        translation_key="buzzer_state",
        device_class=SensorDeviceClass.ENUM,
        options=_enum_options(BUZZER_STATE_MAP),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_register_enum(20, BUZZER_STATE_MAP),
    ),
    MustSensorEntityDescription(
        key="system_fault",
        translation_key="system_fault",
        device_class=SensorDeviceClass.ENUM,
        options=_enum_options(SYSTEM_FAULT_MAP),
        value_fn=_register_enum(21, SYSTEM_FAULT_MAP),
    ),
    MustSensorEntityDescription(
        key="system_alarm",
        translation_key="system_alarm",
        device_class=SensorDeviceClass.ENUM,
        options=_enum_options(SYSTEM_ALARM_MAP),
        value_fn=_register_enum(22, SYSTEM_ALARM_MAP),
    ),
    MustSensorEntityDescription(
        key="charge_stage",
        translation_key="charge_stage",
        device_class=SensorDeviceClass.ENUM,
        options=_enum_options(CHARGE_STAGE_MAP),
        value_fn=_register_enum(23, CHARGE_STAGE_MAP),
    ),
    MustSensorEntityDescription(
        key="grid_charge_flag",
        translation_key="grid_charge_flag",
        device_class=SensorDeviceClass.ENUM,
        options=_enum_options(GRID_CHARGE_FLAG_MAP),
        value_fn=_register_enum(24, GRID_CHARGE_FLAG_MAP),
    ),
    MustSensorEntityDescription(
        key="grid_state",
        translation_key="grid_state",
        device_class=SensorDeviceClass.ENUM,
        options=_enum_options(GRID_STATE_MAP),
        value_fn=_register_enum(25, GRID_STATE_MAP),
    ),
    MustSensorEntityDescription(
        key="battery_level",
        translation_key="battery_level",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda result: result.values.get("battery_level"),
    ),
)

EP3000_PLUS_PROFILE = DeviceProfile(
    key=PROFILE_EP3000_PLUS,
    model_name="EP3000 Plus",
    connection_kinds=(CONNECTION_SERIAL, CONNECTION_TCP, CONNECTION_UDP),
    client_factory=_client_factory,
    sensors=SENSORS,
    binary_sensors=(),
    battery_curve_defaults=BATTERY_CURVE_24V,
    compute_values=_compute_values,
    nominal_voltage_fn=_nominal_voltage,
)
