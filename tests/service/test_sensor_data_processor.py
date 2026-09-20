import pytest

from core.exceptions import NotFoundError
from service.data_models import DataPoint
from service.data_service_impl import InMemoryDataService
from service.sensor_data_processor import (
    HUMIDITY_ALARM_MAX,
    HUMIDITY_ALARM_MIN,
    NOISE_ALARM_MAX,
    TEMPERATURE_ALARM_MAX,
    AlarmBand,
    AlarmEvent,
    AlarmKind,
    ChannelStatistics,
    SensorDataProcessor,
    ThresholdStatus,
)

# -- statistics ---------------------------------------------------------------


def test_get_statistics_for_unknown_key_raises_not_found() -> None:
    processor = SensorDataProcessor(confirm_cycles=1)
    with pytest.raises(NotFoundError):
        processor.get_statistics("dev-1", "temperature")


def test_single_data_point_seeds_statistics() -> None:
    processor = SensorDataProcessor(confirm_cycles=1)
    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel="temperature", value=25.0)
    )

    stats = processor.get_statistics("dev-1", "temperature")
    assert stats.current == 25.0
    assert stats.minimum == 25.0
    assert stats.maximum == 25.0
    assert stats.average == 25.0
    assert stats.sample_count == 1


def test_statistics_accumulate_current_min_max_average() -> None:
    processor = SensorDataProcessor(confirm_cycles=1)
    for value in (20.0, 30.0, 10.0, 25.0):
        processor.handle_data_point(
            DataPoint(device_id="dev-1", channel="temperature", value=value)
        )

    stats = processor.get_statistics("dev-1", "temperature")
    assert stats.current == 25.0
    assert stats.minimum == 10.0
    assert stats.maximum == 30.0
    assert stats.average == pytest.approx((20.0 + 30.0 + 10.0 + 25.0) / 4)
    assert stats.sample_count == 4


def test_statistics_are_independent_per_device_and_channel() -> None:
    processor = SensorDataProcessor(confirm_cycles=1)
    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel="temperature", value=20.0)
    )
    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel="humidity", value=50.0)
    )
    processor.handle_data_point(
        DataPoint(device_id="dev-2", channel="temperature", value=99.0)
    )

    assert processor.get_statistics("dev-1", "temperature").current == 20.0
    assert processor.get_statistics("dev-1", "humidity").current == 50.0
    assert processor.get_statistics("dev-2", "temperature").current == 99.0


def test_non_numeric_value_is_ignored() -> None:
    processor = SensorDataProcessor(confirm_cycles=1)
    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel="status", value="ok")
    )

    with pytest.raises(NotFoundError):
        processor.get_statistics("dev-1", "status")


def test_bool_value_is_ignored() -> None:
    """bool is technically an int subclass in Python but not a meaningful reading."""

# 说明：
# 本文件的用例一律以 ``confirm_cycles=1`` 构造处理器：它们测的是**阈值规则与回调
# 分发**，不是"连续几次才算数"。确认逻辑自 2026-09-09 下沉到本模块后有自己的一组
# 用例（见文件末尾"报警确认"一节），分开写是为了让每个用例只测一件事——否则每个
# 阈值用例都要多塞一个数据点，读起来像在测确认。
    processor = SensorDataProcessor(confirm_cycles=1)
    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel="flag", value=True)
    )

    with pytest.raises(NotFoundError):
        processor.get_statistics("dev-1", "flag")


def test_invalid_data_point_is_marked_invalid_but_still_processed() -> None:
    """valid=False only marks protocol-level validity; the processor does
    not special-case it -- that is a future refinement, not this task's scope."""
    processor = SensorDataProcessor(confirm_cycles=1)
    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel="temperature", value=25.0, valid=False)
    )
    assert processor.get_statistics("dev-1", "temperature").current == 25.0


# -- alarms ---------------------------------------------------------------------


