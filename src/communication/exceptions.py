"""Communication-layer exception hierarchy.

Mirrors the pattern used across the codebase (device/service/protocol
exceptions all extend core.exceptions.PlatformError): these describe
*kinds* of transport-level failure only, never protocol or business
content -- Communication Layer does not parse what it carries.
"""

from __future__ import annotations

from core.exceptions import PlatformError


class CommunicationError(PlatformError):
    """Base class for all Communication Layer errors."""


class NotConnectedError(CommunicationError):
    """Raised when send()/receive() is attempted on a channel that isn't connected."""


class AlreadyConnectedError(CommunicationError):
    """Raised when connect() is called on a channel that is already connected."""


class SerialPortNotFoundError(CommunicationError):
    """Raised when connect() targets a serial port that does not currently exist."""


class SerialConnectionError(CommunicationError):
    """Raised when a serial port exists but could not be opened (permission
    denied, already in use, driver failure, ...)."""


class SerialReadTimeoutError(CommunicationError):
    """Raised when a serial read fails or times out at the OS/driver level."""


class SerialWriteError(CommunicationError):
    """Raised when a serial write fails, including exceeding its write timeout."""
