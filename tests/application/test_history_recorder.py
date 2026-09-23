"""`HistoryRecorder` 的回归测试。

设计见 `docs/decisions/06-history.md`。
这里守的核心只有一条，其余都是它的推论：**数据回调里绝不落盘**。
`InMemoryDataService.publish()` 是同步的，回调跑在采集线程上，
而那个线程的下一步就是取模型结果——把磁盘写放进去，等于把它塞进
维持界面响应的那条路径。2026-09-07 "在数据回调里下发命令重入串口"
是同一个错误在上一层的版本。
"""

from __future__ import annotations

from datetime import datetime, timezone

from application.history_recorder import HistoryRecorder
from service.data_models import DataPoint
from service.data_service_impl import InMemoryDataService
from service.history import HistoryPoint, InMemoryHistoryStore

DEVICE = "mcu-1"
CHANNEL = "temperature"


class _RecordingStore(InMemoryHistoryStore):
    """记下 append_many 被调用的时刻，用来断言"什么时候写"。"""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[int] = []

    def append_many(self, points: list[HistoryPoint]) -> None:
        self.calls.append(len(points))
        super().append_many(points)


class _Clock:
    """手推的时钟，免得用例去睡 5 秒。"""

    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def _point(second: int, *, value: object = 25.0, valid: bool = True) -> DataPoint:
    return DataPoint(
        device_id=DEVICE,
        channel=CHANNEL,
        value=value,
        timestamp=datetime(2026, 9, 17, 12, 0, second, tzinfo=timezone.utc),
        valid=valid,
    )


# -- 回调里不落盘 --------------------------------------------------------------


def test_the_callback_itself_never_writes() -> None:
    """本模块存在的全部理由。"""
    store = _RecordingStore()
    recorder = HistoryRecorder(store, batch_size=50)

    for second in range(10):
        recorder.handle_data_point(_point(second))

    assert store.calls == []
    assert recorder.pending == 10


def test_a_full_batch_is_written_only_when_the_poll_loop_asks() -> None:
    store = _RecordingStore()
    recorder = HistoryRecorder(store, batch_size=3)

    for second in range(3):
        recorder.handle_data_point(_point(second))
    assert store.calls == []

    assert recorder.flush_if_due() is True
    assert store.calls == [3]
    assert recorder.pending == 0


def test_a_partial_batch_waits_until_it_is_old_enough() -> None:
    """安静的通道不能把读数无限期攒在内存里——设备哑掉前那几条最值钱。"""
    clock = _Clock()
    store = _RecordingStore()
    recorder = HistoryRecorder(
        store, batch_size=50, max_age_seconds=5.0, now=clock
    )

    recorder.handle_data_point(_point(1))
    assert recorder.flush_if_due() is False

    clock.value = 4.9
    assert recorder.flush_if_due() is False

    clock.value = 5.0
    assert recorder.flush_if_due() is True
    assert store.calls == [1]


def test_nothing_pending_means_nothing_happens() -> None:
    """轮询循环每个周期都调它，绝大多数周期该是一次空转。"""
    store = _RecordingStore()
    recorder = HistoryRecorder(store)

    assert recorder.flush_if_due() is False
    assert store.calls == []


def test_the_age_clock_restarts_after_each_flush() -> None:
    clock = _Clock()
    store = _RecordingStore()
    recorder = HistoryRecorder(store, batch_size=50, max_age_seconds=5.0, now=clock)

    recorder.handle_data_point(_point(1))
    clock.value = 5.0
    recorder.flush_if_due()

    recorder.handle_data_point(_point(2))
    assert recorder.flush_if_due() is False

    clock.value = 10.0
    assert recorder.flush_if_due() is True
    assert store.calls == [1, 1]


# -- 退出前 flush --------------------------------------------------------------


def test_flush_writes_whatever_is_waiting() -> None:
    """退出路径上调用：最后几条不该因为不满一批就丢掉。"""
    store = _RecordingStore()
    recorder = HistoryRecorder(store, batch_size=50)
    recorder.handle_data_point(_point(1))

    recorder.flush()

    assert store.calls == [1]
    assert recorder.recorded == 1


def test_flushing_twice_writes_once() -> None:
    store = _RecordingStore()
    recorder = HistoryRecorder(store, batch_size=50)
    recorder.handle_data_point(_point(1))

    recorder.flush()
    recorder.flush()

    assert store.calls == [1]


# -- 值的转换 ------------------------------------------------------------------


def test_a_non_numeric_reading_is_counted_rather_than_stored() -> None:
    """`DataPoint.value` 是 `Any`，且硬件与 Modbus 两条路径都由
    `json.loads(...)["value"]` 构造——畸形帧能把字符串送到这里。
    计数而不抛，让坏帧不至于停掉采集；计数非零说明帧解码放过了东西。
    """
    store = _RecordingStore()
    recorder = HistoryRecorder(store, batch_size=1)

    recorder.handle_data_point(_point(1, value="不是数字"))

    assert recorder.skipped == 1
    assert recorder.pending == 0
    assert store.calls == []


def test_a_bad_reading_does_not_cost_the_good_ones_their_place() -> None:
    store = _RecordingStore()
    recorder = HistoryRecorder(store, batch_size=2)

    recorder.handle_data_point(_point(1, value=25.0))
    recorder.handle_data_point(_point(2, value=None))
    recorder.handle_data_point(_point(3, value=26.0))
    recorder.flush()

    assert recorder.skipped == 1
    assert [point.value for point in store.query(DEVICE, CHANNEL)] == [26.0, 25.0]


def test_an_integer_reading_is_stored_as_a_float() -> None:
    store = _RecordingStore()
    recorder = HistoryRecorder(store, batch_size=1)

    recorder.handle_data_point(_point(1, value=25))
    recorder.flush_if_due()

    assert store.query(DEVICE, CHANNEL)[0].value == 25.0


def test_an_invalid_reading_is_recorded_not_dropped() -> None:
    """无效读数是链路质量的证据，在入口处丢掉就补不回来了。"""
    store = _RecordingStore()
    recorder = HistoryRecorder(store, batch_size=1)

    recorder.handle_data_point(_point(1, value=0.0, valid=False))
    recorder.flush_if_due()

    assert store.query(DEVICE, CHANNEL)[0].valid is False


def test_the_original_timestamp_survives() -> None:
    """存的是读数产生的时刻，不是落盘的时刻——攒批意味着两者必然不同。"""
    store = _RecordingStore()
    recorder = HistoryRecorder(store, batch_size=1)
    point = _point(7)

    recorder.handle_data_point(point)
    recorder.flush_if_due()

    assert store.query(DEVICE, CHANNEL)[0].timestamp == point.timestamp


# -- 订阅 ----------------------------------------------------------------------


def test_subscribing_records_what_the_data_service_publishes() -> None:
    store = _RecordingStore()
    recorder = HistoryRecorder(store, batch_size=1)
    data_service = InMemoryDataService()
    recorder.subscribe_to(data_service, DEVICE, CHANNEL)

    data_service.publish(_point(1, value=25.5))
    recorder.flush_if_due()

    assert [point.value for point in store.query(DEVICE, CHANNEL)] == [25.5]


def test_only_subscribed_channels_are_recorded() -> None:
    store = _RecordingStore()
    recorder = HistoryRecorder(store, batch_size=1)
    data_service = InMemoryDataService()
    recorder.subscribe_to(data_service, DEVICE, CHANNEL)

    data_service.publish(
        DataPoint(device_id=DEVICE, channel="noise", value=49.5)
    )
    recorder.flush_if_due()

    assert store.count() == 0