def test_temperature_above_threshold_triggers_alarm() -> None:
    processor = SensorDataProcessor(confirm_cycles=1)
    events: list[AlarmEvent] = []
    processor.on_alarm(events.append)

    processor.handle_data_point(
        DataPoint(
            device_id="dev-1",
            channel="temperature",
            value=TEMPERATURE_ALARM_MAX + 0.1,
        )
    )

    assert len(events) == 1
    assert events[0].kind is AlarmKind.ABOVE_MAX
    assert events[0].channel == "temperature"
    assert events[0].threshold == TEMPERATURE_ALARM_MAX


def test_temperature_at_or_below_threshold_does_not_trigger_alarm() -> None:
    processor = SensorDataProcessor(confirm_cycles=1)
    events: list[AlarmEvent] = []
    processor.on_alarm(events.append)

    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel="temperature", value=TEMPERATURE_ALARM_MAX)
    )
    processor.handle_data_point(
        DataPoint(
            device_id="dev-1",
            channel="temperature",
            value=TEMPERATURE_ALARM_MAX - 5,
        )
    )

    assert events == []


def test_humidity_below_threshold_triggers_alarm() -> None:
    processor = SensorDataProcessor(confirm_cycles=1)
    events: list[AlarmEvent] = []
    processor.on_alarm(events.append)

    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel="humidity", value=HUMIDITY_ALARM_MIN - 1)
    )

    assert len(events) == 1
    assert events[0].kind is AlarmKind.BELOW_MIN
    assert events[0].channel == "humidity"


def test_humidity_at_or_above_threshold_does_not_trigger_alarm() -> None:
    processor = SensorDataProcessor(confirm_cycles=1)
    events: list[AlarmEvent] = []
    processor.on_alarm(events.append)

    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel="humidity", value=HUMIDITY_ALARM_MIN)
    )
    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel="humidity", value=60.0)
    )

    assert events == []


def test_humidity_above_its_ceiling_triggers_alarm() -> None:
    """Added 2026-09-08. Chapter 9 measured 62~78%RH for most of a run --
    above the 40%~65% band GB 37488-2019 gives for air-conditioned public
    spaces -- and the one-sided rule in force at the time said nothing."""
    processor = SensorDataProcessor(confirm_cycles=1)
    events: list[AlarmEvent] = []
    processor.on_alarm(events.append)

    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel="humidity", value=HUMIDITY_ALARM_MAX + 1)
    )

    assert len(events) == 1
    assert events[0].kind is AlarmKind.ABOVE_MAX
    assert events[0].threshold == HUMIDITY_ALARM_MAX


def test_humidity_inside_its_band_stays_quiet() -> None:
    processor = SensorDataProcessor(confirm_cycles=1)
    events: list[AlarmEvent] = []
    processor.on_alarm(events.append)

    for value in (HUMIDITY_ALARM_MIN, 50.0, HUMIDITY_ALARM_MAX):
        processor.handle_data_point(
            DataPoint(device_id="dev-1", channel="humidity", value=value)
        )

    assert events == []


def test_a_normal_reading_is_reported_against_the_nearer_bound() -> None:
    """A status quoting an arbitrary side would report 62%RH as "well
    above 30%RH" when it is three points under the ceiling."""
    processor = SensorDataProcessor(confirm_cycles=1)
    seen: list[ThresholdStatus] = []
    processor.on_status(seen.append)

    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel="humidity", value=62.0)
    )
    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel="humidity", value=35.0)
    )

    assert [s.threshold for s in seen] == [HUMIDITY_ALARM_MAX, HUMIDITY_ALARM_MIN]
    assert [s.triggered for s in seen] == [False, False]


def test_an_alarm_band_needs_at_least_one_bound() -> None:
    with pytest.raises(ValueError):
        AlarmBand()


def test_an_alarm_band_rejects_a_floor_above_its_ceiling() -> None:
    """Silently accepting it would give a band no reading can satisfy,
    and every value would alarm on both sides at once."""
    with pytest.raises(ValueError):
        AlarmBand(minimum=70.0, maximum=30.0)


