"""EventHub: bridges synchronous ApiInterface callbacks to asyncio WebSockets.

The problem this solves
-----------------------
``ApiInterface.subscribe_data``/``subscribe_alarm_status``/
``subscribe_statistics`` deliver via **synchronous callbacks invoked on
whichever thread published the data** (see ui/controller.py's
``_handle_data_point`` docstring: "runs synchronously on whatever call
triggered publication"). A WebSocket send, by contrast, must happen on the
asyncio event loop uvicorn is running.

Calling an asyncio primitive directly from the publishing thread would be
a race. So this hub:

1. accepts messages from any thread via :meth:`publish` (sync, non-blocking,
   never raises into the publisher),
2. hands them to the event loop with ``loop.call_soon_threadsafe``,
3. fans them out to every currently connected WebSocket subscriber queue.

Backpressure: each subscriber has a bounded queue. If a client is too slow
to drain it, the oldest message is dropped for that client only, rather
than growing without bound or blocking the publisher (which would stall
the data pipeline that feeds the PyQt6 UI as well -- the publisher thread
is shared). Dropping is counted so it is observable rather than silent.
"""

from __future__ import annotations

import asyncio
from typing import Any

_DEFAULT_QUEUE_SIZE = 100


class EventHub:
    """Thread-safe fan-out of JSON-able messages to asyncio subscribers."""

    def __init__(self, queue_size: int = _DEFAULT_QUEUE_SIZE) -> None:
        if queue_size <= 0:
            raise ValueError("queue_size must be positive")
        self._queue_size = queue_size
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self.dropped_count = 0
        self.published_count = 0

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Record the event loop that :meth:`publish` should marshal onto.

        Called once from the server's startup hook, where the running loop
        is known. Until this is called, :meth:`publish` is a no-op (a data
        point produced before the server finished starting has no
        connected client to deliver to anyway).
        """
        self._loop = loop

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Register a new subscriber queue. Call from the event loop."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove a subscriber queue. Idempotent."""
        self._subscribers.discard(queue)

    def publish(self, message: dict[str, Any]) -> None:
        """Publish ``message`` to all subscribers. Safe from any thread.

        Never raises: this is called from inside the data pipeline (the
        same synchronous callback chain that feeds the PyQt6 UI), so an
        error here must not propagate back and break data publication.
        """
        loop = self._loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(self._deliver, message)
        except RuntimeError:
            # Loop already closed (server shutting down while a data point
            # was in flight). Nothing to deliver to; not an error worth
            # propagating into the publisher.
            return

    def _deliver(self, message: dict[str, Any]) -> None:
        """Fan out to every subscriber queue. Runs on the event loop."""
        self.published_count += 1
        for queue in self._subscribers:
            self._offer(queue, message)

    def _offer(
        self, queue: asyncio.Queue[dict[str, Any]], message: dict[str, Any]
    ) -> None:
        """Enqueue, dropping this subscriber's oldest message if it is full."""
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()  # discard oldest
                self.dropped_count += 1
                queue.put_nowait(message)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                # Raced with the consumer; the message is simply skipped
                # for this subscriber. Counted above if the drop happened.
                self.dropped_count += 1
