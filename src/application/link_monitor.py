"""LinkMonitor: what the serial link is doing, made visible.

Added 2026-09-23 for the web console's protocol inspector
(docs/decisions/08-web.md).

Until now the link's health existed only as two integers inside
:class:`~application.hardware_runtime.HardwareDeviceReceiver`
(``error_count`` / ``ignored_frame_count``). The stability report could
state "frame sync errors: 0" only because a dedicated capture script read them;
the running system itself never showed the fact. This module is where the
receiver reports each frame and each anomaly, so a presentation end can.

**It listens; it does not decide.** Every judgement -- where a frame
starts, whether its CRC holds, whether it is addressed to us -- is still
made by the receiver and the protocol layer, exactly as before. A receiver
built without a monitor behaves byte-for-byte as it always did.

Thread-safety: the receiver reports from the runtime's driver thread while
a gateway request may read :meth:`statistics` from a server thread, so
counters are guarded by a lock. Subscribers are called on the reporting
thread and must not block (the gateway's EventHub.publish does not).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime

from core.link_events import (
    CHECKSUM_ERROR,
    DECODE_ERROR,
    FRAME,
    IGNORED,
    PAYLOAD_ERROR,
    RESYNC,
    LinkEvent,
    LinkEventCallback,
    LinkStatistics,
)
from core.timestamps import now_utc

__all__ = [
    "CHECKSUM_ERROR",
    "DECODE_ERROR",
    "FRAME",
    "IGNORED",
    "PAYLOAD_ERROR",
    "RESYNC",
    "LinkEvent",
    "LinkEventCallback",
    "LinkMonitor",
    "LinkStatistics",
]


@dataclass
class _Counters:
    bytes_received: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    last_frame_at: datetime | None = None


class LinkMonitor:
    """Collects link events from a receiver and fans them out."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = False
        self._counters = _Counters()
        self._subscribers: list[LinkEventCallback] = []

    # -- receiver side ----------------------------------------------------

    def attach(self) -> None:
        """Mark that a byte-stream receiver now reports here."""
        with self._lock:
            self._active = True

    def record_bytes(self, count: int) -> None:
        with self._lock:
            self._counters.bytes_received += count

    def record(self, event: LinkEvent) -> None:
        """Count one event and hand it to every subscriber. Never raises."""
        with self._lock:
            counts = self._counters.counts
            counts[event.kind] = counts.get(event.kind, 0) + 1
            if event.kind == FRAME:
                self._counters.last_frame_at = event.timestamp
            subscribers = list(self._subscribers)
        for callback in subscribers:
            try:
                callback(event)
            except Exception:  # noqa: BLE001 -- a viewer must not stop the link
                pass

    def event(
        self,
        kind: str,
        raw: bytes = b"",
        device_id: int | None = None,
        command_type: int | None = None,
        payload: str | None = None,
        detail: str = "",
    ) -> None:
        """Convenience for the receiver: stamp and record in one call."""
        self.record(LinkEvent(
            kind=kind, timestamp=now_utc(), raw=raw, device_id=device_id,
            command_type=command_type, payload=payload, detail=detail,
        ))

    # -- presentation side ------------------------------------------------

    def subscribe(self, callback: LinkEventCallback) -> None:
        with self._lock:
            self._subscribers.append(callback)

    def statistics(self) -> LinkStatistics:
        with self._lock:
            counts = self._counters.counts
            return LinkStatistics(
                active=self._active,
                bytes_received=self._counters.bytes_received,
                frames=counts.get(FRAME, 0),
                resyncs=counts.get(RESYNC, 0),
                checksum_errors=counts.get(CHECKSUM_ERROR, 0),
                decode_errors=counts.get(DECODE_ERROR, 0),
                ignored=counts.get(IGNORED, 0),
                payload_errors=counts.get(PAYLOAD_ERROR, 0),
                last_frame_at=self._counters.last_frame_at,
            )