def test_noise_above_threshold_triggers_alarm() -> None:
    processor = SensorDataProcessor(confirm_cycles=1)
    events: list[AlarmEvent] = []
    processor.on_alarm(events.append)

    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel="noise", value=NOISE_ALARM_MAX + 5)
    )

    assert len(events) == 1
    assert events[0].kind is AlarmKind.ABOVE_MAX
    assert events[0].channel == "noise"


def test_unrelated_channel_never_triggers_alarm() -> None:
    processor = SensorDataProcessor(confirm_cycles=1)
    events: list[AlarmEvent] = []
    processor.on_alarm(events.append)

    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel="pressure", value=99999.0)
    )

    assert events == []


def test_multiple_alarm_callbacks_all_receive_the_event() -> None:
    processor = SensorDataProcessor(confirm_cycles=1)
    first: list[AlarmEvent] = []
    second: list[AlarmEvent] = []
    processor.on_alarm(first.append)
    processor.on_alarm(second.append)

    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel="noise", value=NOISE_ALARM_MAX + 1)
    )

    assert len(first) == 1
    assert len(second) == 1


# -- status (fires on every evaluated point, triggered or not) ------------------


def test_status_fires_with_triggered_false_for_a_normal_reading() -> None:
    processor = SensorDataProcessor(confirm_cycles=1)
    statuses: list[ThresholdStatus] = []
    processor.on_status(statuses.append)

    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel="temperature", value=20.0)
    )

    assert len(statuses) == 1
    assert statuses[0].triggered is False
    assert statuses[0].value == 20.0
    assert statuses[0].threshold == TEMPERATURE_ALARM_MAX


def test_status_fires_with_triggered_true_for_an_alarming_reading() -> None:
    processor = SensorDataProcessor(confirm_cycles=1)
    statuses: list[ThresholdStatus] = []
    processor.on_status(statuses.append)

    processor.handle_data_point(
        DataPoint(
            device_id="dev-1",
            channel="temperature",
            value=TEMPERATURE_ALARM_MAX + 1,
        )
    )

    assert len(statuses) == 1
    assert statuses[0].triggered is True


def test_status_lets_a_caller_observe_recovery_after_an_alarm() -> None:
    """The scenario on_alarm alone cannot support: knowing when a channel
    that previously alarmed has returned to normal."""
    processor = SensorDataProcessor(confirm_cycles=1)
    statuses: list[ThresholdStatus] = []
    processor.on_status(statuses.append)

    processor.handle_data_point(
        DataPoint(
            device_id="dev-1",
            channel="temperature",
            value=TEMPERATURE_ALARM_MAX + 1,
        )
    )
    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel="temperature", value=20.0)
    )

    assert [status.triggered for status in statuses] == [True, False]


def test_status_does_not_fire_for_a_channel_with_no_threshold_rule() -> None:
    processor = SensorDataProcessor(confirm_cycles=1)
    statuses: list[ThresholdStatus] = []
    processor.on_status(statuses.append)

    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel="pressure", value=1.0)
    )

    assert statuses == []


def test_on_status_does_not_affect_on_alarm_subscribers() -> None:
    """Purely additive: on_alarm's existing firing behavior (only on
    violation) is unchanged by also registering an on_status callback."""
    processor = SensorDataProcessor(confirm_cycles=1)
    alarms: list[AlarmEvent] = []
    statuses: list[ThresholdStatus] = []
    processor.on_alarm(alarms.append)
    processor.on_status(statuses.append)

    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel="temperature", value=20.0)
    )

    assert alarms == []
    assert len(statuses) == 1


# -- statistics callback (fires for any channel, not just threshold ones) -------


