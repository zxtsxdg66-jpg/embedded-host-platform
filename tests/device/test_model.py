import pytest

from core.exceptions import ValidationError
from device.capability import CommandDescriptor, DeviceCapability
from device.model import Device
from device.state import ConnectionState


def test_device_requires_non_empty_id() -> None:
    with pytest.raises(ValidationError):
        Device(device_id="")


def test_device_defaults() -> None:
    device = Device(device_id="dev-1")
    assert device.device_id == "dev-1"
    assert not device.is_connected


def test_device_occupy_and_release_are_immutable() -> None:
    device = Device(device_id="dev-1")
    occupied = device.occupy("client-1")
    assert occupied.status.occupant == "client-1"

    released = occupied.release("client-1")
    assert released.status.occupant is None

    # original instance must remain untouched
    assert device.status.occupant is None


def test_device_capability_lookup() -> None:
    capability = DeviceCapability(commands=(CommandDescriptor(command_type="PING"),))
    device = Device(device_id="dev-1", capability=capability)
    assert device.capability.supports_command("PING")


def test_device_with_status_updates_connection() -> None:
    device = Device(device_id="dev-1")
    updated = device.with_status(
        device.status.with_connection(ConnectionState.CONNECTED)
    )
    assert updated.is_connected
    assert not device.is_connected
