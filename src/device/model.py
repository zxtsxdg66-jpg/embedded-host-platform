"""Device model: the concrete, immutable value object implementing DeviceInterface.

Corresponds to docs/architecture.md
(Device abstraction) as a whole. Not bound to any specific sensor,
controlled object, or MCU model -- ``capability`` and ``metadata`` are the
only places device-specific information may appear, and both are opaque,
data-driven descriptions rather than hardcoded device types.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from core.exceptions import ValidationError
from core.models import ClientId, DeviceId
from device.capability import DeviceCapability
from device.metadata import DeviceMetadata
from device.state import ConnectionState, DeviceStatus


@dataclass(frozen=True)
class Device:
    """Immutable representation of a single device known to the platform."""

    device_id: DeviceId
    capability: DeviceCapability = field(default_factory=DeviceCapability)
    status: DeviceStatus = field(default_factory=DeviceStatus)
    metadata: DeviceMetadata = field(default_factory=DeviceMetadata)

    def __post_init__(self) -> None:
        if not self.device_id:
            raise ValidationError("device_id must not be empty")

    @property
    def is_connected(self) -> bool:
        return self.status.connection_state is ConnectionState.CONNECTED

    def with_status(self, status: DeviceStatus) -> Device:
        """Return a new Device with its status replaced."""
        return replace(self, status=status)

    def occupy(self, client_id: ClientId) -> Device:
        """Return a new Device exclusively held by ``client_id``."""
        return self.with_status(self.status.occupy(client_id))

    def release(self, client_id: ClientId) -> Device:
        """Return a new Device released from ``client_id``'s occupancy."""
        return self.with_status(self.status.release(client_id))
