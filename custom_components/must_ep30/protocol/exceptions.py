"""Exceptions raised by MUST device protocol clients."""

from __future__ import annotations


class MustConnectionError(Exception):
    """Raised when the transport (serial port / TCP / UDP) cannot be opened or used."""


class MustProtocolError(Exception):
    """Raised when a response is missing, malformed, or fails validation.

    Covers empty/short reads, unparseable ASCII frames, and Modbus error
    responses (``result.isError()`` or a short register list). Since neither
    the ASCII protocol nor this Modbus register block carries a checksum,
    callers should treat any parse failure as suspect rather than guessing.
    """
