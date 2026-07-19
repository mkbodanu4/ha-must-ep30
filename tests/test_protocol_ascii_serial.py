"""Unit tests for the EP30 Pro ASCII protocol parser.

These exercise the static ``_parse_*`` methods directly with synthetic
byte strings -- no serial I/O, no HA fixtures needed. The two required
bug fixes (BCD temperature decode, working_status fallback) are the
highest-value cases here since the original project had them wrong.

The end-to-end regression test near the bottom of this file additionally
exercises the real async I/O path (``AsciiSerialClient.async_fetch()``)
against a scripted fake transport, to cover the stray-bytes-before-D bug
fix that the parser-only tests above can't reach.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from custom_components.must_ep30.protocol.ascii_serial import (
    WORKING_STATUS_MAP,
    AsciiSerialClient,
)

from .conftest import make_f_response, make_q1_response


def test_parse_f() -> None:
    response = make_f_response(
        rating_voltage="220.0",
        rating_current="10.0",
        nominal_battery_voltage="24.00",
        nominal_frequency="50.0",
    )
    values = AsciiSerialClient._parse_f(response, {})
    assert values["rating_voltage"] == 220.0
    assert values["rating_current"] == 10.0
    assert values["nominal_battery_voltage"] == 24.00
    assert values["nominal_frequency"] == 50.0


def test_parse_q1_basic_fields() -> None:
    response = make_q1_response(
        input_voltage="220.0",
        output_voltage="230.0",
        load_level="042",
        battery_voltage="27.2",
    )
    values = AsciiSerialClient._parse_q1(response, {})
    assert values["input_voltage"] == 220.0
    assert values["output_voltage"] == 230.0
    assert values["load_level"] == 42
    assert values["battery_voltage"] == 27.2


def test_parse_q1_temperature_bcd_decode() -> None:
    """Bugfix #1: temp_field "25.3" -> tens digit 2 (*10) + 5.3 = 25.3."""
    response = make_q1_response(temp_field="25.3")
    values = AsciiSerialClient._parse_q1(response, {})
    assert values["ups_temperature"] == 25.3


def test_parse_q1_temperature_bcd_decode_zero_tens() -> None:
    """A tens digit of 0 ("0") should not corrupt the low end of the range."""
    response = make_q1_response(temp_field="04.5")
    values = AsciiSerialClient._parse_q1(response, {})
    assert values["ups_temperature"] == 4.5


def test_parse_q1_temperature_plausibility_warning(caplog) -> None:
    """An implausible decode should log a warning but still return a value."""
    caplog.set_level(logging.WARNING)
    # tens-digit char 'A' (ord 65) -> (65-48)*10 = 170, + fraction 0.0 = 170.0,
    # well outside the -10..120 plausible range.
    response = make_q1_response(temp_field="A0.0")
    values = AsciiSerialClient._parse_q1(response, {})
    assert values["ups_temperature"] == 170.0
    assert any("implausible temperature" in record.message for record in caplog.records)


def test_parse_q1_working_status_validated_code() -> None:
    """Only ASCII code 30 is empirically validated -> battery_priority."""
    response = make_q1_response(working_status_code=30)
    values = AsciiSerialClient._parse_q1(response, {})
    assert values["working_status"] == "battery_priority"
    assert values["working_status_code"] == 30
    assert WORKING_STATUS_MAP[30] == "battery_priority"


def test_parse_q1_working_status_unknown_code_fallback() -> None:
    """Bugfix #2: unmapped codes must not be silently mis-reported."""
    response = make_q1_response(working_status_code=65)  # 'A', arbitrary unmapped code
    values = AsciiSerialClient._parse_q1(response, {})
    assert values["working_status"] == "unknown_code_65"


def test_parse_q1_working_status_bypass_code() -> None:
    """Code 31 -> bypass: backed by a real field report (working_status=31
    observed with utility_fail=0 and output_voltage tracking input_voltage,
    both characteristic of bypass mode) plus the predecessor project's own
    "not 30 -> Bypass" fallback heuristic in mqtt.py.
    """
    response = make_q1_response(working_status_code=31)
    values = AsciiSerialClient._parse_q1(response, {})
    assert values["working_status"] == "bypass"
    assert values["working_status_code"] == 31
    assert WORKING_STATUS_MAP[31] == "bypass"


def test_parse_q1_flags() -> None:
    response = make_q1_response(
        utility_fail="1",
        battery_low="1",
        ups_failed="1",
        ups_type="0",
        test_in_progress="1",
        shutdown_active="1",
        beeper_on="1",
    )
    values = AsciiSerialClient._parse_q1(response, {})
    assert values["utility_fail"] == 1
    assert values["battery_low"] == 1
    assert values["ups_failed"] == 1
    assert values["ups_type"] == 0
    assert values["test_in_progress"] == 1
    assert values["shutdown_active"] == 1
    assert values["beeper_on"] == 1


def test_parse_g_passthrough() -> None:
    values = AsciiSerialClient._parse_g(b"No fault\r", {})
    assert values["fault_state"] == "No fault"


def test_parse_g_over_voltage_special_case() -> None:
    values = AsciiSerialClient._parse_g(b"Battery Over Volage\r", {})
    assert values["fault_state"] == "Battery Over Voltage"


def test_parse_d_charging_ack() -> None:
    values = AsciiSerialClient._parse_d(b"ACK", {})
    assert values["is_charging"] is True


