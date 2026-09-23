"""Device metadata: descriptive information that does not affect protocol parsing.

Corresponds to docs/architecture.md
("Device Metadata"). Deliberately excludes any sensor/controlled-object/MCU
identification beyond a free-form ``extra`` mapping -- such details, if
ever needed, belong to a device profile configuration, not to this model.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class DeviceMetadata:
    """Optional, display-only information about a device."""

    name: str = ""
    connected_at: datetime | None = None
    extra: Mapping[str, str] = field(default_factory=dict)
