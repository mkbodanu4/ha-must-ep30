"""ASCII serial protocol client for the MUST EP30 Pro.

Ports the 5-command polling sequence (``F``, ``Q1``, ``G?``, ``D``, ``X``)
and field offsets from the original ``ep30_pro_mqtt`` project's
``mqtt.py``, with two corrected bugs verified against the decompiled C#
reference sources under ``mapping/serial/`` in that project:

1. ``ups_temperature`` is BCD-like (``Ep3000Server.txt`` lines 28-32), not
   a plain float -- the original Python's ``float(data[33:37])`` is wrong.
2. ``working_status`` has 6 possible states
   (``WorkingModeConverter.txt``) but the original Python only
   distinguishes 2. ASCII code 30 is validated against the decompiled
   reference and code 31 is backed by a real field report; this client maps
   those two codes and uses a safe ``unknown_code_N`` fallback rather than
   guessing the remaining 4 ordinals (see README "Supported hardware").

The protocol carries no checksum/CRC, so a mis-synced read is otherwise
undetectable -- this client applies a sanity clamp to the decoded
temperature and logs a warning if it falls outside a plausible range.

Uses ``serialx``'s native ``AsyncSerial`` transport (``async_serial_for_url``
/ ``readuntil`` / ``readexactly`` / ``write``, all real coroutines) rather
than wrapping pyserial's blocking API in a thread -- confirmed against
serialx 1.8.2's actual API surface. RTS is asserted automatically on open
via serialx's default ``rtsdtr_on_open=PinState.HIGH``, matching the
original C# reference's ``RtsEnable = true``.

Unlike pyserial, ``AsyncSerial`` exposes no ``reset_input_buffer()`` --
the original ``mqtt.py`` calls that (plus ``reset_output_buffer()``)
before every command, which is what makes it tolerant of any stray bytes
left over from a previous exchange. Without an equivalent, this was a
real, reproduced bug: the ``D`` command's fixed-size ``readexactly(3)``
occasionally consumed 1-2 leftover bytes from an unconsumed tail of a
prior response instead of "ACK"/"NAK", which then also shifted the
following ``X`` command's read (e.g. captured ``D=b"FaN"``,
``X=b"AK01 3B 03 C8 \n"`` when the real values were ``D=b"NAK"``,
``X=b"01 3B 03 C8 \n"`` -- the "AK" is literally the tail of "NAK" that
``readexactly(3)`` failed to consume, shifted into the next read).
``_drain_stray_bytes()`` below reproduces ``reset_input_buffer()``'s
effect with a short-timeout ``read()``: if bytes are already sitting in
the buffer (the only case that matters -- by the time it runs, the
inter-command delay has already given the device time to finish replying
to the previous command) it returns them immediately and they're
discarded; otherwise there is nothing to drain, the read has no data to
return, and the short timeout bounds how long we wait to find that out
before moving on to writing the next command.
"""

from __future__ import annotations

import asyncio
from typing import Any

import serialx

from ..const import ASCII_BAUDRATE, ASCII_TIMEOUT, LOGGER
from .base import MustDeviceClient, MustPollResult
from .exceptions import MustConnectionError, MustProtocolError

# ASCII code 30 -> battery_priority: confirmed against the decompiled C#
# reference (WorkingModeConverter.txt) by the original project author.
#
# ASCII code 31 -> bypass: not in the decompiled reference table, but
# backed by two independent pieces of evidence from a real field report:
# (1) the predecessor project's mqtt.py used a blanket
# `"BatteryPriority" if working_status == 30 else "Bypass"` fallback --
# i.e. its author had already observed that "not 30" reliably means
# Bypass in practice on this hardware; (2) the specific reading that
# surfaced code 31 had utility_fail=0 (grid present) and output_voltage
# tracking input_voltage closely, both behaviorally characteristic of
# bypass/pass-through mode rather than battery-inverting mode.
#
# The remaining 4 states (InvertOnly, GridFailAndInvert, GridAndInvertFail,
# Fail) documented in WorkingModeConverter.txt still have no known byte
# value -- do not guess them, extend this table from further field reports.
WORKING_STATUS_MAP: dict[int, str] = {
    30: "battery_priority",
    31: "bypass",
}

