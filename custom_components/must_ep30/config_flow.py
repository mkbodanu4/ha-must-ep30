"""Config flow for the MUST EP30/EP3000 integration.

Step graph::

    user -> serial              (EP30 Pro, or EP3000 Plus over USB Modbus)
    user -> tcp                 (EP3000 Plus over a Modbus TCP gateway)
    user -> udp                 (EP3000 Plus over a Modbus UDP gateway)
    reconfigure -> (serial|tcp|udp), branching on the existing entry's
                   connection kind; the device profile itself is immutable
                   post-creation since it determines the entity set.

Every connection-specific step performs a *real* read against the device
before the entry is created (or, for reconfigure, before it's updated).
"""

from __future__ import annotations

import asyncio
import math
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SerialPortSelector,
)
from pymodbus.exceptions import ModbusException

from .const import (
    CONF_ADC_BATTERY_VOLTAGE_MAX,
    CONF_CHARGE_BOOST_VOLTAGE,
    CONF_CHARGE_EMPTY_VOLTAGE,
    CONF_CHARGE_FLOAT_CURRENT,
    CONF_CHARGE_FULL_VOLTAGE,
    CONF_CONNECTION_KIND,
    CONF_DEVICE_PATH,
    CONF_DISCHARGE_EMPTY_VOLTAGE,
    CONF_DISCHARGE_FULL_VOLTAGE,
    CONF_HOST,
    CONF_MODEL_CHOICE,
    CONF_POLL_INTERVAL,
    CONF_PORT,
    CONF_PROFILE,
    CONF_SLAVE_ID,
    CONFIG_FLOW_TIMEOUT,
    CONNECTION_SERIAL,
    CONNECTION_TCP,
    CONNECTION_UDP,
    DEFAULT_ADC_BATTERY_VOLTAGE_MAX,
    DEFAULT_MODBUS_PORT,
    DEFAULT_MODBUS_SLAVE_ID,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    LOGGER,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    PROFILE_EP30_PRO,
    PROFILE_EP3000_PLUS,
)
from .devices import get_profile
from .devices.models import battery_curve_defaults_for_nominal_voltage
from .protocol.ascii_serial import AsciiSerialClient
from .protocol.base import MustDeviceClient
from .protocol.exceptions import MustConnectionError, MustProtocolError
from .protocol.modbus import ModbusClient

# Maps a single user-facing choice to (profile_key, connection_kind). Kept
# as one combined list (rather than a separate model + connection-kind
# question) since EP30 Pro only ever supports one connection kind and
# splitting the question would just add a redundant screen for that case.
MODEL_CHOICES: dict[str, tuple[str, str]] = {
    "ep30_pro_serial": (PROFILE_EP30_PRO, CONNECTION_SERIAL),
    "ep3000_plus_serial": (PROFILE_EP3000_PLUS, CONNECTION_SERIAL),
    "ep3000_plus_tcp": (PROFILE_EP3000_PLUS, CONNECTION_TCP),
    "ep3000_plus_udp": (PROFILE_EP3000_PLUS, CONNECTION_UDP),
}


