"""SQLite-backed history store.

Schema and the reasoning behind it: see
docs/decisions/06-history.md. The short
version of the two decisions that are easy to get wrong later:

* **Timestamps are stored as ISO-8601 UTC text.** ``DataPoint.timestamp``
  is already ``now_utc()``; storing it unchanged avoids the ambiguity that
  local time would introduce the first time a reading is exported or read
  on a device in another timezone. Export adds a local-time column for
  people to read, which is a presentation concern, not a storage one.
* **Invalid readings are stored, not filtered.** See ``HistoryPoint``.

Never raises to its caller. A full disk, a locked file or a corrupted
database must not take down the acquisition loop -- history is valuable
but it is not what the system is for. Failures are counted so a launcher
can surface "history is not being written" rather than silently losing
data, which is the failure mode that would otherwise be invisible.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from core.models import ChannelId, DeviceId
from core.timestamps import from_iso8601, to_iso8601
from service.history import HistoryPoint

_SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    id        INTEGER PRIMARY KEY,
    device_id TEXT    NOT NULL,
    channel   TEXT    NOT NULL,
    value     REAL    NOT NULL,
    ts_utc    TEXT    NOT NULL,
    valid     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_readings_lookup ON readings (channel, ts_utc);
"""

DEFAULT_DATABASE_PATH = Path("data") / "history.sqlite"
"""Where the history database lives by default.

Under ``data/`` rather than loose in the project root so that a future
retention policy or backup has one directory to act on. Excluded from
version control -- it is data, not source.
"""


class SqliteHistoryStore:
    """Stores readings in a SQLite file.

    One connection per instance, guarded by a lock. The acquisition loop
    is the only writer, but the gateway answers queries on its own thread,
    and sqlite3 connections are not safe to share across threads without
    serialising access. A lock is enough here and avoids a connection pool
    for what is, at roughly one reading per second, a nearly idle file.
    """

    def __init__(self, path: Path | str = DEFAULT_DATABASE_PATH) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._failures = 0
        self._last_error = ""
        self._connection: sqlite3.Connection | None = self._open()

    @property
    def failures(self) -> int:
        """How many operations have failed since start. 0 in the normal case."""
        return self._failures

    @property
    def last_error(self) -> str:
        """Why the most recent failure happened, for a launcher to display."""
        return self._last_error

    def _open(self) -> sqlite3.Connection | None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self._path, check_same_thread=False)
            # WAL lets the gateway read while the poll loop writes, instead
            # of the two blocking each other on a single file lock.
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(_SCHEMA)
            connection.commit()
            return connection
        except (sqlite3.Error, OSError) as error:
            self._note_failure(error)
            return None

    def _note_failure(self, error: BaseException) -> None:
        self._failures += 1
        self._last_error = f"{type(error).__name__}: {error}"

    def append_many(self, points: list[HistoryPoint]) -> None:
        if not points:
            return
        rows = []
        for point in points:
            # Per point, not per batch: a single unconvertible reading must
            # not cost the other 49 their place in the database. Deciding
            # *what* a non-numeric reading means is the recorder's job --
            # by the time a HistoryPoint exists its value is already
            # declared to be a float, so anything caught here is a bug
            # upstream rather than an ordinary invalid reading.
            try:
                rows.append(
                    (
                        point.device_id,
                        point.channel,
                        float(point.value),
                        to_iso8601(point.timestamp),
                        1 if point.valid else 0,
                    )
                )
            except (TypeError, ValueError) as error:
                self._note_failure(error)
        if not rows:
            return
        with self._lock:
            connection = self._connection
            if connection is None:
                return
            try:
                connection.executemany(
                    "INSERT INTO readings (device_id, channel, value, ts_utc, valid)"
                    " VALUES (?, ?, ?, ?, ?)",
                    rows,
                )
                connection.commit()
            except (sqlite3.Error, OSError) as error:
                self._note_failure(error)

    def query(
        self,
        device_id: DeviceId,
        channel: ChannelId,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> list[HistoryPoint]:
        with self._lock:
            connection = self._connection
            if connection is None:
                return []
            sql = (
                "SELECT device_id, channel, value, ts_utc, valid FROM readings"
                " WHERE device_id = ? AND channel = ?"
            )
            parameters: list[object] = [device_id, channel]
            if start is not None:
                sql += " AND ts_utc >= ?"
                parameters.append(to_iso8601(start))
            if end is not None:
                sql += " AND ts_utc <= ?"
                parameters.append(to_iso8601(end))
            sql += " ORDER BY ts_utc DESC, id DESC LIMIT ?"
            parameters.append(max(0, limit))
            try:
                rows = connection.execute(sql, parameters).fetchall()
            except (sqlite3.Error, ValueError) as error:
                self._note_failure(error)
                return []
        return [
            HistoryPoint(
                device_id=row[0],
                channel=row[1],
                value=row[2],
                timestamp=from_iso8601(row[3]),
                valid=bool(row[4]),
            )
            for row in rows
        ]

    def query_range(
        self,
        start: datetime,
        end: datetime,
        limit: int | None = None,
    ) -> list[HistoryPoint]:
        """所有设备、所有通道在 [start, end] 内的读数，**由早到晚**。

        与 `query()` 的倒序相反，理由见 `service.history.HistoryStore`
        的同名方法：它喂的是给人从上往下读的导出文件。
        """
        with self._lock:
            connection = self._connection
            if connection is None:
                return []
            sql = (
                "SELECT device_id, channel, value, ts_utc, valid FROM readings"
                " WHERE ts_utc >= ? AND ts_utc <= ?"
                " ORDER BY ts_utc ASC, id ASC"
            )
            parameters: list[object] = [to_iso8601(start), to_iso8601(end)]
            if limit is not None:
                sql += " LIMIT ?"
                parameters.append(max(0, limit))
            try:
                rows = connection.execute(sql, parameters).fetchall()
            except (sqlite3.Error, ValueError) as error:
                self._note_failure(error)
                return []
        return [
            HistoryPoint(
                device_id=row[0],
                channel=row[1],
                value=row[2],
                timestamp=from_iso8601(row[3]),
                valid=bool(row[4]),
            )
            for row in rows
        ]

    def count(self) -> int:
        with self._lock:
            connection = self._connection
            if connection is None:
                return 0
            try:
                row = connection.execute("SELECT COUNT(*) FROM readings").fetchone()
            except sqlite3.Error as error:
                self._note_failure(error)
                return 0
        return int(row[0]) if row else 0

    def close(self) -> None:
        with self._lock:
            connection = self._connection
            self._connection = None
            if connection is None:
                return
            try:
                connection.close()
            except sqlite3.Error as error:
                self._note_failure(error)
