import pytest

from core.exceptions import ValidationError
from device.capability import ChannelDescriptor, CommandDescriptor, DeviceCapability


def test_command_descriptor_rejects_empty_type() -> None:
    with pytest.raises(ValidationError):
        CommandDescriptor(command_type="")


def test_channel_descriptor_rejects_empty_id() -> None:
    with pytest.raises(ValidationError):
        ChannelDescriptor(channel_id="")


def test_capability_supports_command_and_channel() -> None:
    capability = DeviceCapability(
        commands=(CommandDescriptor(command_type="READ_STATUS"),),
        channels=(ChannelDescriptor(channel_id="ch1"),),
    )
    assert capability.supports_command("READ_STATUS")
    assert not capability.supports_command("UNKNOWN")
    assert capability.has_channel("ch1")
    assert not capability.has_channel("ch2")


def test_empty_capability_supports_nothing() -> None:
    capability = DeviceCapability()
    assert not capability.supports_command("ANY")
    assert not capability.has_channel("ANY")
