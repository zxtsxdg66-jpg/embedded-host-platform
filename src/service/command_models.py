"""Control instruction model exchanged between clients and the Service Layer.

Corresponds to docs/02_Architecture/Core_Service_Design.md Section 3
(Control instruction model design), including the command lifecycle
(pending -> success / failed / timeout) described there.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any
from uuid import uuid4

from core.models import ClientId, CommandType, DeviceId
from core.timestamps import now_utc


class CommandStatus(Enum):
    """Lifecycle status of a submitted command."""

    PENDING = auto()
    SUCCESS = auto()
    FAILED = auto()
    TIMEOUT = auto()


@dataclass(frozen=True)
class Command:
    """A single control instruction targeting one device."""

    device_id: DeviceId
    command_type: CommandType
    origin: ClientId
    parameters: Mapping[str, Any] = field(default_factory=dict)
    command_id: str = field(default_factory=lambda: str(uuid4()))
    issued_at: datetime = field(default_factory=now_utc)


@dataclass(frozen=True)
class CommandResult:
    """Current outcome of a previously submitted command."""

    command_id: str
    status: CommandStatus = CommandStatus.PENDING
    message: str = ""
    completed_at: datetime | None = None
