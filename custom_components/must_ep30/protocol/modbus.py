"""Modbus RTU/TCP/UDP client for the MUST EP3000 Plus.

Reads a single 26-register holding-register block starting at address
30000 (device_id/slave configurable, default 10) -- the same read the
original project's ``ep3000_plus.py`` performed. The register offsets and
scaling are NOT decided here; they live in ``devices/ep3000_plus.py`` as a
declarative table this client's caller (the coordinator) doesn't need to
know about. This module only owns transport + the raw register read.

Deliberately does not depend on or reuse register maps from
``mukaschultze/ha-must-inverter`` -- that project's own issue tracker
(#112) documents garbled/misaligned reads against a real EP3000 Plus, so
its PV1800/PV1900 register layout is known-incompatible with this
hardware. The 30000-30026 block below is re-derived from this project's
own field-tested ``ep3000_plus.py`` instead.
"""

from __future__ import annotations

import asyncio

from pymodbus.client import (
    AsyncModbusSerialClient,
    AsyncModbusTcpClient,
    AsyncModbusUdpClient,
)
from pymodbus.exceptions import ModbusException

from ..const import (
    CONNECTION_SERIAL,
    CONNECTION_TCP,
    CONNECTION_UDP,
    MODBUS_BASE_ADDRESS,
    MODBUS_BAUDRATE,
    MODBUS_PARITY,
    MODBUS_REGISTER_COUNT,
    MODBUS_SERIAL_NUMBER_HIGH_REGISTER,
    MODBUS_STOPBITS,
)
from .base import MustDeviceClient, MustPollResult
from .exceptions import MustConnectionError, MustProtocolError

_SerialNumberRegisters = tuple[int, int]


class ModbusClient(MustDeviceClient):
    """Async Modbus client supporting serial (RTU), TCP, and UDP transports."""

    def __init__(
        self,
        *,
        connection_kind: str,
        device_path: str | None = None,
        host: str | None = None,
        port: int | None = None,
        slave_id: int,
    ) -> None:
        self._connection_kind = connection_kind
        self._slave_id = slave_id
        self._lock = asyncio.Lock()

        if connection_kind == CONNECTION_SERIAL:
            if not device_path:
                raise ValueError("device_path is required for serial connections")
            self._client = AsyncModbusSerialClient(
                port=device_path,
                baudrate=MODBUS_BAUDRATE,
                parity=MODBUS_PARITY,
                stopbits=MODBUS_STOPBITS,
            )
        elif connection_kind == CONNECTION_TCP:
            if not host or not port:
                raise ValueError("host and port are required for TCP connections")
            self._client = AsyncModbusTcpClient(host=host, port=port)
        elif connection_kind == CONNECTION_UDP:
            if not host or not port:
                raise ValueError("host and port are required for UDP connections")
            self._client = AsyncModbusUdpClient(host=host, port=port)
        else:
            raise ValueError(f"Unsupported Modbus connection kind: {connection_kind}")

    async def async_connect(self) -> None:
        try:
            await self._client.connect()
        except (OSError, ModbusException, TimeoutError) as err:
            raise MustConnectionError(str(err)) from err
        if not self._client.connected:
            raise MustConnectionError("Modbus client failed to connect")

    async def async_close(self) -> None:
        self._client.close()

    async def async_fetch(self) -> MustPollResult:
        async with self._lock:
            if not self._client.connected:
                await self.async_connect()

            try:
                result = await self._client.read_holding_registers(
                    address=MODBUS_BASE_ADDRESS,
                    count=MODBUS_REGISTER_COUNT,
                    device_id=self._slave_id,
                )
            except (OSError, ModbusException, TimeoutError) as err:
                await self.async_close()
                raise MustConnectionError(str(err)) from err

            if result.isError():
                raise MustProtocolError(f"Modbus error response: {result}")

            registers = result.registers
            if len(registers) != MODBUS_REGISTER_COUNT:
                raise MustProtocolError(
                    f"Expected {MODBUS_REGISTER_COUNT} registers, got {len(registers)}"
                )

            return MustPollResult(values={}, raw={"registers": registers})

    async def async_probe_serial_number(self) -> str | None:
        """Best-effort read of the serial-number register pair.

        Registers 31200 (high)/31201 (low) are documented only for the
        EP3300/EP3300-TLV Modbus profiles in the reverse-engineered
        reference sources -- never confirmed present/populated on the
        plain EP3000 Plus 30000-30026 profile this client targets. This
        probe is intentionally non-fatal: any failure, or an all-zero
        result, returns ``None`` and the caller (config_flow) falls back
        to a connection-string-based unique_id instead.
        """
        async with self._lock:
            if not self._client.connected:
                try:
                    await self.async_connect()
                except MustConnectionError:
                    return None
            try:
                result = await self._client.read_holding_registers(
                    address=MODBUS_SERIAL_NUMBER_HIGH_REGISTER,
                    count=2,
                    device_id=self._slave_id,
                )
            except (OSError, ModbusException, TimeoutError):
                return None

            try:
                if result.isError() or len(result.registers) != 2:
                    return None
                high, low = result.registers
                if high == 0 and low == 0:
                    return None
                return f"{high:05d}{low:05d}"
            except (AttributeError, TypeError, ValueError):
                return None