def test_on_statistics_fires_with_the_running_snapshot() -> None:
    processor = SensorDataProcessor(confirm_cycles=1)
    seen: list[tuple[str, str, ChannelStatistics]] = []
    processor.on_statistics(lambda d, c, s: seen.append((d, c, s)))

    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel="temperature", value=20.0)
    )
    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel="temperature", value=30.0)
    )

    assert len(seen) == 2
    device_id, channel, stats = seen[-1]
    assert device_id == "dev-1"
    assert channel == "temperature"
    assert stats.current == 30.0
    assert stats.minimum == 20.0
    assert stats.maximum == 30.0
    assert stats.average == 25.0
    assert stats.sample_count == 2


def test_on_statistics_fires_for_channels_with_no_threshold_rule() -> None:
    """Unlike on_status/on_alarm, on_statistics is not limited to
    temperature/humidity/noise -- any numeric channel qualifies."""
    processor = SensorDataProcessor(confirm_cycles=1)
    seen: list[ChannelStatistics] = []
    processor.on_statistics(lambda _d, _c, stats: seen.append(stats))

    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel="pressure", value=101.3)
    )

    assert len(seen) == 1
    assert seen[0].current == 101.3


def test_on_statistics_does_not_fire_for_non_numeric_values() -> None:
    processor = SensorDataProcessor(confirm_cycles=1)
    seen: list[ChannelStatistics] = []
    processor.on_statistics(lambda _d, _c, stats: seen.append(stats))

    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel="status", value="ok")
    )

    assert seen == []


# -- data flow: SensorSimulator -> DataService -> SensorDataProcessor -----------


def test_subscribe_to_receives_published_data_points() -> None:
    data_service = InMemoryDataService()
    processor = SensorDataProcessor(confirm_cycles=1)
    processor.subscribe_to(data_service, "dev-1", "temperature")

    data_service.publish(
        DataPoint(device_id="dev-1", channel="temperature", value=22.5)
    )

    stats = processor.get_statistics("dev-1", "temperature")
    assert stats.current == 22.5


def test_subscribe_to_triggers_alarms_through_data_service() -> None:
    data_service = InMemoryDataService()
    processor = SensorDataProcessor(confirm_cycles=1)
    events: list[AlarmEvent] = []
    processor.on_alarm(events.append)
    processor.subscribe_to(data_service, "dev-1", "noise")

    data_service.publish(
        DataPoint(device_id="dev-1", channel="noise", value=NOISE_ALARM_MAX + 10)
    )

    assert len(events) == 1


# -- 报警确认（2026-09-09 由 alarm_announcer 下沉至此） -----------------------


def _feed(processor: SensorDataProcessor, *values: float) -> list[bool]:
    seen: list[bool] = []
    processor.on_status(lambda s: seen.append(s.triggered))
    for value in values:
        processor.handle_data_point(
            DataPoint(device_id="dev-1", channel="noise", value=value)
        )
    return seen


def test_a_lone_spike_does_not_raise_an_alarm() -> None:
    """下沉的理由就在这里。此前 triggered 是逐点算的，直接喂给界面高亮与
    AlarmStateDispatcher（0x15 → LCD 位图），而语音要连续两次才响——
    于是单点尖峰让屏幕和 LCD 红一下再灭，语音全程没动静。
    同一个系统内部对"什么算报警"有两套标准，这才是缺陷本身。

    数值取自实测：长时间稳定性两次跑各有一个孤立点越过 80 dB
    （96.2 与 84.7），都是噪声传感器首帧伪值。"""
    processor = SensorDataProcessor()

    assert _feed(processor, 40.1, 96.2, 40.0, 39.7) == [False, False, False, False]


def test_two_consecutive_excursions_do_raise_one() -> None:
    processor = SensorDataProcessor()

    assert _feed(processor, 40.1, 85.0, 86.0, 87.0, 40.0) == [
        False,
        False,
        True,
        True,
        False,
    ]


def test_a_reading_back_inside_the_band_clears_the_count() -> None:
    """回到正常即清零：下一次越限要从头挣自己的确认，
    而不是接上几分钟前那次的计数。"""
    processor = SensorDataProcessor()

    assert _feed(processor, 85.0, 40.0, 85.0) == [False, False, False]


