"""Common exception hierarchy shared by all layers.

Kept intentionally small and generic: exceptions here describe *kinds* of
failure (validation, invalid state transition, missing entity, timeout),
never a specific device, sensor, or protocol concept.
"""

from __future__ import annotations


class PlatformError(Exception):
    """Base class for all platform-defined exceptions."""


class ValidationError(PlatformError):
    """Raised when input data fails validation."""


class StateTransitionError(PlatformError):
    """Raised when an invalid state transition is attempted."""


class NotFoundError(PlatformError):
    """Raised when a referenced entity (device, subscription, command, ...)
    does not exist."""


class OperationTimeoutError(PlatformError):
    """Raised when an operation exceeds its allotted time budget."""
