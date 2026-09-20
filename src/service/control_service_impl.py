"""Concrete ControlService: occupancy bookkeeping + command dispatch via a transport.

Corresponds to docs/02_Architecture/Core_Service_Design.md Section 4
("command dispatch and tracking", "multi-client session and access
control") and Section 7's default rule ("共享读、独占写"): submit_command()
refuses to dispatch unless the caller currently holds the device via
acquire().

This module deliberately does not import protocol/ or communication/
directly -- it depends only on the narrow :class:`CommandTransport`
contract, so it stays agnostic to *how* a command reaches a device. Phase
1 supplies that transport from application/manager.py (Frame encode/decode
over a CommunicationChannel); a later phase (e.g. a network gateway) can
supply a different one without changing this module.
"""

from __future__ import annotations

from typing import Protocol

from core.exceptions import NotFoundError, StateTransitionError
from core.models import ClientId, DeviceId
from service.command_models import Command, CommandResult
from service.control_service import ControlService


class CommandTransport(Protocol):
    """The narrow contract InMemoryControlService dispatches commands through."""

    def deliver(self, command: Command) -> CommandResult:
        """Deliver ``command`` to its target device and return the final result."""


class InMemoryControlService(ControlService):
    """In-memory ControlService: exclusive-write occupancy + transport dispatch."""

    def __init__(self, transport: CommandTransport) -> None:
        self._transport = transport
        self._owner: dict[DeviceId, ClientId] = {}
        self._results: dict[str, CommandResult] = {}

    def acquire(self, device_id: DeviceId, client_id: ClientId) -> bool:
        current_owner = self._owner.get(device_id)
        if current_owner is not None and current_owner != client_id:
            return False
        self._owner[device_id] = client_id
        return True

    def release(self, device_id: DeviceId, client_id: ClientId) -> None:
        if self._owner.get(device_id) == client_id:
            del self._owner[device_id]

    def get_owner(self, device_id: DeviceId) -> ClientId | None:
        """Return the client currently holding ``device_id``, if any.

        Not part of the ControlService ABC -- an implementation-specific
        query used by application.runtime.ApplicationRuntime to build a
        DeviceStatusView, since occupancy is authoritatively tracked here
        (not on the Device model itself; see that module's docstring).
        """
        return self._owner.get(device_id)

    def submit_command(self, command: Command) -> CommandResult:
        owner = self._owner.get(command.device_id)
        if owner != command.origin:
            raise StateTransitionError(
                f"client {command.origin!r} does not hold command authority "
                f"over device {command.device_id!r} (current owner: {owner!r})"
            )
        result = self._transport.deliver(command)
        self._results[result.command_id] = result
        return result

    def get_result(self, command_id: str) -> CommandResult:
        try:
            return self._results[command_id]
        except KeyError as exc:
            raise NotFoundError(f"unknown command_id: {command_id!r}") from exc
