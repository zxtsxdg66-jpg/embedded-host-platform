"""API-layer exception hierarchy.

Mirrors the pattern used across the codebase: each layer defines its own
base exception, reusing core.exceptions for kinds of failure that are
already generic enough (this module does not redefine "not found" or
"invalid state" as concepts). What this module adds is *specificity* at
the facade boundary: ApplicationRuntime/service raise a single generic
core.exceptions.NotFoundError for several different missing-entity cases
(unknown device, unknown command), which is fine internally but not
precise enough for a facade meant to be consumed by external clients
(a future PyQt6 UI, an Android bridge) that want to branch on "which kind
of not-found is this" without parsing error message text.
"""

from __future__ import annotations

from core.exceptions import PlatformError


class ApiError(PlatformError):
    """Base class for all API Layer errors."""


class DeviceNotFoundError(ApiError):
    """Raised when a request references a device_id that is not registered."""


class CommandNotFoundError(ApiError):
    """Raised when a request references a command_id with no known result."""


class CommandAuthorityError(ApiError):
    """Raised when a client submits a command for a device it does not
    currently hold exclusive command authority over (see
    docs/architecture.md)."""


class CommandDeliveryError(ApiError):
    """Raised when a command was sent but never acknowledged in time.

    Only reachable in Hardware mode: DeviceManager.deliver()'s Hardware
    path waits for a real device response instead of fabricating one
    (see application/manager.py's _await_device_ack), so a
    disconnected/unresponsive device surfaces here as a clean, catchable
    error instead of an unhandled exception reaching the UI layer.
    """
