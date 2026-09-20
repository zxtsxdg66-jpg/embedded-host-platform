"""`service.history` 的端口与两个不落盘实现。

设计见 `docs/02_Architecture/History_And_Cloud_Design.md` 第 4 节。
`NullHistoryStore` 的存在理由与 `NullLlmClient`、`LoopbackChannel` 相同：
让它上面的一切都能在不挂任何外部资源的情况下被验证。
"""

from __future__ import annotations

from datetime import datetime, timezone

from service.history import (
    HistoryPoint,
    HistoryStore,
    InMemoryHistoryStore,
    NullHistoryStore,
)

DEVICE = "mcu-1"


def _point(
    second: int, *, channel: str = "temperature", value: float = 25.0
) -> HistoryPoint:
    return HistoryPoint(
        device_id=DEVICE,
        channel=channel,
        value=value,
        timestamp=datetime(2026, 9, 17, 12, 0, second, tzinfo=timezone.utc),
    )


# -- 端口 ----------------------------------------------------------------------


def test_both_bundled_implementations_satisfy_the_port() -> None:
    assert isinstance(NullHistoryStore(), HistoryStore)
    assert isinstance(InMemoryHistoryStore(), HistoryStore)


def test_a_history_point_defaults_to_valid() -> None:
    """与 `DataPoint.valid` 一致：没说无效就是有效。"""
    assert _point(1).valid is True


# -- 不存的那个 ----------------------------------------------------------------


def test_the_null_store_accepts_everything_and_answers_empty() -> None:
    """没接存储的启动器仍要能跑，查询返回空而不是抛异常。

    代价是"忘了接"与"故意不接"长得一模一样——这个项目已经犯过两次
    （09-07 自动通风、09-08 模型），所以防线不在这里，而在那条断言
    三个启动器都提到接线符号的测试（设计文档第 7 节）。
    """
    store = NullHistoryStore()

    store.append_many([_point(1), _point(2)])

    assert store.query(DEVICE, "temperature") == []
    assert store.count() == 0
    store.close()


# -- 内存那个 ------------------------------------------------------------------


def test_the_in_memory_store_returns_the_newest_first() -> None:
    store = InMemoryHistoryStore()

    store.append_many(
        [_point(1, value=1.0), _point(3, value=3.0), _point(2, value=2.0)]
    )

    assert [point.value for point in store.query(DEVICE, "temperature")] == [
        3.0,
        2.0,
        1.0,
    ]


def test_the_in_memory_store_filters_by_channel() -> None:
    store = InMemoryHistoryStore()

    store.append_many([_point(1, value=25.0), _point(1, channel="noise", value=49.5)])

    assert [point.value for point in store.query(DEVICE, "noise")] == [49.5]


def test_the_in_memory_store_filters_by_device() -> None:
    store = InMemoryHistoryStore()
    store.append_many([_point(1)])

    assert store.query("mcu-absent", "temperature") == []


def test_the_in_memory_store_honours_the_time_range() -> None:
    store = InMemoryHistoryStore()
    store.append_many([_point(second) for second in (1, 5, 9)])

    found = store.query(
        DEVICE,
        "temperature",
        start=datetime(2026, 9, 17, 12, 0, 4, tzinfo=timezone.utc),
        end=datetime(2026, 9, 17, 12, 0, 6, tzinfo=timezone.utc),
    )

    assert [point.timestamp.second for point in found] == [5]


def test_the_in_memory_store_honours_the_limit() -> None:
    store = InMemoryHistoryStore()
    store.append_many([_point(second) for second in range(10)])

    assert len(store.query(DEVICE, "temperature", limit=3)) == 3


def test_query_range_returns_oldest_first() -> None:
    """与 `query()` 的"新的在前"相反，这是有意的。

    它喂的是给人从上往下读的导出文件，让存储定顺序，省得每个调用方
    各自重排——但这个不对称确实容易踩，所以用例把它钉住。
    """
    store = InMemoryHistoryStore()
    store.append_many(
        [_point(3, value=3.0), _point(1, value=1.0), _point(2, value=2.0)]
    )

    found = store.query_range(
        datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 17, 12, 0, 9, tzinfo=timezone.utc),
    )

    assert [point.value for point in found] == [1.0, 2.0, 3.0]


def test_query_range_spans_devices_and_channels() -> None:
    """导出要的是"这个时段内全部设备全部通道"，不按设备/通道过滤。"""
    store = InMemoryHistoryStore()
    store.append_many(
        [
            _point(1, value=25.0),
            _point(1, channel="noise", value=49.5),
        ]
    )

    found = store.query_range(
        datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 17, 12, 0, 9, tzinfo=timezone.utc),
    )

    assert len(found) == 2


def test_query_range_excludes_what_falls_outside() -> None:
    store = InMemoryHistoryStore()
    store.append_many([_point(second) for second in (1, 5, 9)])

    found = store.query_range(
        datetime(2026, 9, 17, 12, 0, 4, tzinfo=timezone.utc),
        datetime(2026, 9, 17, 12, 0, 6, tzinfo=timezone.utc),
    )

    assert [point.timestamp.second for point in found] == [5]


def test_query_range_honours_an_explicit_limit() -> None:
    store = InMemoryHistoryStore()
    store.append_many([_point(second) for second in range(10)])

    found = store.query_range(
        datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 17, 12, 0, 9, tzinfo=timezone.utc),
        limit=3,
    )

    assert len(found) == 3


def test_the_null_store_answers_query_range_empty() -> None:
    assert (
        NullHistoryStore().query_range(
            datetime(2026, 9, 17, tzinfo=timezone.utc),
            datetime(2026, 9, 18, tzinfo=timezone.utc),
        )
        == []
    )


def test_the_in_memory_store_counts_everything_it_was_given() -> None:
    """count() 是全库计数，不受 device/channel 过滤影响——导出台账要用它。"""
    store = InMemoryHistoryStore()

    store.append_many([_point(1), _point(1, channel="noise")])

    assert store.count() == 2


def test_appending_nothing_changes_nothing() -> None:
    store = InMemoryHistoryStore()

    store.append_many([])

    assert store.count() == 0
