"""Device state model: connection state and occupancy state.

Corresponds to docs/architecture.md
("Connection State", "Occupancy State") and Section 7 (multi-client access
rules: "shared read, exclusive write"). `DeviceStatus` is an immutable value
object -- transitions return a new instance rather than mutating in place,
so a `Device` holding a stale reference cannot silently observe another
client's change.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum, auto

from core.exceptions import StateTransitionError
from core.models import ClientId
from core.timestamps import now_utc


class ConnectionState(Enum):
    """Reachability of the device, as observed via the Communication Layer."""

    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    ERROR = auto()


class OccupancyState(Enum):
    """Whether a client currently holds exclusive command authority over the device."""

    FREE = auto()
    OCCUPIED = auto()


@dataclass(frozen=True)
class DeviceStatus:
    """Immutable snapshot of a device's connection and occupancy state."""

    connection_state: ConnectionState = ConnectionState.DISCONNECTED
    occupancy_state: OccupancyState = OccupancyState.FREE
    occupant: ClientId | None = None
    updated_at: datetime = field(default_factory=now_utc)

    def __post_init__(self) -> None:
        if self.occupancy_state is OccupancyState.OCCUPIED and self.occupant is None:
            raise StateTransitionError("occupied status requires an occupant")
        if self.occupancy_state is OccupancyState.FREE and self.occupant is not None:
            raise StateTransitionError("free status must not carry an occupant")

    def with_connection(self, connection_state: ConnectionState) -> DeviceStatus:
        """Return a new status reflecting an updated connection state."""
        return replace(self, connection_state=connection_state, updated_at=now_utc())

    def occupy(self, client_id: ClientId) -> DeviceStatus:
        """Return a new status with the device exclusively held by ``client_id``.

        Raises StateTransitionError if the device is already occupied by
        anyone (including the same client) -- callers must release first.
        """
        if self.occupancy_state is OccupancyState.OCCUPIED:
            raise StateTransitionError(f"device already occupied by {self.occupant!r}")
        return replace(
            self,
            occupancy_state=OccupancyState.OCCUPIED,
            occupant=client_id,
            updated_at=now_utc(),
        )

    def release(self, client_id: ClientId) -> DeviceStatus:
        """Return a new status with the device freed, if ``client_id``
        is the current occupant."""
        if self.occupancy_state is OccupancyState.FREE:
            raise StateTransitionError("device is already free")
        if self.occupant != client_id:
            raise StateTransitionError(
                f"device is occupied by {self.occupant!r}, not {client_id!r}"
            )
        return replace(
            self,
            occupancy_state=OccupancyState.FREE,
            occupant=None,
            updated_at=now_utc(),
        )
