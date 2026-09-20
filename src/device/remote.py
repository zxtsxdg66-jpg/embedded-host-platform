"""RemoteDevice: passive representation of an external, real device pending
Communication Layer integration (e.g. a future STM32/MSPM0 MCU over UART).

Corresponds to docs/02_Architecture/Core_Service_Design.md Section 1
(Device abstraction) and the "Hardware 模式" described in
docs/05_Test/Hardware_Simulation_Mode.md.

Unlike device.simulator.SimulatorDevice, RemoteDevice never generates data
itself -- a real device produces its own data over its own transport.
RemoteDevice only carries the Service Layer's view of that device's
identity, capability, and status; it has:

- no data-generation methods (no ``generate``/``generate_all``)
- no serial/UART logic of any kind
- no dependency on ``communication`` (not even the abstract
  ``CommunicationChannel``) -- how bytes eventually reach a real device
  (via a future SerialChannel-backed read loop) is entirely outside this
  class's concern, mirroring Communication Layer's own "only moves bytes,
  never knows about devices" boundary from the other direction

Not bound to any specific MCU model: ``capability`` is supplied by the
caller (from a device profile / future capability negotiation), never
hardcoded here.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from core.exceptions import ValidationError
from core.models import ClientId, DeviceId
from device.capability import DeviceCapability
from device.state import DeviceStatus


@dataclass(frozen=True)
class RemoteDevice:
    """Immutable device_id/capability/status record for an external real device.

    Structurally satisfies device.interface.DeviceInterface
    (device_id/capability/status), exactly like device.model.Device, but is
    a distinct type so DeviceManager and callers can tell "this is a real
    device slot, not a simulator" apart from device.simulator.SimulatorDevice.
    """

    device_id: DeviceId
    capability: DeviceCapability = field(default_factory=DeviceCapability)
    status: DeviceStatus = field(default_factory=DeviceStatus)

    def __post_init__(self) -> None:
        if not self.device_id:
            raise ValidationError("device_id must not be empty")

    def with_status(self, status: DeviceStatus) -> RemoteDevice:
        """Return a new RemoteDevice with its status replaced.

        Useful once a future Communication Layer integration needs to
        update connection state (e.g. DISCONNECTED -> CONNECTED after a
        SerialChannel.connect() succeeds) -- RemoteDevice itself never
        calls SerialChannel or any other communication code.
        """
        return replace(self, status=status)

    def occupy(self, client_id: ClientId) -> RemoteDevice:
        """Return a new RemoteDevice exclusively held by ``client_id``."""
        return self.with_status(self.status.occupy(client_id))

    def release(self, client_id: ClientId) -> RemoteDevice:
        """Return a new RemoteDevice released from ``client_id``'s occupancy."""
        return self.with_status(self.status.release(client_id))