def test_parse_d_not_charging() -> None:
    values = AsciiSerialClient._parse_d(b"NAK", {})
    assert values["is_charging"] is False


def test_parse_x_while_charging() -> None:
    response = b"a 1 2 ff\n"  # hex: a=10, 1, 2, ff=255
    values = AsciiSerialClient._parse_x(response, {"is_charging": True})
    assert values["charging_value1"] == 10.0
    assert values["charging_value2"] == 1.0
    assert values["charging_value3"] == 2.0
    assert values["charging_value4"] == 255.0
    assert values["charging_current"] == 10.0


def test_parse_x_while_not_charging_forces_zero_current() -> None:
    response = b"a 1 2 ff\n"
    values = AsciiSerialClient._parse_x(response, {"is_charging": False})
    assert values["charging_current"] == 0.0


def test_parse_x_missing_is_charging_defaults_to_not_charging() -> None:
    """If the D command failed this cycle, charging_current must default safe."""
    response = b"a 1 2 ff\n"
    values = AsciiSerialClient._parse_x(response, {})
    assert values["charging_current"] == 0.0


def test_parse_x_accepts_arbitrary_whitespace() -> None:
    values = AsciiSerialClient._parse_x(b"a  1\t2   ff\n", {"is_charging": True})
    assert values["charging_current"] == 10.0


class _ScriptedAsyncSerial:
    """Fake serialx.AsyncSerial reproducing a real reported byte-level bug:
    2 stray bytes ("Fa") sit unconsumed in the buffer after G?'s response
    (its terminator-based read only consumes through the \\r), so by the
    time D's read starts, "Fa" is already there ahead of D's real "NAK".
    Without draining, D's readexactly(3) reads "Fa"+"N" instead of "NAK",
    leaving "AK" to corrupt the start of X's response too.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.is_open = True
        self.write_log: list[bytes] = []
        self._responses = {
            b"F\n": b"#230.0 007 12.00 50.0\r",
            b"Q1\n": b"(204.0 204.0 199.0 000 50.0 13.6 26.0 00\x1f01001\r",
            b"G?\n": b"Normal 04\rFa",  # the "Fa" here is the bug: it's not
            # part of G?'s own message (readuntil(b"\r") stops at the \r,
            # never consuming it), it's what's actually sitting on the wire
            # next -- modeled this way so it lands in the buffer exactly
            # when G?'s response does, before D's drain step runs.
            b"D\n": b"NAK",
            b"X\n": b"01 3B 03 C8 \n",
        }

    async def open(self) -> None:
        self.is_open = True

    async def close(self) -> None:
        self.is_open = False

    async def write(self, data: bytes) -> None:
        self.write_log.append(bytes(data))
        self._buffer.extend(self._responses.get(bytes(data), b""))

    async def flush(self) -> None:
        pass

    async def read(self, n: int = -1) -> bytes:
        if not self._buffer:
            await asyncio.sleep(10)  # cut short by the caller's timeout
            return b""
        if n == -1:
            data = bytes(self._buffer)
            self._buffer.clear()
        else:
            data = bytes(self._buffer[:n])
            del self._buffer[:n]
        return data

    async def readexactly(self, n: int) -> bytes:
        # A single check, not a poll loop: this fake has no concurrent
        # writer, so the buffer can't grow while this coroutine awaits --
        # it either already has enough bytes, or it never will and the
        # caller's own timeout cancels the sleep below.
        if len(self._buffer) < n:
            await asyncio.sleep(10)
        data = bytes(self._buffer[:n])
        del self._buffer[:n]
        return data

    async def readuntil(self, separator: bytes = b"\n") -> bytes:
        while True:
            idx = self._buffer.find(separator)
            if idx != -1:
                data = bytes(self._buffer[: idx + len(separator)])
                del self._buffer[: idx + len(separator)]
                return data
            await asyncio.sleep(10)


async def test_regression_stray_bytes_before_d_no_longer_corrupt_d_and_x(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reproduces the exact reported bug and confirms the drain-before-write
    fix resolves it: with draining, D correctly reads "NAK" (is_charging
    False) and X correctly reads the clean, un-shifted register values.
    Without the fix (pre-existing behavior being guarded against), D would
    read "FaN" and X would read "AK01 3B 03 C8" instead.
    """
    fake = _ScriptedAsyncSerial()
    monkeypatch.setattr(
        "custom_components.must_ep30.protocol.ascii_serial.serialx.async_serial_for_url",
        lambda *a, **k: fake,
    )

    client = AsciiSerialClient(device_path="/dev/fake")
    result = await client.async_fetch()

    assert result.raw["D"] == "NAK"
    assert result.values["is_charging"] is False
    assert result.raw["X"] == "01 3B 03 C8 \n"
    assert result.values["charging_value1"] == float(0x01)
    assert result.values["charging_value2"] == float(0x3B)
    assert result.values["charging_value3"] == float(0x03)
    assert result.values["charging_value4"] == float(0xC8)
    assert result.values["charging_current"] == 0.0  # not charging


async def test_drain_stray_bytes_ignores_transport_error() -> None:
    class _FailingReadSerial:
        async def read(self, _size: int) -> bytes:
            raise OSError("serial transport failed")

    client = AsciiSerialClient(device_path="/dev/fake")
    client._serial = _FailingReadSerial()

    await client._drain_stray_bytes()
