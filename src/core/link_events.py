"""Value types describing what happens on a device link.

Moved here from ``application/link_monitor.py`` on 2026-09-23. They cross the
``api`` boundary -- ``ApiInterface.get_link_statistics()`` returns one,
``subscribe_link_events()`` delivers the other -- so the presentation ends
must be able to name them, and a presentation end may import ``api``,
``core`` and the shared model types, never ``application``. The monitor that
produces these values stays in ``application``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

FRAME = "frame"
"""A frame that decoded, was addressed to this receiver and carried data."""
RESYNC = "resync"
"""The byte stream did not start with a frame header; bytes were skipped."""
CHECKSUM_ERROR = "checksum_error"
"""A frame whose CRC did not match."""
DECODE_ERROR = "decode_error"
"""Any other malformed frame (bad header, inconsistent length)."""
IGNORED = "ignored"
"""A well-formed frame not meant for the receiver (other id, not a report)."""
PAYLOAD_ERROR = "payload_error"
"""A well-formed data frame whose payload could not be read."""


@dataclass(frozen=True)
class LinkEvent:
    """One thing that happened on the link.

    ``raw`` is the frame's bytes exactly as extracted from the stream (empty
    for a resync, which has no frame). ``device_id``/``command_type``/
    ``payload`` are filled only when the frame decoded.
    """

    kind: str
    timestamp: datetime
    raw: bytes = b""
    device_id: int | None = None
    command_type: int | None = None
    payload: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class LinkStatistics:
    """Counters since the monitor was created.

    ``active`` is False until a receiver has been attached -- in Simulator
    mode there is no byte stream at all, and a client should say so rather
    than show a reassuring row of zeros.
    """

    active: bool
    bytes_received: int = 0
    frames: int = 0
    resyncs: int = 0
    checksum_errors: int = 0
    decode_errors: int = 0
    ignored: int = 0
    payload_errors: int = 0
    last_frame_at: datetime | None = None


LinkEventCallback = Callable[[LinkEvent], None]
