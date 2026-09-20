"""Core: cross-cutting infrastructure shared by all layers
(logging, config, exceptions, common types).

Currently implemented: common exceptions, timestamp utilities, shared id
type aliases. Logging/config are not yet implemented. See src/core/README.md
for the full module scope.
"""

from core.exceptions import (
    NotFoundError,
    OperationTimeoutError,
    PlatformError,
    StateTransitionError,
    ValidationError,
)
from core.models import ChannelId, ClientId, CommandType, DeviceId
from core.timestamps import from_iso8601, monotonic_ms, now_utc, to_iso8601

__all__ = [
    "PlatformError",
    "ValidationError",
    "StateTransitionError",
    "NotFoundError",
    "OperationTimeoutError",
    "DeviceId",
    "ClientId",
    "ChannelId",
    "CommandType",
    "now_utc",
    "to_iso8601",
    "from_iso8601",
    "monotonic_ms",
]
