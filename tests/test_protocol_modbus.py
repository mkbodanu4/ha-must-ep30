"""Unit tests for the EP3000 Plus Modbus client.

Uses a fake transport client injected in place of pymodbus's
Async*Client classes, so these run without any real serial port/network
socket and without depending on pymodbus's exact constructor signature
beyond what ModbusClient itself calls.
"""

from __future__ import annotations

import pytest

from custom_components.must_ep30.const import (
    MODBUS_BASE_ADDRESS,
    MODBUS_SERIAL_NUMBER_HIGH_REGISTER,
)
from custom_components.must_ep30.protocol.exceptions import (
    MustConnectionError,
    MustProtocolError,
)
from custom_components.must_ep30.protocol.modbus import ModbusClient


class _FakeResult:
    def __init__(self, *, is_error: bool, registers: list[int]) -> None:
        self._is_error = is_error
        self.registers = registers

    def isError(self) -> bool:
        return self._is_error


class _FakeTransportClient:
    def __init__(self, *, responses=None, raise_on_connect: bool = False) -> None:
        self.connected = False
        self._responses = responses or {}
        self._raise_on_connect = raise_on_connect

    async def connect(self) -> bool:
        if self._raise_on_connect:
            raise OSError("simulated connect failure")
        self.connected = True
        return True

    def close(self) -> None:
        self.connected = False

    async def read_holding_registers(self, address: int, count: int, device_id: int):
        response = self._responses.get(address)
        if response is None:
            return _FakeResult(is_error=True, registers=[])
        return response


def _install_fake_client(monkeypatch: pytest.MonkeyPatch, fake: _FakeTransportClient) -> None:
    for name in (
        "AsyncModbusSerialClient",
        "AsyncModbusTcpClient",
        "AsyncModbusUdpClient",
    ):
        monkeypatch.setattr(
            f"custom_components.must_ep30.protocol.modbus.{name}",
            lambda *args, **kwargs: fake,
        )


async def test_async_fetch_success(monkeypatch: pytest.MonkeyPatch) -> None:
    registers = list(range(26))
    fake = _FakeTransportClient(
        responses={MODBUS_BASE_ADDRESS: _FakeResult(is_error=False, registers=registers)}
    )
    _install_fake_client(monkeypatch, fake)

    client = ModbusClient(connection_kind="serial", device_path="/dev/ttyUSB0", slave_id=10)
    result = await client.async_fetch()

    assert result.raw["registers"] == registers


async def test_async_fetch_error_result_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeTransportClient(
        responses={MODBUS_BASE_ADDRESS: _FakeResult(is_error=True, registers=[])}
    )
    _install_fake_client(monkeypatch, fake)

    client = ModbusClient(connection_kind="serial", device_path="/dev/ttyUSB0", slave_id=10)
    with pytest.raises(MustProtocolError):
        await client.async_fetch()


async def test_async_fetch_short_register_list_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeTransportClient(
        responses={MODBUS_BASE_ADDRESS: _FakeResult(is_error=False, registers=[1, 2, 3])}
    )
    _install_fake_client(monkeypatch, fake)

    client = ModbusClient(connection_kind="serial", device_path="/dev/ttyUSB0", slave_id=10)
    with pytest.raises(MustProtocolError):
        await client.async_fetch()


async def test_async_connect_raises_must_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeTransportClient(raise_on_connect=True)
    _install_fake_client(monkeypatch, fake)

    client = ModbusClient(connection_kind="serial", device_path="/dev/ttyUSB0", slave_id=10)
    with pytest.raises(MustConnectionError):
        await client.async_connect()


async def test_probe_serial_number_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeTransportClient(
        responses={
            MODBUS_SERIAL_NUMBER_HIGH_REGISTER: _FakeResult(is_error=False, registers=[12345, 6789])
        }
    )
    _install_fake_client(monkeypatch, fake)

    client = ModbusClient(connection_kind="serial", device_path="/dev/ttyUSB0", slave_id=10)
    serial_number = await client.async_probe_serial_number()

    assert serial_number == "1234506789"


async def test_probe_serial_number_all_zero_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeTransportClient(
        responses={
            MODBUS_SERIAL_NUMBER_HIGH_REGISTER: _FakeResult(is_error=False, registers=[0, 0])
        }
    )
    _install_fake_client(monkeypatch, fake)

    client = ModbusClient(connection_kind="serial", device_path="/dev/ttyUSB0", slave_id=10)
    assert await client.async_probe_serial_number() is None


async def test_probe_serial_number_unsupported_register_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The fake has no response configured for the SN register at all,
    # simulating a device (plain EP3000 Plus) that doesn't populate it --
    # the probe must degrade gracefully, not raise.
    fake = _FakeTransportClient(responses={})
    _install_fake_client(monkeypatch, fake)

    client = ModbusClient(connection_kind="serial", device_path="/dev/ttyUSB0", slave_id=10)
    assert await client.async_probe_serial_number() is None


def test_tcp_requires_host_and_port(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_client(monkeypatch, _FakeTransportClient())
    with pytest.raises(ValueError):
        ModbusClient(connection_kind="tcp", slave_id=10)
