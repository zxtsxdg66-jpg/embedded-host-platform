"""Device capability descriptor: what commands/channels a device supports.

Corresponds to docs/02_Architecture/Core_Service_Design.md Section 1.2
("Device Capability Descriptor"). Deliberately generic -- a command type or
channel id is an opaque string here; their business meaning is defined by
whoever describes a concrete device (device profile / future capability
negotiation), never by this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.exceptions import ValidationError
from core.models import ChannelId, CommandType


@dataclass(frozen=True)
class CommandDescriptor:
    """Describes a single command type a device claims to support."""

    command_type: CommandType
    description: str = ""

    def __post_init__(self) -> None:
        if not self.command_type:
            raise ValidationError("command_type must not be empty")


@dataclass(frozen=True)
class ChannelDescriptor:
    """Describes a single data channel a device claims to report."""

    channel_id: ChannelId
    description: str = ""

    def __post_init__(self) -> None:
        if not self.channel_id:
            raise ValidationError("channel_id must not be empty")


@dataclass(frozen=True)
class DeviceCapability:
    """Immutable collection of the command types and channels a device supports."""

    commands: tuple[CommandDescriptor, ...] = field(default_factory=tuple)
    channels: tuple[ChannelDescriptor, ...] = field(default_factory=tuple)

    def supports_command(self, command_type: CommandType) -> bool:
        return any(command.command_type == command_type for command in self.commands)

    def has_channel(self, channel_id: ChannelId) -> bool:
        return any(channel.channel_id == channel_id for channel in self.channels)
