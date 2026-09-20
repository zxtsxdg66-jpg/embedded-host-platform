"""Device: generic device abstraction (identity, capability descriptor,
connection/occupancy state).

Not bound to any specific sensor, controlled object, or MCU model.
See src/device/README.md for module scope.
"""

from device.capability import ChannelDescriptor, CommandDescriptor, DeviceCapability
from device.interface import DeviceInterface
from device.metadata import DeviceMetadata
from device.model import Device
from device.remote import RemoteDevice
from device.simulator import (
    ConstantValueGenerator,
    RandomValueGenerator,
    SequenceValueGenerator,
    SimulatedChannel,
    SimulatorDevice,
    ValueGenerator,
)
from device.state import ConnectionState, DeviceStatus, OccupancyState

__all__ = [
    "ChannelDescriptor",
    "CommandDescriptor",
    "DeviceCapability",
    "DeviceInterface",
    "DeviceMetadata",
    "Device",
    "RemoteDevice",
    "ConnectionState",
    "DeviceStatus",
    "OccupancyState",
    "ConstantValueGenerator",
    "RandomValueGenerator",
    "SequenceValueGenerator",
    "SimulatedChannel",
    "SimulatorDevice",
    "ValueGenerator",
]
