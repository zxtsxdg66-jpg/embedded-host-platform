"""`SqliteHistoryStore` 的回归测试。

设计见 `docs/decisions/06-history.md`。
这里守的几条决定，每条都对应文档里一句明确的取舍：

- 时间戳存 UTC 文本，且**文本序必须等于时间序**（否则"新的在前"是错的）；
- 无效读数照存不丢；
- 磁盘出问题绝不抛异常，只计数——采集循环不能因为历史写不进去而停。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from service.history import HistoryPoint, HistoryStore
from storage.sqlite_history import SqliteHistoryStore

DEVICE = "mcu-1"


def _point(
    second: int, *, channel: str = "temperature", value: float = 25.0,
    valid: bool = True, microsecond: int = 0,
) -> HistoryPoint:
    return HistoryPoint(
        device_id=DEVICE,
        channel=channel,
        value=value,
        timestamp=datetime(
            2026, 9, 17, 12, 0, second, microsecond, tzinfo=timezone.utc
        ),
        valid=valid,
    )


def _store(tmp_path: Path) -> SqliteHistoryStore:
    return SqliteHistoryStore(tmp_path / "history.sqlite")


# -- 契约 ----------------------------------------------------------------------


def test_the_sqlite_store_satisfies_the_service_layer_port(tmp_path: Path) -> None:
    """结构化匹配由 mypy 在装配点验证，这里再运行时确认一次。

    端口定义在消费方 `service.history`，本包不被 `service` import——
    与 `LlmClient` / `CommandTransport` 是同一条既有约定。
    """
    store = _store(tmp_path)

    assert isinstance(store, HistoryStore)

    store.close()


# -- 写入与读回 ----------------------------------------------------------------


def test_what_was_written_can_be_read_back(tmp_path: Path) -> None:
    store = _store(tmp_path)

    store.append_many([_point(1, value=25.5), _point(2, value=26.0)])

    found = store.query(DEVICE, "temperature")
    assert [point.value for point in found] == [26.0, 25.5]
    assert store.count() == 2
    store.close()


def test_readings_survive_reopening_the_file(tmp_path: Path) -> None:
    """重启后还在，这正是做持久化的全部意义。

    对应第 8 节 P0 的验收标准："跑 10 分钟后重启，能查到重启前的数据"。
    """
    path = tmp_path / "history.sqlite"
    first = SqliteHistoryStore(path)
    first.append_many([_point(1, value=21.0)])
    first.close()

    second = SqliteHistoryStore(path)

    assert [point.value for point in second.query(DEVICE, "temperature")] == [21.0]
    second.close()


def test_the_newest_reading_comes_first_even_with_mixed_precision(
    tmp_path: Path,
) -> None:
    """有微秒与无微秒的时间戳混在一起，顺序仍须正确。

    排序是按 `ts_utc` 的**文本**做的，所以"文本序等于时间序"是这条查询正确的
    前提。`to_iso8601()` 强制转成 UTC 保证了这一点，但有无微秒会让字符串长短
    不同，这条用例把该情形钉下来。
    """
    store = _store(tmp_path)

    store.append_many(
        [
            _point(5, value=1.0),
            _point(5, value=2.0, microsecond=123456),
            _point(4, value=3.0, microsecond=999999),
            _point(6, value=4.0),
        ]
    )

    assert [point.value for point in store.query(DEVICE, "temperature")] == [
        4.0,
        2.0,
        1.0,
        3.0,
    ]
    store.close()


def test_an_invalid_reading_is_stored_rather_than_filtered(tmp_path: Path) -> None:
    """无效读数是链路质量的证据，入口处丢掉就再也补不回来。"""
    store = _store(tmp_path)

    store.append_many([_point(1, value=0.0, valid=False)])

    found = store.query(DEVICE, "temperature")
    assert len(found) == 1
    assert found[0].valid is False
    store.close()


def test_the_timestamp_read_back_is_the_one_written(tmp_path: Path) -> None:
    store = _store(tmp_path)
    written = _point(7, microsecond=250000)

    store.append_many([written])

    assert store.query(DEVICE, "temperature")[0].timestamp == written.timestamp
    store.close()


# -- 过滤 ----------------------------------------------------------------------


def test_channels_do_not_bleed_into_each_other(tmp_path: Path) -> None:
    store = _store(tmp_path)

    store.append_many([_point(1, value=25.0), _point(1, channel="noise", value=49.5)])

    assert [point.value for point in store.query(DEVICE, "noise")] == [49.5]
    store.close()


def test_a_time_range_selects_only_what_falls_inside_it(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append_many([_point(second) for second in (1, 5, 9)])

    found = store.query(
        DEVICE,
        "temperature",
        start=datetime(2026, 9, 17, 12, 0, 4, tzinfo=timezone.utc),
        end=datetime(2026, 9, 17, 12, 0, 6, tzinfo=timezone.utc),
    )

    assert [point.timestamp.second for point in found] == [5]
    store.close()


def test_the_limit_caps_how_much_comes_back(tmp_path: Path) -> None:
    """默认 500，与界面既有的历史上限一致——一次查询不该把几十万行拉进内存。"""
    store = _store(tmp_path)
    store.append_many([_point(second) for second in range(10)])

    assert len(store.query(DEVICE, "temperature", limit=3)) == 3
    store.close()


def test_asking_about_a_device_that_never_reported_gives_nothing(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.append_many([_point(1)])

    assert store.query("mcu-absent", "temperature") == []
    store.close()


# -- query_range（导出用） -----------------------------------------------------


def test_query_range_spans_devices_and_channels_oldest_first(tmp_path: Path) -> None:
    """导出取的是"整个时段"，不分设备通道，且由早到晚。"""
    store = _store(tmp_path)
    store.append_many(
        [
            _point(3, value=3.0),
            _point(1, channel="noise", value=1.0),
            _point(2, value=2.0),
        ]
    )

    found = store.query_range(
        datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 17, 12, 0, 9, tzinfo=timezone.utc),
    )

    assert [point.value for point in found] == [1.0, 2.0, 3.0]
    store.close()


def test_query_range_is_inclusive_at_both_ends(tmp_path: Path) -> None:
    """闭区间。导出按小时切片时靠它保证不漏掉整点那一条。"""
    store = _store(tmp_path)
    store.append_many([_point(0), _point(9)])

    found = store.query_range(
        datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 17, 12, 0, 9, tzinfo=timezone.utc),
    )

    assert len(found) == 2
    store.close()


def test_query_range_on_a_broken_database_returns_empty(tmp_path: Path) -> None:
    blocked = tmp_path / "occupied"
    blocked.write_text("我是一个文件，不是目录", encoding="utf-8")
    store = SqliteHistoryStore(blocked / "history.sqlite")

    assert (
        store.query_range(
            datetime(2026, 9, 17, tzinfo=timezone.utc),
            datetime(2026, 9, 18, tzinfo=timezone.utc),
        )
        == []
    )
    assert store.failures > 0
    store.close()


# -- 绝不抛异常 ----------------------------------------------------------------


def test_a_broken_database_never_raises(tmp_path: Path) -> None:
    """数据库路径被一个文件占住父目录，打开必然失败。

    与"日志坏掉不抛异常"、"模型缺席时问答照常工作"是同一条原则：
    历史写不进去是遗憾，把采集循环带下去才是事故。
    """
    blocked = tmp_path / "occupied"
    blocked.write_text("我是一个文件，不是目录", encoding="utf-8")
    store = SqliteHistoryStore(blocked / "history.sqlite")

    store.append_many([_point(1)])

    assert store.query(DEVICE, "temperature") == []
    assert store.count() == 0
    assert store.failures > 0
    assert store.last_error != ""
    store.close()


def test_an_empty_batch_touches_nothing(tmp_path: Path) -> None:
    store = _store(tmp_path)

    store.append_many([])

    assert store.count() == 0
    assert store.failures == 0
    store.close()


def test_closing_twice_is_safe(tmp_path: Path) -> None:
    """退出路径上 flush 与 close 可能各走一遍，重复关闭不该出事。"""
    store = _store(tmp_path)

    store.close()
    store.close()

    assert store.failures == 0


def test_writing_after_close_does_not_raise(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.close()

    store.append_many([_point(1)])

    assert store.query(DEVICE, "temperature") == []


def test_the_database_file_lands_where_asked(tmp_path: Path) -> None:
    """落点是 `data/history.sqlite`（见 4.0 节），目录不存在时自行建出来。"""
    target = tmp_path / "data" / "history.sqlite"
    store = SqliteHistoryStore(target)

    store.append_many([_point(1)])
    store.close()

    assert target.exists()


def test_a_timezone_aware_local_timestamp_is_normalised_to_utc(
    tmp_path: Path,
) -> None:
    """带 +08:00 的时间戳存进去，读回来应是同一时刻的 UTC 表示。"""
    store = _store(tmp_path)
    local = datetime(
        2026, 9, 17, 20, 0, 5, tzinfo=timezone(timedelta(hours=8))
    )
    store.append_many(
        [HistoryPoint(DEVICE, "temperature", 25.0, local, True)]
    )

    read_back = store.query(DEVICE, "temperature")[0].timestamp

    assert read_back == local
    assert read_back.utcoffset() == timedelta(0)
    store.close()