_TEMPERATURE_MIN_PLAUSIBLE = -10.0
_TEMPERATURE_MAX_PLAUSIBLE = 120.0

_COMMANDS: tuple[bytes, ...] = (b"F\n", b"Q1\n", b"G?\n", b"D\n", b"X\n")
_INTER_COMMAND_DELAY = 0.1
# Bounds _drain_stray_bytes()'s read -- only needs to be long enough to
# catch bytes already sitting in the buffer, not to wait for new ones.
_DRAIN_TIMEOUT = 0.05


class AsciiSerialClient(MustDeviceClient):
    """Serial client for the EP30 Pro's proprietary ASCII protocol."""

    def __init__(self, *, device_path: str) -> None:
        self._device_path = device_path
        self._serial: serialx.AsyncSerial | None = None

    async def async_connect(self) -> None:
        if self._serial is not None and self._serial.is_open:
            return
        try:
            self._serial = serialx.async_serial_for_url(
                self._device_path, baudrate=ASCII_BAUDRATE, timeout=ASCII_TIMEOUT
            )
            await self._serial.open()
        except (serialx.SerialException, OSError) as err:
            self._serial = None
            raise MustConnectionError(str(err)) from err

    async def async_close(self) -> None:
        if self._serial is not None:
            try:
                await self._serial.close()
            finally:
                self._serial = None

    async def async_fetch(self) -> MustPollResult:
        await self.async_connect()

        values: dict[str, Any] = {}
        raw: dict[str, str] = {}
        failed_commands: set[str] = set()

        parsers = {
            b"F\n": self._parse_f,
            b"Q1\n": self._parse_q1,
            b"G?\n": self._parse_g,
            b"D\n": self._parse_d,
            b"X\n": self._parse_x,
        }

        try:
            for command in _COMMANDS:
                try:
                    response = await self._send_command(command)
                    command_name = command.decode().strip()
                    raw[command_name] = response.decode("utf-8", errors="replace")
                    values.update(parsers[command](response, values))
                except (
                    serialx.SerialException,
                    OSError,
                    TimeoutError,
                    ValueError,
                    IndexError,
                    MustProtocolError,
                    MustConnectionError,
                ) as err:
                    failed_commands.add(command.decode().strip())
                    LOGGER.debug("EP30 Pro command %r failed: %s", command, err)
                    if isinstance(err, (serialx.SerialException, OSError)):
                        await self.async_close()
        except asyncio.CancelledError:
            # A late response would otherwise remain buffered and be parsed as
            # the reply to the next poll's first command.
            await self.async_close()
            raise

        if "Q1" in failed_commands or len(failed_commands) == len(_COMMANDS):
            raise MustProtocolError(
                f"Failed to read EP30 Pro status (failed commands: {sorted(failed_commands)})"
            )

        return MustPollResult(values=values, raw=raw)

    async def _drain_stray_bytes(self) -> None:
        """Discard anything already buffered, mirroring pyserial's
        ``reset_input_buffer()`` (see module docstring for the bug this
        fixes). Never raises -- an empty buffer is the common case and just
        means the short timeout below elapses with nothing to report.
        """
        if self._serial is None:
            return
        try:
            async with asyncio.timeout(_DRAIN_TIMEOUT):
                stray = await self._serial.read(4096)
        except TimeoutError:
            return
        except (serialx.SerialException, OSError) as err:
            LOGGER.debug("Failed to drain EP30 Pro serial input: %s", err)
            return
        if stray:
            LOGGER.debug("Discarded %d stray byte(s) before next command: %r", len(stray), stray)

    async def _send_command(self, command: bytes) -> bytes:
        if self._serial is None:
            raise MustConnectionError("Serial port is not open")

        await self._drain_stray_bytes()

        await self._serial.write(command)
        await asyncio.sleep(_INTER_COMMAND_DELAY)
        await self._serial.flush()

        async with asyncio.timeout(ASCII_TIMEOUT):
            if command == b"D\n":
                response = await self._serial.readexactly(3)
            elif command == b"X\n":
                response = await self._serial.readuntil(b"\n")
            else:
                response = await self._serial.readuntil(b"\r")

        await asyncio.sleep(_INTER_COMMAND_DELAY)

        if not response:
            raise MustProtocolError(f"Empty response to {command!r}")
        return response

    # -- response parsers -------------------------------------------------
    # Each takes (raw_response, values_so_far) and returns new keys to
    # merge into `values`. `values_so_far` lets the X parser see the
    # is_charging flag decoded by the preceding D command.

    @staticmethod
    def _parse_f(response: bytes, _values: dict[str, Any]) -> dict[str, Any]:
        data = response.decode("utf-8")
        return {
            "rating_voltage": float(data[1:6]),
            "rating_current": float(data[7:10]),
            "nominal_battery_voltage": float(data[11:16]),
            "nominal_frequency": float(data[17:21]),
        }

    @staticmethod
    def _parse_q1(response: bytes, _values: dict[str, Any]) -> dict[str, Any]:
        data = response.decode("utf-8")

        # BCD-like temperature decode (bugfix #1) -- see module docstring.
        temp_field = data[33:37]
        tens_digit = ord(temp_field[0]) - 48
        fraction = float(temp_field[1:4])
        ups_temperature = tens_digit * 10 + fraction
        if not (_TEMPERATURE_MIN_PLAUSIBLE <= ups_temperature <= _TEMPERATURE_MAX_PLAUSIBLE):
            LOGGER.warning(
                "EP30 Pro reported an implausible temperature %.1f°C (raw field %r); "
                "the ASCII protocol has no checksum, so this may be a mis-synced read",
                ups_temperature,
                temp_field,
            )

        # Full working_status enum (bugfix #2) -- see module docstring.
        working_status_code = ord(data[40:41])
        working_status = WORKING_STATUS_MAP.get(
            working_status_code, f"unknown_code_{working_status_code}"
        )

        return {
            "input_voltage": float(data[1:6]),
            "fault_voltage": float(data[7:12]),
            "output_voltage": float(data[13:18]),
            "load_level": int(data[19:22]),
            "output_frequency": float(data[23:27]),
            "battery_voltage": float(data[28:32]),
            "ups_temperature": ups_temperature,
            "utility_fail": int(data[38:39]),
            "battery_low": int(data[39:40]),
            "working_status": working_status,
            "working_status_code": working_status_code,
            "ups_failed": int(data[41:42]),
            "ups_type": int(data[42:43]),
            "test_in_progress": int(data[43:44]),
            "shutdown_active": int(data[44:45]),
            "beeper_on": int(data[45:46]),
        }

    @staticmethod
    def _parse_g(response: bytes, _values: dict[str, Any]) -> dict[str, Any]:
        raw = response.decode("utf-8", errors="replace").strip("\r\n")
        # Ported from the C# reference's `.Contains("Over Volage")` special
        # case (sic -- likely an old-firmware typo for "Over Voltage").
        # Confirm against real hardware before relying on this (see README
        # open items); harmless no-op if the substring never appears.
        fault_state = "Battery Over Voltage" if "Over Volage" in raw else raw
        return {"fault_state": fault_state}

    @staticmethod
    def _parse_d(response: bytes, _values: dict[str, Any]) -> dict[str, Any]:
        is_charging = response.decode("utf-8", errors="replace") == "ACK"
        return {"is_charging": is_charging}

    @staticmethod
    def _parse_x(response: bytes, values: dict[str, Any]) -> dict[str, Any]:
        parts = response.decode("utf-8").split()
        if len(parts) != 4:
            raise MustProtocolError(f"Expected four X response fields, got {len(parts)}")
        charging_value1 = float(int(parts[0], 16))
        charging_value2 = float(int(parts[1], 16))
        charging_value3 = float(int(parts[2], 16))
        charging_value4 = float(int(parts[3], 16))

        is_charging = bool(values.get("is_charging", False))
        charging_current = charging_value1 if is_charging else 0.0

        return {
            "charging_value1": charging_value1,
            "charging_value2": charging_value2,
            "charging_value3": charging_value3,
            "charging_value4": charging_value4,
            "charging_current": charging_current,
        }
