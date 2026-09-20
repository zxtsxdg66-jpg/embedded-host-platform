"""The port through which the service layer records and reads back history.

Defined here -- in the consumer -- rather than beside the SQLite
implementation, following the same convention as
``service.assistant.llm_port.LlmClient`` and
``service.control_service_impl.CommandTransport``: the layer that needs a
capability declares its shape, and whoever composes the application
injects something that fits. The concrete store therefore lives outside
``service/`` (in the ``storage`` package) and is never imported by it.

Why the service layer may not simply open a database itself: it must not
manage physical resources -- see ``src/service/README.md`` "设计约束".
A file path and a connection are exactly that.

Design: docs/02_Architecture/History_And_Cloud_Design.md section 4.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from core.models import ChannelId, DeviceId


@dataclass(frozen=True)
class HistoryPoint:
    """One stored reading.

    Deliberately *not* ``DataPoint``: that type carries ``value: Any``
    because a channel's payload is whatever its device declares, whereas
    anything that reached storage has already been narrowed to a number.
    Keeping them separate means the storage schema does not silently widen
    when someone adds a non-numeric channel upstream.

    ``valid`` is stored rather than filtered on the way in. The firmware
    does not report the noise channel at all when its Modbus read fails,
    so an invalid reading that *does* arrive is evidence about link
    quality -- dropping it here would make that evidence unrecoverable.
    """

    device_id: DeviceId
    channel: ChannelId
    value: float
    timestamp: datetime
    valid: bool = True


@runtime_checkable
class HistoryStore(Protocol):
    """Somewhere readings can be appended to and queried back from."""

    def append_many(self, points: list[HistoryPoint]) -> None:
        """Store a batch. Called from the poll loop, never from a data callback.

        Must not raise: losing history is not worth taking the acquisition
        loop down for, and the caller has no useful recovery either.
        """
        ...

    def query(
        self,
        device_id: DeviceId,
        channel: ChannelId,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> list[HistoryPoint]:
        """Return matching readings, newest first, at most ``limit`` of them."""
        ...

    def query_range(
        self,
        start: datetime,
        end: datetime,
        limit: int | None = None,
    ) -> list[HistoryPoint]:
        """Every reading in ``[start, end]``, across all devices and channels.

        **Oldest first** -- the opposite of :meth:`query`, and deliberately
        so. This method exists to feed an export file that people read
        top-down as time moves forward, whereas ``query`` feeds a view
        that shows what just happened. Having the store settle the order
        keeps every caller from re-sorting, but the asymmetry is real, so
        it is stated here rather than left to be discovered.

        Added 2026-09-17 for the hourly archive export (design doc section
        5.1). Extending this protocol was agreed first, per CLAUDE.md's
        rule about protected interfaces: the alternative was letting
        ``scripts/`` open the database file directly, which would put a
        second thing that touches external resources outside the adapter
        packages.
        """
        ...

    def count(self) -> int:
        """Total stored readings. For tests and for the export bookkeeping."""
        ...

    def close(self) -> None:
        """Release whatever the implementation holds. Safe to call twice."""
        ...


class NullHistoryStore:
    """The always-available implementation: stores nothing, answers empty.

    This is the default, by analogy with
    ``service.assistant.llm_port.NullLlmClient`` and
    ``communication.loopback.LoopbackChannel``: everything above it can be
    exercised with no external resource attached, and a launcher that has
    not attached a real store still runs rather than crashing on first
    reading.

    That tolerance has a cost worth naming: a launcher which *forgot* to
    attach a store looks exactly like one that deliberately did not. This
    project has already shipped that bug twice -- the 2026-09-07
    automations and the 2026-09-08 model were each wired into one launcher
    and silently missing from the others. So the guard against forgetting
    is not a runtime error here; it is
    ``tests/scripts/test_automation_wiring.py``'s
    ``test_every_launcher_records_history``, which asserts all three
    launchers mention the wiring symbols (design doc section 7).
    """

    def append_many(self, points: list[HistoryPoint]) -> None:
        return None

    def query(
        self,
        device_id: DeviceId,
        channel: ChannelId,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> list[HistoryPoint]:
        return []

    def query_range(
        self,
        start: datetime,
        end: datetime,
        limit: int | None = None,
    ) -> list[HistoryPoint]:
        return []

    def count(self) -> int:
        return 0

    def close(self) -> None:
        return None


class InMemoryHistoryStore:
    """A real store that keeps everything in a list. For tests.

    Same role ``InMemoryDataService`` plays for the data path: the
    behaviour under test is the recorder's batching and the query
    semantics, neither of which should need a file on disk to verify.
    """

    def __init__(self) -> None:
        self._points: list[HistoryPoint] = []

    def append_many(self, points: list[HistoryPoint]) -> None:
        self._points.extend(points)

    def query(
        self,
        device_id: DeviceId,
        channel: ChannelId,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> list[HistoryPoint]:
        selected = [
            point
            for point in self._points
            if point.device_id == device_id
            and point.channel == channel
            and (start is None or point.timestamp >= start)
            and (end is None or point.timestamp <= end)
        ]
        selected.sort(key=lambda point: point.timestamp, reverse=True)
        return selected[:limit]

    def query_range(
        self,
        start: datetime,
        end: datetime,
        limit: int | None = None,
    ) -> list[HistoryPoint]:
        selected = [
            point
            for point in self._points
            if start <= point.timestamp <= end
        ]
        selected.sort(key=lambda point: point.timestamp)
        return selected if limit is None else selected[:limit]

    def count(self) -> int:
        return len(self._points)

    def close(self) -> None:
        return None
