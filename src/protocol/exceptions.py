"""Protocol-layer exception hierarchy.

Mirrors the pattern used across the codebase (device/service exceptions
extend core.exceptions.PlatformError): protocol errors describe *kinds* of
framing failure, never a specific device, sensor, or transport.
"""

from __future__ import annotations

from core.exceptions import PlatformError


class ProtocolError(PlatformError):
    """Base class for all Protocol Layer errors."""


class FrameValueError(ProtocolError):
    """Raised when a Frame field value is outside its valid range."""


class FrameSyncError(ProtocolError):
    """Raised when the frame header/sync marker is missing or corrupted."""


class FrameLengthError(ProtocolError):
    """Raised when declared and actual byte lengths of a frame disagree."""


class ChecksumError(ProtocolError):
    """Raised when a frame's CRC does not match its computed checksum."""
