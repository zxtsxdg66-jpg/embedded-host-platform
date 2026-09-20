"""Timestamp utilities: timezone-aware wall-clock time and monotonic elapsed time.

All wall-clock timestamps used across the platform must be timezone-aware
UTC datetimes -- naive datetimes are rejected rather than silently assumed
to be UTC, since a silent assumption here would be a platform-wide source
of subtle bugs once PC and Android clients run in different timezones.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone


def now_utc() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def to_iso8601(moment: datetime) -> str:
    """Serialize a timezone-aware datetime to an ISO 8601 string (UTC)."""
    if moment.tzinfo is None:
        raise ValueError("moment must be timezone-aware")
    return moment.astimezone(timezone.utc).isoformat()


def from_iso8601(text: str) -> datetime:
    """Parse an ISO 8601 string into a timezone-aware UTC datetime."""
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        raise ValueError("text must include timezone information")
    return moment.astimezone(timezone.utc)


def monotonic_ms() -> int:
    """Return a monotonic millisecond counter, suitable for measuring elapsed time.

    Not a wall-clock timestamp -- only valid for computing differences
    within a single process run (e.g. timeout tracking for commands).
    """
    return int(time.monotonic() * 1000)
