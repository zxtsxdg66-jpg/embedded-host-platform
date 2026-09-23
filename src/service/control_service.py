"""Control service base interface: device occupancy and command dispatch.

Corresponds to docs/architecture.md
(Service Layer responsibilities -- "command dispatch and tracking",
"multi-client session and access control") and Section 7 (the default
"shared read, exclusive write" rule: ``acquire``/``release`` gate exclusive
command authority, independent of the read-only data subscriptions
provided by :class:`service.data_service.DataService`).

This module defines the contract only; no concrete implementation is
provided here, and none of it is bound to any specific device.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import ClientId, DeviceId
from service.command_models import Command, CommandResult


class ControlService(ABC):
    """Base interface for device occupancy control and command dispatch."""

    @abstractmethod
    def acquire(self, device_id: DeviceId, client_id: ClientId) -> bool:
        """Attempt to acquire exclusive command authority over ``device_id``.

        Returns True if ``client_id`` now holds (or already held) the
        device, False if another client currently holds it.
        """

    @abstractmethod
    def release(self, device_id: DeviceId, client_id: ClientId) -> None:
        """Release command authority previously acquired by ``client_id``."""

    @abstractmethod
    def submit_command(self, command: Command) -> CommandResult:
        """Submit ``command`` for dispatch, returning its initial (pending) result."""

    @abstractmethod
    def get_result(self, command_id: str) -> CommandResult:
        """Retrieve the current result/status of a previously submitted command."""
