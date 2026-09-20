"""归档导出的台账：哪些时段已导出、哪些还没上传。

设计见 docs/02_Architecture/History_And_Cloud_Design.md 第 5.1 节。它同时
承担两件事，而这两件事本来就是同一张表的两面：

* **幂等**——同一个小时片重复导出不产生第二份文件；
* **待发队列**——`uploaded_at` 为空的行就是"导出了但还没送上云"的时段，
  断网时它们留在那儿，下次运行脚本自然补上。

**为什么和历史读数放在同一个 sqlite 文件里**（2026-09-17 用户确认）：
"导出了哪一段"与"那一段的数据"分在两个文件里，崩溃或手工删档之后就会
对不上——台账说导过、库里却没有，或者反过来。同一个文件至少保证两者
一起存在、一起消失。代价是 `storage` 包里多一个类碰同一个库，这比
两份文件各说各话要好。

与 ``SqliteHistoryStore`` 一样**绝不向调用方抛异常**：台账写不进去是
遗憾，不该让一次导出中途炸掉。失败被计数并记下原因。
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.timestamps import from_iso8601, to_iso8601
from storage.sqlite_history import DEFAULT_DATABASE_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS exports (
    id          INTEGER PRIMARY KEY,
    slot        TEXT    NOT NULL UNIQUE,
    file_name   TEXT    NOT NULL,
    row_count   INTEGER NOT NULL,
    exported_at TEXT    NOT NULL,
    uploaded_at TEXT
);
"""
"""``slot`` 上的 UNIQUE 约束就是幂等本身。

把"同一时段只能有一条"交给数据库，而不是先查后插：后者在两个进程同时
跑脚本时会双双查到"没有"，然后插两条。这个项目只会有一个人双击那个
.bat，但让正确性依赖"不会有第二个人"是没必要的脆弱。
"""


@dataclass(frozen=True)
class ExportRecord:
    """一个已导出的小时片。"""

    slot: str
    """本地时间的小时标识，形如 ``20260917_15``。与文件名里的那段一致。"""

    file_name: str
    row_count: int
    exported_at: datetime
    uploaded_at: datetime | None = None

    @property
    def is_uploaded(self) -> bool:
        return self.uploaded_at is not None


class SqliteExportLedger:
    """导出台账，与历史读数同库不同表。"""

    def __init__(self, path: Path | str = DEFAULT_DATABASE_PATH) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._failures = 0
        self._last_error = ""
        self._connection: sqlite3.Connection | None = self._open()

    @property
    def failures(self) -> int:
        """失败次数，正常情况下为 0。"""
        return self._failures

    @property
    def last_error(self) -> str:
        """最近一次失败的原因，供脚本打印给人看。"""
        return self._last_error

    def _open(self) -> sqlite3.Connection | None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self._path, check_same_thread=False)
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

    def is_exported(self, slot: str) -> bool:
        """该时段是否已经导出过。"""
        with self._lock:
            connection = self._connection
            if connection is None:
                return False
            try:
                row = connection.execute(
                    "SELECT 1 FROM exports WHERE slot = ?", (slot,)
                ).fetchone()
            except sqlite3.Error as error:
                self._note_failure(error)
                return False
        return row is not None

    def record_export(
        self,
        slot: str,
        file_name: str,
        row_count: int,
        exported_at: datetime,
    ) -> bool:
        """登记一个刚导出的时段。已登记过则返回 False，不产生第二条。

        **先写文件、再登记**是调用方必须遵守的顺序：反过来的话，文件写
        失败但台账已记，那个时段就再也不会被补导出了。
        """
        with self._lock:
            connection = self._connection
            if connection is None:
                return False
            try:
                connection.execute(
                    "INSERT INTO exports (slot, file_name, row_count, exported_at)"
                    " VALUES (?, ?, ?, ?)",
                    (slot, file_name, row_count, to_iso8601(exported_at)),
                )
                connection.commit()
            except sqlite3.IntegrityError:
                # UNIQUE 冲突：这个时段别人已经导过。不是错误，是幂等生效。
                return False
            except (sqlite3.Error, ValueError) as error:
                self._note_failure(error)
                return False
        return True

    def mark_uploaded(self, slot: str, uploaded_at: datetime) -> bool:
        """标记该时段已送上云。未登记过的时段返回 False。"""
        with self._lock:
            connection = self._connection
            if connection is None:
                return False
            try:
                cursor = connection.execute(
                    "UPDATE exports SET uploaded_at = ? WHERE slot = ?",
                    (to_iso8601(uploaded_at), slot),
                )
                connection.commit()
            except (sqlite3.Error, ValueError) as error:
                self._note_failure(error)
                return False
        return cursor.rowcount > 0

    def pending_uploads(self) -> list[ExportRecord]:
        """已导出但还没上传的时段，由早到晚。这就是待发队列。"""
        return self._select("WHERE uploaded_at IS NULL")

    def all_records(self) -> list[ExportRecord]:
        """全部台账记录，由早到晚。"""
        return self._select("")

    def _select(self, where: str) -> list[ExportRecord]:
        with self._lock:
            connection = self._connection
            if connection is None:
                return []
            try:
                rows = connection.execute(
                    "SELECT slot, file_name, row_count, exported_at, uploaded_at"
                    f" FROM exports {where} ORDER BY slot ASC"
                ).fetchall()
            except sqlite3.Error as error:
                self._note_failure(error)
                return []
        records = []
        for row in rows:
            try:
                records.append(
                    ExportRecord(
                        slot=row[0],
                        file_name=row[1],
                        row_count=row[2],
                        exported_at=from_iso8601(row[3]),
                        uploaded_at=from_iso8601(row[4]) if row[4] else None,
                    )
                )
            except ValueError as error:
                # 单条记录的时间戳坏掉不该让整张台账读不出来。
                self._note_failure(error)
        return records

    def close(self) -> None:
        """释放连接。可重复调用。"""
        with self._lock:
            connection = self._connection
            self._connection = None
            if connection is None:
                return
            try:
                connection.close()
            except sqlite3.Error as error:
                self._note_failure(error)
