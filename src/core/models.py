"""Shared primitive types used across device/service (and future api/ui) modules.

These are plain string type aliases rather than a shared entity model --
`core` must not know what a "device" or a "command" is, that knowledge
belongs to the `device` and `service` modules. Aliasing improves readability
and gives static type checkers something more specific than a bare `str`
to check call sites against.
"""

from __future__ import annotations

from typing import TypeAlias

DeviceId: TypeAlias = str
"""Unique identifier of a device, corresponding to the
Protocol Layer's device-id field."""

ClientId: TypeAlias = str
"""Identifier of a client/session (PC or Android) interacting with the platform."""

ChannelId: TypeAlias = str
"""Identifier of a data channel reported by a device."""

CommandType: TypeAlias = str
"""Identifier of a command type understood by a device, per its
capability descriptor."""