class MustEp30ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MUST EP30/EP3000."""

    VERSION = 1

    def __init__(self) -> None:
        self._profile_key: str = PROFILE_EP30_PRO
        self._connection_kind: str = CONNECTION_SERIAL
        self._name: str = ""
        self._is_reconfigure = False

    @staticmethod
    def async_get_options_flow(config_entry) -> MustEp30OptionsFlow:
        return MustEp30OptionsFlow()

    # -- initial setup ------------------------------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._profile_key, self._connection_kind = MODEL_CHOICES[user_input[CONF_MODEL_CHOICE]]
            self._name = user_input.get("name") or get_profile(self._profile_key).model_name
            return await self._async_step_for_connection_kind()

        schema = vol.Schema(
            {
                vol.Required(CONF_MODEL_CHOICE): SelectSelector(
                    SelectSelectorConfig(
                        options=list(MODEL_CHOICES.keys()),
                        translation_key=CONF_MODEL_CHOICE,
                    )
                ),
                vol.Optional("name"): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    # -- reconfigure ----------------------------------------------------

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        self._profile_key = entry.data[CONF_PROFILE]
        self._connection_kind = entry.data[CONF_CONNECTION_KIND]
        self._name = entry.title
        self._is_reconfigure = True
        return await self._async_step_for_connection_kind(user_input)

    async def _async_step_for_connection_kind(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._connection_kind == CONNECTION_SERIAL:
            return await self.async_step_serial(user_input)
        if self._connection_kind == CONNECTION_TCP:
            return await self.async_step_tcp(user_input)
        return await self.async_step_udp(user_input)

    # -- connection-specific steps ---------------------------------------

    async def async_step_serial(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            device_path = user_input[CONF_DEVICE_PATH]
            client = self._build_client(connection_kind=CONNECTION_SERIAL, device_path=device_path)
            try:
                error = await self._async_validate(client)
                if error is None:
                    serial_number = await self._async_probe_serial_number(client)
            finally:
                await client.async_close()
            if error is None:
                unique_id_prefix = "ascii" if self._profile_key == PROFILE_EP30_PRO else "modbus"
                unique_id = f"{unique_id_prefix}-serial://{device_path}"
                if serial_number:
                    unique_id = f"modbus-serialnum://{serial_number}"
                return await self._async_finish(
                    unique_id=unique_id,
                    data={
                        CONF_PROFILE: self._profile_key,
                        CONF_CONNECTION_KIND: CONNECTION_SERIAL,
                        CONF_DEVICE_PATH: device_path,
                    },
                )
            errors["base"] = error

        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_PATH, default="/dev/ttyUSB0"): SerialPortSelector(),
            }
        )
        return self.async_show_form(step_id="serial", data_schema=schema, errors=errors)

    async def async_step_tcp(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_step_network(user_input, connection_kind=CONNECTION_TCP)

    async def async_step_udp(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_step_network(user_input, connection_kind=CONNECTION_UDP)

    async def _async_step_network(
        self, user_input: dict[str, Any] | None, *, connection_kind: str
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            slave_id = user_input[CONF_SLAVE_ID]
            client = self._build_client(
                connection_kind=connection_kind, host=host, port=port, slave_id=slave_id
            )
            try:
                error = await self._async_validate(client)
                if error is None:
                    serial_number = await self._async_probe_serial_number(client)
            finally:
                await client.async_close()
            if error is None:
                unique_id = f"modbus-{connection_kind}://{host.lower()}:{port}/{slave_id}"
                if serial_number:
                    unique_id = f"modbus-serialnum://{serial_number}"
                return await self._async_finish(
                    unique_id=unique_id,
                    data={
                        CONF_PROFILE: self._profile_key,
                        CONF_CONNECTION_KIND: connection_kind,
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_SLAVE_ID: slave_id,
                    },
                )
            errors["base"] = error

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_MODBUS_PORT): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=65535)
                ),
                vol.Required(CONF_SLAVE_ID, default=DEFAULT_MODBUS_SLAVE_ID): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=247)
                ),
            }
        )
        return self.async_show_form(step_id=connection_kind, data_schema=schema, errors=errors)

    # -- shared helpers ---------------------------------------------------

    def _build_client(
        self,
        *,
        connection_kind: str,
        device_path: str | None = None,
        host: str | None = None,
        port: int | None = None,
        slave_id: int | None = None,
    ) -> MustDeviceClient:
        if self._profile_key == PROFILE_EP30_PRO:
            assert device_path is not None
            return AsciiSerialClient(device_path=device_path)
        return ModbusClient(
            connection_kind=connection_kind,
            device_path=device_path,
            host=host,
            port=port,
            slave_id=slave_id or DEFAULT_MODBUS_SLAVE_ID,
        )

    @staticmethod
    async def _async_validate(client: MustDeviceClient) -> str | None:
        """Perform a real connect + read; return an error code or None."""
        try:
            async with asyncio.timeout(CONFIG_FLOW_TIMEOUT):
                await client.async_connect()
                await client.async_fetch()
        except (
            MustConnectionError,
            MustProtocolError,
            ModbusException,
            OSError,
            TimeoutError,
        ) as err:
            LOGGER.debug("Config flow validation failed: %s", err)
            return "cannot_connect"
        return None

    @staticmethod
    async def _async_probe_serial_number(client: MustDeviceClient) -> str | None:
        """Best-effort EP3000 Plus serial-number probe; see ModbusClient docs."""
        if isinstance(client, ModbusClient):
            try:
                async with asyncio.timeout(CONFIG_FLOW_TIMEOUT):
                    return await client.async_probe_serial_number()
            except (
                AttributeError,
                IndexError,
                TypeError,
                ValueError,
                ModbusException,
                OSError,
                TimeoutError,
            ):
                LOGGER.debug("Serial-number probe failed", exc_info=True)
        return None

    async def _async_finish(self, *, unique_id: str, data: dict[str, Any]) -> ConfigFlowResult:
        if self._is_reconfigure:
            current_entry = self._get_reconfigure_entry()
            if any(
                other.entry_id != current_entry.entry_id and other.unique_id == unique_id
                for other in self.hass.config_entries.async_entries(DOMAIN)
            ):
                return self.async_abort(reason="already_configured")
            return self.async_update_reload_and_abort(current_entry, data=data, unique_id=unique_id)
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=self._name, data=data)


class MustEp30OptionsFlow(OptionsFlowWithReload):
    """Options flow: poll interval, plus an advanced battery-calibration step."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["general", "battery_calibration"])

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={**self.config_entry.options, **user_input})

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_POLL_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
                    ),
                ): vol.All(int, vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL)),
            }
        )
        return self.async_show_form(step_id="general", data_schema=schema)

    async def async_step_battery_calibration(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if _valid_battery_calibration(user_input):
                return self.async_create_entry(data={**self.config_entry.options, **user_input})
            errors["base"] = "invalid_calibration"

        profile = get_profile(self.config_entry.data[CONF_PROFILE])
        defaults = profile.battery_curve_defaults
        # Prefer defaults derived from the device's own last-known nominal
        # voltage reading over the static 24V-bank fallback, so a 12V/48V
        # system doesn't see nonsensical pre-filled values here -- see
        # battery_curve_defaults_for_nominal_voltage()'s docstring.
        coordinator = getattr(self.config_entry, "runtime_data", None)
        if profile.nominal_voltage_fn is not None and coordinator is not None:
            poll_result = coordinator.data
            if poll_result is not None:
                nominal_voltage = profile.nominal_voltage_fn(poll_result)
                if nominal_voltage is not None:
                    defaults = battery_curve_defaults_for_nominal_voltage(nominal_voltage)
        options = self.config_entry.options

        schema_dict: dict[Any, Any] = {
            vol.Required(
                CONF_CHARGE_FLOAT_CURRENT,
                default=options.get(CONF_CHARGE_FLOAT_CURRENT, defaults.charge_float_current),
            ): _positive_finite_float,
            vol.Required(
                CONF_CHARGE_FULL_VOLTAGE,
                default=options.get(CONF_CHARGE_FULL_VOLTAGE, defaults.charge_full_voltage),
            ): _positive_finite_float,
            vol.Required(
                CONF_CHARGE_BOOST_VOLTAGE,
                default=options.get(CONF_CHARGE_BOOST_VOLTAGE, defaults.charge_boost_voltage),
            ): _positive_finite_float,
            vol.Required(
                CONF_CHARGE_EMPTY_VOLTAGE,
                default=options.get(CONF_CHARGE_EMPTY_VOLTAGE, defaults.charge_empty_voltage),
            ): _positive_finite_float,
            vol.Required(
                CONF_DISCHARGE_FULL_VOLTAGE,
                default=options.get(CONF_DISCHARGE_FULL_VOLTAGE, defaults.discharge_full_voltage),
            ): _positive_finite_float,
            vol.Required(
                CONF_DISCHARGE_EMPTY_VOLTAGE,
                default=options.get(CONF_DISCHARGE_EMPTY_VOLTAGE, defaults.discharge_empty_voltage),
            ): _positive_finite_float,
        }

        if self.config_entry.data[CONF_PROFILE] == PROFILE_EP30_PRO:
            schema_dict[
                vol.Required(
                    CONF_ADC_BATTERY_VOLTAGE_MAX,
                    default=options.get(
                        CONF_ADC_BATTERY_VOLTAGE_MAX, DEFAULT_ADC_BATTERY_VOLTAGE_MAX
                    ),
                )
            ] = _positive_finite_float

        return self.async_show_form(
            step_id="battery_calibration", data_schema=vol.Schema(schema_dict), errors=errors
        )


def _positive_finite_float(value: Any) -> float:
    """Coerce a finite, positive calibration value."""
    number = vol.Coerce(float)(value)
    if not math.isfinite(number) or number <= 0:
        raise vol.Invalid("value must be finite and greater than zero")
    return number


def _valid_battery_calibration(values: dict[str, Any]) -> bool:
    """Validate relationships between battery curve thresholds."""
    return (
        values[CONF_CHARGE_EMPTY_VOLTAGE]
        < values[CONF_CHARGE_FULL_VOLTAGE]
        <= values[CONF_CHARGE_BOOST_VOLTAGE]
        and values[CONF_DISCHARGE_EMPTY_VOLTAGE] < values[CONF_DISCHARGE_FULL_VOLTAGE]
    )
