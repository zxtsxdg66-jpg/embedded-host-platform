"""API: interface surface for external/remote callers.

Serves multi-client and future gateway-mode access.

Currently implemented (phase 1): ApiInterface (the abstract entry point)
and LocalApi (its in-process implementation, a thin facade over
application.ApplicationRuntime), plus the API exception hierarchy. A
gateway-mode ApiInterface implementation is not yet implemented.
See src/api/README.md for the full module scope.
"""

from api.exceptions import (
    ApiError,
    CommandAuthorityError,
    CommandNotFoundError,
    DeviceNotFoundError,
)
from api.interface import ApiInterface
from api.local_api import LocalApi

__all__ = [
    "ApiInterface",
    "LocalApi",
    "ApiError",
    "DeviceNotFoundError",
    "CommandNotFoundError",
    "CommandAuthorityError",
]
