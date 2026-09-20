import pytest

from core.exceptions import StateTransitionError, ValidationError
from device.capability import CommandDescriptor, DeviceCapability
from device.interface import DeviceInterface
from device.remote import RemoteDevice
from device.state import ConnectionState, DeviceStatus


def test_remote_device_requires_non_empty_id() -> None:
    with pytest.raises(ValidationError):
        RemoteDevice(device_id="")


def test_remote_device_defaults() -> None:
    device = RemoteDevice(device_id="mcu-1")
    assert device.device_id == "mcu-1"
    assert device.status.connection_state is ConnectionState.DISCONNECTED
    assert device.capability == DeviceCapability()


def test_remote_device_satisfies_device_interface() -> None:
    device = RemoteDevice(device_id="mcu-1")
    assert hasattr(device, "device_id")
    assert hasattr(device, "capability")
    assert hasattr(device, "status")
    assert isinstance(device, DeviceInterface)


def test_remote_device_has_no_data_generation_methods() -> None:
    """RemoteDevice must never generate its own data -- see module docstring."""
    device = RemoteDevice(device_id="mcu-1")
    assert not hasattr(device, "generate")
    assert not hasattr(device, "generate_all")


def test_remote_device_capability_supplied_by_caller() -> None:
    capability = DeviceCapability(commands=(CommandDescriptor(command_type="PING"),))
    device = RemoteDevice(device_id="mcu-1", capability=capability)
    assert device.capability.supports_command("PING")


def test_remote_device_with_status_is_immutable() -> None:
    device = RemoteDevice(device_id="mcu-1")
    updated = device.with_status(
        device.status.with_connection(ConnectionState.CONNECTED)
    )

    assert updated.status.connection_state is ConnectionState.CONNECTED
    assert device.status.connection_state is ConnectionState.DISCONNECTED


def test_remote_device_occupy_and_release_are_immutable() -> None:
    device = RemoteDevice(device_id="mcu-1")

    occupied = device.occupy("client-1")
    assert occupied.status.occupant == "client-1"
    assert device.status.occupant is None

    released = occupied.release("client-1")
    assert released.status.occupant is None


def test_remote_device_occupy_twice_raises() -> None:
    device = RemoteDevice(device_id="mcu-1").occupy("client-1")
    with pytest.raises(StateTransitionError):
        device.occupy("client-2")


def test_remote_device_can_be_constructed_already_connected() -> None:
    """Once a future SerialChannel-backed read loop exists, whatever wires it
    up can hand RemoteDevice a CONNECTED status directly via with_status()."""
    device = RemoteDevice(
        device_id="mcu-1",
        status=DeviceStatus(connection_state=ConnectionState.CONNECTED),
    )
    assert device.status.connection_state is ConnectionState.CONNECTED