def test_a_flip_to_the_other_side_of_the_band_starts_over() -> None:
    """湿度自 2026-09-08 起有上下两界。由"太干"漂到"太湿"是一次新的越限，
    沿用上一次的计数会让第二次立刻报警。"""
    processor = SensorDataProcessor()
    seen: list[bool] = []
    processor.on_status(lambda s: seen.append(s.triggered))
    for value in (20.0, 80.0, 81.0):
        processor.handle_data_point(
            DataPoint(device_id="dev-1", channel="humidity", value=value)
        )

    assert seen == [False, False, True]


def test_confirmation_is_only_for_raising_not_for_clearing() -> None:
    """解除立即生效。对称确认会把报警多留三秒，而实测数据里没有任何
    在解除侧抖动的迹象——两次长跑各只越限一次，且都是单点。"""
    processor = SensorDataProcessor()

    assert _feed(processor, 85.0, 86.0, 40.0) == [False, True, False]


def test_confirm_cycles_must_be_at_least_one() -> None:
    with pytest.raises(ValueError):
        SensorDataProcessor(confirm_cycles=0)


# -- 报警回差（2026-09-09） ---------------------------------------------------


def test_clearing_needs_the_reading_to_come_back_inside_by_the_deadband() -> None:
    """回差只在**解除**侧生效：越线即报警，回到线内还不够，要回够一段才解除。

    实测依据：长时间稳定性那次跑，湿度整段压在 75.00%RH 上，靠 ±0.07%RH 的
    传感器噪声决定报不报警。没有回差时，停在 74.98~75.04 之间的读数会让报警
    随噪声通断。"""
    band = AlarmBand(minimum=30.0, maximum=75.0, hysteresis=0.5)

    # 未报警时按标称限值判定
    assert band.evaluate(75.01)[2] is True
    assert band.evaluate(74.98)[2] is False

    # 已在上界报警时，74.98 仍算越限——要跌破 74.5 才解除
    assert band.evaluate(74.98, AlarmKind.ABOVE_MAX)[2] is True
    assert band.evaluate(74.49, AlarmKind.ABOVE_MAX)[2] is False

    # 下界对称
    assert band.evaluate(30.02, AlarmKind.BELOW_MIN)[2] is True
    assert band.evaluate(30.51, AlarmKind.BELOW_MIN)[2] is False


def test_the_reported_bound_is_always_the_nominal_one() -> None:
    """读的人该看到标准定的那条线，而不是系统内部的死区。"""
    band = AlarmBand(maximum=75.0, hysteresis=0.5)

    _, threshold, triggered = band.evaluate(74.7, AlarmKind.ABOVE_MAX)
    assert threshold == 75.0
    assert triggered is True


def test_raising_is_never_delayed_by_the_deadband() -> None:
    """不对称是有意的：晚报一个真实报警是这套系统最不该做的事，
    而晚解除只是把提示多留一会儿。"""
    band = AlarmBand(maximum=75.0, hysteresis=5.0)

    assert band.evaluate(75.01)[2] is True          # 刚过线就报
    assert band.evaluate(75.01, None)[2] is True


def test_a_deadband_wider_than_the_band_is_refused() -> None:
    """两侧死区在中间相遇，就再没有"正常"可言——一旦报警便无从解除。"""
    with pytest.raises(ValueError):
        AlarmBand(minimum=30.0, maximum=31.0, hysteresis=0.6)
    with pytest.raises(ValueError):
        AlarmBand(maximum=75.0, hysteresis=-0.1)


def test_a_stateless_caller_gets_the_plain_comparison() -> None:
    """问答的取数层描述"这一个读数",手上没有状态可传，
    默认参数因此必须退化成不带回差的判定。"""
    band = AlarmBand(maximum=75.0, hysteresis=0.5)
    assert band.evaluate(74.7)[2] is False
