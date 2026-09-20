"""Business-level data model produced by the Service Layer.

Corresponds to docs/02_Architecture/Core_Service_Design.md Section 2
(Data model design). A `DataPoint` is deliberately generic -- it carries no
physical-quantity semantics (no "temperature", "voltage", ...); channel
meaning is defined by a device's capability descriptor, not by this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.models import ChannelId, DeviceId
from core.timestamps import now_utc


@dataclass(frozen=True)
class DataPoint:
    """A single, generic reading reported by a device on one of its channels."""

    device_id: DeviceId
    channel: ChannelId
    value: Any
    timestamp: datetime = field(default_factory=now_utc)
    valid: bool = True
