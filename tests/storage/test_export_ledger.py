"""`SqliteExportLedger` 的回归测试。

设计见 `docs/02_Architecture/History_And_Cloud_Design.md` 第 5.1 节。
这张表同时是**幂等依据**与**待发队列**，下面的用例分别守这两件事，
外加一条：台账坏掉不抛异常（与历史库、问答日志同一条原则）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from storage.export_ledger import ExportRecord, SqliteExportLedger

SLOT = "20260917_15"


def _moment(minute: int = 0) -> datetime:
    return datetime(2026, 9, 17, 16, minute, tzinfo=timezone.utc)


def _ledger(tmp_path: Path) -> SqliteExportLedger:
    return SqliteExportLedger(tmp_path / "history.sqlite")


# -- 幂等 ----------------------------------------------------------------------


def test_a_slot_can_be_recorded_once(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)

    assert ledger.record_export(SLOT, "env_20260917_15.csv", 3500, _moment()) is True

    assert ledger.is_exported(SLOT) is True
    ledger.close()


def test_recording_the_same_slot_twice_does_not_add_a_second_row(
    tmp_path: Path,
) -> None:
    """重复导出同一区间不产生第二份——这条是幂等的全部内容。"""
    ledger = _ledger(tmp_path)
    ledger.record_export(SLOT, "env_20260917_15.csv", 3500, _moment())

    assert ledger.record_export(SLOT, "env_20260917_15.csv", 9999, _moment(5)) is False

    records = ledger.all_records()
    assert len(records) == 1
    # 第一次写下的行数保持不变，后来的 9999 没有覆盖它。
    assert records[0].row_count == 3500
    ledger.close()


def test_an_unrecorded_slot_is_not_exported(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)

    assert ledger.is_exported("20260101_00") is False
    ledger.close()


def test_the_ledger_survives_reopening(tmp_path: Path) -> None:
    """台账与历史读数同库，因此也必须活过重启。"""
    path = tmp_path / "history.sqlite"
    first = SqliteExportLedger(path)
    first.record_export(SLOT, "env_20260917_15.csv", 10, _moment())
    first.close()

    second = SqliteExportLedger(path)

    assert second.is_exported(SLOT) is True
    second.close()


# -- 待发队列 ------------------------------------------------------------------


def test_a_freshly_exported_slot_is_pending_upload(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.record_export(SLOT, "env_20260917_15.csv", 10, _moment())

    pending = ledger.pending_uploads()

    assert [record.slot for record in pending] == [SLOT]
    assert pending[0].is_uploaded is False
    ledger.close()


def test_marking_uploaded_takes_it_out_of_the_queue(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.record_export(SLOT, "env_20260917_15.csv", 10, _moment())

    assert ledger.mark_uploaded(SLOT, _moment(30)) is True

    assert ledger.pending_uploads() == []
    assert ledger.all_records()[0].is_uploaded is True
    ledger.close()


def test_marking_an_unknown_slot_reports_it_rather_than_inventing_a_row(
    tmp_path: Path,
) -> None:
    """标记一个没登记过的时段不该凭空造出一条记录。"""
    ledger = _ledger(tmp_path)

    assert ledger.mark_uploaded("20990101_00", _moment()) is False

    assert ledger.all_records() == []
    ledger.close()


def test_pending_uploads_come_back_oldest_first(tmp_path: Path) -> None:
    """断网攒下几段之后，补传要按发生顺序来。"""
    ledger = _ledger(tmp_path)
    for slot in ("20260917_17", "20260917_15", "20260917_16"):
        ledger.record_export(slot, f"env_{slot}.csv", 10, _moment())

    assert [record.slot for record in ledger.pending_uploads()] == [
        "20260917_15",
        "20260917_16",
        "20260917_17",
    ]
    ledger.close()


def test_uploaded_slots_stay_in_the_ledger(tmp_path: Path) -> None:
    """上传完不删记录——它同时还是"这一段导过了"的幂等依据。"""
    ledger = _ledger(tmp_path)
    ledger.record_export(SLOT, "env_20260917_15.csv", 10, _moment())
    ledger.mark_uploaded(SLOT, _moment(30))

    assert ledger.is_exported(SLOT) is True
    ledger.close()


def test_timestamps_read_back_as_written(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    exported_at = _moment()
    ledger.record_export(SLOT, "env_20260917_15.csv", 10, exported_at)

    record = ledger.all_records()[0]

    assert record.exported_at == exported_at
    assert record.file_name == "env_20260917_15.csv"
    ledger.close()


def test_export_record_reports_upload_state() -> None:
    """纯数据类的小断言：省得调用方各自判断 uploaded_at 是不是 None。"""
    pending = ExportRecord(SLOT, "f.csv", 1, _moment())
    done = ExportRecord(SLOT, "f.csv", 1, _moment(), uploaded_at=_moment(30))

    assert pending.is_uploaded is False
    assert done.is_uploaded is True


# -- 绝不抛异常 ----------------------------------------------------------------


def test_a_broken_ledger_never_raises(tmp_path: Path) -> None:
    """父目录被一个文件占住，打开必然失败。

    与历史库、问答日志同一条原则：台账写不进去是遗憾，
    让一次导出中途炸掉才是事故。
    """
    blocked = tmp_path / "occupied"
    blocked.write_text("我是一个文件，不是目录", encoding="utf-8")
    ledger = SqliteExportLedger(blocked / "history.sqlite")

    assert ledger.record_export(SLOT, "f.csv", 1, _moment()) is False
    assert ledger.is_exported(SLOT) is False
    assert ledger.pending_uploads() == []
    assert ledger.mark_uploaded(SLOT, _moment()) is False
    assert ledger.failures > 0
    assert ledger.last_error != ""
    ledger.close()


def test_closing_twice_is_safe(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)

    ledger.close()
    ledger.close()

    assert ledger.failures == 0


def test_the_ledger_shares_the_database_with_the_readings(tmp_path: Path) -> None:
    """同一个 sqlite 文件里两张表，互不干扰。

    这条守的是 2026-09-17 的决定：台账与读数同库，免得"导出了哪一段"
    与"那一段的数据"在崩溃或手工删档后对不上。
    """
    from service.history import HistoryPoint
    from storage.sqlite_history import SqliteHistoryStore

    path = tmp_path / "history.sqlite"
    store = SqliteHistoryStore(path)
    store.append_many(
        [HistoryPoint("mcu-1", "temperature", 25.0, _moment(), True)]
    )
    ledger = SqliteExportLedger(path)
    ledger.record_export(SLOT, "env_20260917_15.csv", 1, _moment())

    assert store.count() == 1
    assert ledger.is_exported(SLOT) is True
    store.close()
    ledger.close()
