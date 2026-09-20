"""Device abstract interface: the structural contract the Service Layer relies on.

Defined as a `typing.Protocol` rather than an ABC base class: the Service
Layer should be able to treat anything that structurally looks like a
device (has an id, a capability descriptor, a status) as one, including
future device-simulator implementations, without those implementations
being forced to inherit from a concrete base class.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.models import DeviceId
from device.capability import DeviceCapability
from device.state import DeviceStatus


@runtime_checkable
class DeviceInterface(Protocol):
    """Structural contract satisfied by anything the platform treats as a device."""

    @property
    def device_id(self) -> DeviceId: ...

    @property
    def capability(self) -> DeviceCapability: ...

    @property
    def status(self) -> DeviceStatus: ...
