"""HistoryRecorder: subscribes to published readings and batches them to a store.

Same shape as the dispatchers beside it -- record in the callback, do the
slow thing from the poll loop -- and here that shape is not a preference
but a hard requirement. ``InMemoryDataService.publish()`` is synchronous:
its callbacks run on the acquisition thread, and the very next thing that
thread does is collect the language model's output. A disk write inside
the callback would therefore sit directly in the path that keeps the UI
responsive. The 2026-09-07 defect (sending a command from a data callback
re-entered the serial read loop and took the test process down with it)
is the same mistake one layer over.

So: the callback appends to a list in memory and returns. Flushing to the
store happens when ``flush_if_due()`` is called from the poll loop, which
writes once a batch is big enough or old enough.

Design: docs/02_Architecture/History_And_Cloud_Design.md section 4.2.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from core.models import ChannelId, DeviceId
from service.data_models import DataPoint
from service.data_service import DataService
from service.history import HistoryPoint, HistoryStore

DEFAULT_BATCH_SIZE = 50
"""Flush once this many readings are waiting.

At roughly one reading per second across three channels, this is a write
every fifteen-odd seconds -- rare enough that the disk is idle between
them, small enough that a crash loses seconds rather than minutes.
"""

DEFAULT_MAX_AGE_SECONDS = 5.0
"""Flush this long after the oldest waiting reading arrived, batch or no.

Without it a quiet channel's readings could sit in memory indefinitely,
which is exactly the data most worth having when a device goes silent.
"""


class HistoryRecorder:
    """Collects published readings and writes them to a store in batches."""

    def __init__(
        self,
        store: HistoryStore,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._batch_size = max(1, batch_size)
        self._max_age_seconds = max_age_seconds
        self._now = now
        self._pending: list[HistoryPoint] = []
        self._oldest_at: float | None = None
        self._recorded = 0
        self._skipped = 0

    @property
    def recorded(self) -> int:
        """Readings handed to the store since start."""
        return self._recorded

    @property
    def skipped(self) -> int:
        """Readings dropped because their value was not a number.

        Not expected to move. It exists because ``DataPoint.value`` is
        ``Any`` and two of its three construction sites build it from
        ``json.loads(...)["value"]`` off the wire -- a malformed frame can
        therefore carry a string this far. Counting rather than raising
        keeps a bad frame from stopping acquisition, and a non-zero value
        here means the frame decoder let something through.
        """
        return self._skipped

    @property
    def pending(self) -> int:
        """Readings waiting in memory, not yet written."""
        return len(self._pending)

    def subscribe_to(
        self, data_service: DataService, device_id: DeviceId, channel: ChannelId
    ) -> None:
        """Record every reading published on ``device_id``/``channel``.

        Per channel, matching how the alarm and ventilation processors are
        wired in ``ApplicationRuntime.watch_device_channels()``. The
        recorder has nothing to filter -- it stores everything -- but
        subscribing the same way keeps that method from needing to know
        which subscribers care about which channels.
        """
        data_service.subscribe(device_id, channel, self.handle_data_point)

    def handle_data_point(self, point: DataPoint) -> None:
        """Queue one reading. Runs on the acquisition thread: memory only."""
        try:
            value = float(point.value)
        except (TypeError, ValueError):
            self._skipped += 1
            return
        if self._oldest_at is None:
            self._oldest_at = self._now()
        self._pending.append(
            HistoryPoint(
                device_id=point.device_id,
                channel=point.channel,
                value=value,
                timestamp=point.timestamp,
                valid=point.valid,
            )
        )

    def flush_if_due(self) -> bool:
        """Write the batch if it is big enough or old enough. Call each cycle.

        Returns whether anything was written. Cheap on the cycles it does
        nothing, which is most of them.
        """
        if not self._pending:
            return False
        if len(self._pending) < self._batch_size:
            oldest_at = self._oldest_at
            if oldest_at is None:
                return False
            if self._now() - oldest_at < self._max_age_seconds:
                return False
        self.flush()
        return True

    def flush(self) -> None:
        """Write whatever is waiting, unconditionally. Call before exiting.

        Never raises: the store is documented not to, and losing the last
        few readings is not a reason to fail a shutdown.
        """
        if not self._pending:
            return
        batch = self._pending
        self._pending = []
        self._oldest_at = None
        self._store.append_many(batch)
        self._recorded += len(batch)
