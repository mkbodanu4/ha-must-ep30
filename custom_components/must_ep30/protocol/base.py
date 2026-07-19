"""Shared protocol client interface for MUST inverter/charger devices.

Both device profiles (EP30 Pro over an ASCII serial protocol, EP3000 Plus
over Modbus RTU/TCP/UDP) implement :class:`MustDeviceClient`. The
coordinator and config flow only ever talk to this interface, which keeps
protocol-specific code isolated to ``protocol/ascii_serial.py`` and
``protocol/modbus.py``.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from homeassistant.helpers.typing import StateType


@dataclass(slots=True)
class MustPollResult:
    """One successful poll cycle's worth of decoded sensor values.

    ``values`` maps a sensor key (e.g. ``"battery_voltage"``) to its decoded,
    scaled value ready to hand to an entity. ``raw`` optionally retains the
    last raw bytes/registers for ``diagnostics.py``. A key that failed to
    decode on a given cycle (partial-failure tolerance, see
    ``protocol/ascii_serial.py``) is simply absent from ``values`` rather
    than present with a placeholder.
    """

    values: dict[str, StateType]
    raw: dict[str, Any] = field(default_factory=dict)


class MustDeviceClient(abc.ABC):
    """Transport+protocol client for one physical MUST device."""

    @abc.abstractmethod
    async def async_connect(self) -> None:
        """Open the underlying transport. Safe to call again after a close."""

    @abc.abstractmethod
    async def async_close(self) -> None:
        """Close the underlying transport."""

    @abc.abstractmethod
    async def async_fetch(self) -> MustPollResult:
        """Perform one full poll cycle and return decoded values.

        Implementations must raise :class:`~.exceptions.MustConnectionError`
        or :class:`~.exceptions.MustProtocolError` on failure rather than
        letting transport-library-specific exceptions escape, so the
        coordinator can map failures to ``UpdateFailed`` uniformly.
        """
