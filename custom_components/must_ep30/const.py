"""Constants for the MUST EP30/EP3000 integration."""

from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "must_ep30"
LOGGER = logging.getLogger(__package__)

MANUFACTURER: Final = "MUST"

# Device profile keys (see devices/models.py PROFILE_REGISTRY)
PROFILE_EP30_PRO: Final = "ep30_pro"
PROFILE_EP3000_PLUS: Final = "ep3000_plus"

# Connection kinds
CONNECTION_SERIAL: Final = "serial"
CONNECTION_TCP: Final = "tcp"
CONNECTION_UDP: Final = "udp"

# Config flow keys
CONF_MODEL_CHOICE: Final = "model_choice"

# Config entry data keys
CONF_PROFILE: Final = "profile"
CONF_CONNECTION_KIND: Final = "connection_kind"
CONF_DEVICE_PATH: Final = "device"
CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_SLAVE_ID: Final = "slave_id"
# Options flow keys
CONF_POLL_INTERVAL: Final = "poll_interval"
CONF_CHARGE_FLOAT_CURRENT: Final = "charge_float_current"
CONF_CHARGE_FULL_VOLTAGE: Final = "charge_full_voltage"
CONF_CHARGE_BOOST_VOLTAGE: Final = "charge_boost_voltage"
CONF_CHARGE_EMPTY_VOLTAGE: Final = "charge_empty_voltage"
CONF_DISCHARGE_FULL_VOLTAGE: Final = "discharge_full_voltage"
CONF_DISCHARGE_EMPTY_VOLTAGE: Final = "discharge_empty_voltage"
CONF_ADC_BATTERY_VOLTAGE_MAX: Final = "adc_battery_voltage_max"

# Defaults
DEFAULT_POLL_INTERVAL: Final = 10  # seconds; original script default was 2s
MIN_POLL_INTERVAL: Final = 5
MAX_POLL_INTERVAL: Final = 300
DEFAULT_MODBUS_PORT: Final = 502
DEFAULT_MODBUS_SLAVE_ID: Final = 10

# Battery voltage-curve reference defaults live in devices/models.py
# (BATTERY_CURVE_24V / battery_curve_defaults_for_nominal_voltage) -- not
# here, to keep a single source of truth after they briefly drifted (see
# CHANGELOG for the 24V empty_voltage 11.0->21.0 fix).
DEFAULT_ADC_BATTERY_VOLTAGE_MAX: Final = 17.35

# ASCII protocol (EP30 Pro) transport constants
ASCII_BAUDRATE: Final = 2400
ASCII_TIMEOUT: Final = 10

# Modbus (EP3000 Plus) transport constants
MODBUS_BAUDRATE: Final = 9600
MODBUS_PARITY: Final = "N"
MODBUS_STOPBITS: Final = 1
MODBUS_BASE_ADDRESS: Final = 30000
MODBUS_REGISTER_COUNT: Final = 26
MODBUS_SERIAL_NUMBER_HIGH_REGISTER: Final = 31200
MODBUS_SERIAL_NUMBER_LOW_REGISTER: Final = 31201

POLL_TIMEOUT: Final = 15
CONFIG_FLOW_TIMEOUT: Final = 15
