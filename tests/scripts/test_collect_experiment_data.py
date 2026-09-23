"""Tests for scripts/collect_experiment_data.py's statistics.

The recording half needs real hardware, but the part that matters for the
results -- the arithmetic that turns raw frames into the numbers that will be
printed in tables -- is a pure function and is tested here. A wrong loss rate
or a wrong period average would end up in a report unnoticed otherwise.
"""

from __future__ import annotations

import pytest

from scripts.collect_experiment_data import (
    NOISE_ALARM_MAX,
    Record,
    group_cycles,
    modbus_stats,
    parse_cues,
    sample_table,
    summarize,
    threshold_segments,
    to_markdown,
)


def _series(channel: str, start: float, step: float, values: list[float]):
    return [
        Record(
            elapsed=start + i * step,
            wall_clock="12:00:00.000",
            channel=channel,
            value=v,
            valid=True,
        )
        for i, v in enumerate(values)
    ]


def test_counts_and_value_statistics() -> None:
    records = _series("temperature", 0.0, 3.0, [24.0, 26.0, 28.0])
    summary = summarize(records, duration=9.0, error_count=0, ignored_count=0)

    stats = summary["channels"]["temperature"]
    assert stats["count"] == 3
    assert stats["value_min"] == 24.0
    assert stats["value_max"] == 28.0
    assert stats["value_mean"] == 26.0
    assert summary["total_frames"] == 3


def test_period_statistics_use_gaps_between_same_channel_frames() -> None:
    records = _series("humidity", 0.0, 3.0, [50.0, 51.0, 52.0, 53.0])
    stats = summarize(records, duration=12.0, error_count=0, ignored_count=0)[
        "channels"
    ]["humidity"]

    assert stats["gap_mean"] == 3.0
    assert stats["gap_min"] == 3.0
    assert stats["gap_max"] == 3.0
    assert stats["gap_stdev"] == 0.0


def test_a_steady_stream_reports_no_loss_even_if_period_differs_from_design():
    """The regression this pins down: a firmware period slightly longer than
    the design value must NOT be reported as frame loss.

    Measured on real hardware (2026-08-17): design period 3.000 s, actual
    3.093 s. Counting "expected frames" as duration/design_period made a
    clean 59-frame run look like 1.67% loss, which is simply wrong.
    """
    records = _series("temperature", 0.51, 3.093, [25.0] * 59)
    stats = summarize(records, duration=180.0, error_count=0, ignored_count=0)[
        "channels"
    ]["temperature"]

    assert stats["dropped"] == 0
    assert stats["loss_rate"] == 0.0
    assert stats["period_deviation"] is not None
    assert abs(stats["period_deviation"] - 0.031) < 0.005


def test_a_doubled_gap_counts_as_one_dropped_frame() -> None:
    """Real loss shows up as a gap of about twice the normal interval."""
    records = _series("noise", 0.0, 3.0, [40.0] * 5)
    # 在第 3 帧之后人为制造一次 6 s 的空档（丢了一帧）
    shifted = records[:3] + [
        Record(r.elapsed + 3.0, r.wall_clock, r.channel, r.value, r.valid)
        for r in records[3:]
    ]
    stats = summarize(shifted, duration=18.0, error_count=0, ignored_count=0)[
        "channels"
    ]["noise"]

    assert stats["dropped"] == 1
    assert abs(stats["loss_rate"] - 1 / 6) < 1e-9


def test_two_consecutive_missing_frames_are_both_counted() -> None:
    records = _series("humidity", 0.0, 3.0, [50.0] * 4)
    shifted = records[:2] + [
        Record(r.elapsed + 6.0, r.wall_clock, r.channel, r.value, r.valid)
        for r in records[2:]
    ]
    stats = summarize(shifted, duration=24.0, error_count=0, ignored_count=0)[
        "channels"
    ]["humidity"]

    assert stats["dropped"] == 2


def test_invalid_points_are_excluded_from_value_statistics() -> None:
    records = _series("temperature", 0.0, 3.0, [25.0, 26.0])
    records.append(
        Record(elapsed=6.0, wall_clock="12:00:06.000", channel="temperature",
               value=0.0, valid=False)
    )
    stats = summarize(records, duration=9.0, error_count=0, ignored_count=0)[
        "channels"
    ]["temperature"]

    # 计入帧数（它确实收到了），但不污染数值统计
    assert stats["count"] == 3
    assert stats["value_max"] == 26.0


def test_single_frame_has_no_period_statistics() -> None:
    records = _series("temperature", 0.0, 3.0, [25.0])
    stats = summarize(records, duration=3.0, error_count=0, ignored_count=0)[
        "channels"
    ]["temperature"]

    assert stats["gap_mean"] is None
    assert stats["gap_stdev"] is None


def test_sample_table_holds_latest_value_per_instant() -> None:
    records = _series("temperature", 0.0, 3.0, [24.0, 25.0, 26.0])
    table = sample_table(records, every=3.0)

    assert "| 时刻/s | temperature |" in table
    assert "| 0 | 24.00 |" in table
    assert "| 6 | 26.00 |" in table


def test_markdown_reports_error_counters() -> None:
    records = _series("temperature", 0.0, 3.0, [25.0, 25.5])
    summary = summarize(records, duration=6.0, error_count=7, ignored_count=2)
    text = to_markdown(summary, "测试")

    assert "帧同步错误（丢弃的非法字节段）：7" in text
    assert "已忽略的非数据帧：2" in text
    assert "# 实验记录：测试" in text


# --------------------------------------------------------------------------
# 采集周期归组与 Modbus 应答成功率（噪声通道到货后新增）
#
# 这一组测试钉住的是一个真实的误判风险：Modbus 读失败时固件根本不上报噪声通道
# （User/main.c: ``if (data.noise.valid)``），若沿用通用的"间隔跳变"丢帧口径，
# 会把传感器侧的应答失败记成通信链路丢帧。
# --------------------------------------------------------------------------


def _cycle(at: float, channels: list[str]) -> list[Record]:
    """One acquisition cycle: all channels arrive back to back."""
    return [
        Record(
            elapsed=at + i * 0.02,  # 同一周期内各通道相隔毫秒级
            wall_clock="12:00:00.000",
            channel=channel,
            value=1.0,
            valid=True,
        )
        for i, channel in enumerate(channels)
    ]


_ALL = ["temperature", "humidity", "noise"]


def test_frames_arriving_together_form_one_cycle() -> None:
    records = _cycle(0.0, _ALL) + _cycle(3.0, _ALL)

    cycles = group_cycles(records, expected_interval=3.0)

    assert cycles == [set(_ALL), set(_ALL)]


def test_a_cycle_missing_only_noise_is_a_modbus_failure_not_frame_loss() -> None:
    """The distinction this whole feature exists for."""
    records = (
        _cycle(0.0, _ALL)
        + _cycle(3.0, ["temperature", "humidity"])  # Modbus 超时
        + _cycle(6.0, _ALL)
    )

    stats = modbus_stats(group_cycles(records, expected_interval=3.0))

    assert stats["cycles_total"] == 3
    assert stats["cycles_with_noise"] == 2
    assert stats["cycles_without_noise"] == 1
    assert stats["success_rate"] == pytest.approx(2 / 3)


def test_an_entirely_missing_cycle_is_not_blamed_on_modbus() -> None:
    """A gap where *no* channel arrived is a link problem, not a sensor one.

    It must not drag the Modbus success rate down, or the noise sensor would
    be blamed for something the serial link did.
    """
    records = _cycle(0.0, _ALL) + _cycle(6.0, _ALL)  # t=3 整个周期缺失

    stats = modbus_stats(group_cycles(records, expected_interval=3.0))

    assert stats["cycles_total"] == 2
    assert stats["cycles_without_noise"] == 0
    assert stats["success_rate"] == 1.0


def test_summary_omits_modbus_section_when_there_is_no_noise_channel() -> None:
    """Re-running a report over an older temperature-only CSV must not invent
    a Modbus success rate for a sensor that was not connected yet."""
    records = _series("temperature", 0.0, 3.0, [25.0, 25.5])

    summary = summarize(records, duration=6.0, error_count=0, ignored_count=0)

    assert summary["modbus"] is None
    assert "Modbus 链路可靠性" not in to_markdown(summary, "旧实验")


def test_markdown_reports_modbus_success_rate_and_warns_about_loss_column():
    records = (
        _cycle(0.0, _ALL)
        + _cycle(3.0, ["temperature", "humidity"])
        + _cycle(6.0, _ALL)
        + _cycle(9.0, _ALL)
    )
    summary = summarize(records, duration=12.0, error_count=0, ignored_count=0)

    text = to_markdown(summary, "噪声试运行")

    assert "## Modbus 链路可靠性（噪声通道专有）" in text
    assert "**75.00%**" in text
    assert "不可直接当作链路丢帧" in text


def test_period_table_warns_when_modbus_failures_inflate_the_noise_row() -> None:
    """A failed Modbus read leaves a double-length gap, which inflates the
    noise row's mean and stdev. Without a warning a report could quote those
    as "the noise channel's period is unstable" -- it is not; some reads
    failed. The median-based deviation column stays trustworthy."""
    records = (
        _cycle(0.0, _ALL)
        + _cycle(3.0, ["temperature", "humidity"])
        + _cycle(6.0, _ALL)
        + _cycle(9.0, _ALL)
    )
    summary = summarize(records, duration=12.0, error_count=0, ignored_count=0)

    text = to_markdown(summary, "噪声试运行")

    assert "会把该行的平均值与标准差显著抬高" in text
    assert "不是固件采集周期不稳" in text


def test_no_period_warning_when_every_modbus_read_succeeded() -> None:
    records = _cycle(0.0, _ALL) + _cycle(3.0, _ALL) + _cycle(6.0, _ALL)
    summary = summarize(records, duration=9.0, error_count=0, ignored_count=0)

    assert "显著抬高" not in to_markdown(summary, "噪声试运行")


def _noise(start: float, values: list[float]) -> list[Record]:
    return [
        Record(start + i * 3.0, "12:00:00.000", "noise", v, True)
        for i, v in enumerate(values)
    ]


def test_threshold_segments_group_consecutive_readings_by_alarm_state() -> None:
    records = _noise(0.0, [40.0, 40.0, 85.0, 86.0, 84.0, 39.0])

    segments = threshold_segments(records)

    assert [s["triggered"] for s in segments] == [False, True, False]
    assert [s["samples"] for s in segments] == [2, 3, 1]


def test_a_sustained_alarm_is_distinguishable_from_flapping() -> None:
    """A min/max table cannot tell these apart; the segment table must."""
    sustained = threshold_segments(_noise(0.0, [85.0] * 6))
    flapping = threshold_segments(_noise(0.0, [81.0, 79.0, 81.0, 79.0, 81.0, 79.0]))

    assert len([s for s in sustained if s["triggered"]]) == 1
    assert len([s for s in flapping if s["triggered"]]) == 3


def test_report_omits_the_alarm_section_when_nothing_exceeded_the_threshold():
    """The earlier 56 dB step run must not grow an empty alarm section."""
    summary = summarize(
        _noise(0.0, [38.0, 56.0, 56.0, 38.0]),
        duration=12.0,
        error_count=0,
        ignored_count=0,
    )

    assert "噪声越限与报警状态" not in to_markdown(summary, "噪声阶跃响应")


def test_report_counts_alarm_triggers_and_longest_sustained_run() -> None:
    records = _noise(0.0, [38.0, 85.0, 86.0, 85.0, 38.0, 85.0, 38.0])
    summary = summarize(records, duration=21.0, error_count=0, ignored_count=0)

    text = to_markdown(summary, "噪声越限报警")

    assert "## 噪声越限与报警状态（阈值 80 dB）" in text
    assert "- 报警触发次数：**2**" in text
    assert "（3 个采样点）" in text


def test_alarm_threshold_comes_from_the_service_layer_not_a_local_copy() -> None:
    """If the two ever diverge, the report would call a reading "over the
    limit" that the UI does not actually alarm on."""
    from service.sensor_data_processor import NOISE_ALARM_MAX as service_threshold

    assert NOISE_ALARM_MAX == service_threshold


def test_a_run_with_no_noise_frames_at_all_says_so_loudly() -> None:
    """The 2026-08-18 background-noise run produced 291 cycles and zero noise
    frames (the module turned out to be unpowered), but the report simply
    omitted the Modbus section -- indistinguishable from an experiment that
    never involved noise. A silently missing channel must not look normal."""
    records = [
        r
        for i in range(4)
        for r in _cycle(i * 3.0, ["temperature", "humidity"])
    ]
    summary = summarize(records, duration=12.0, error_count=0, ignored_count=0)

    text = to_markdown(summary, "环境本底噪声")

    assert summary["noise_frames"] == 0
    assert "## 噪声通道：本次采集未收到任何数据" in text
    assert "本次数据不能用于噪声通道的任何结论" in text


def test_a_healthy_run_does_not_show_the_missing_channel_warning() -> None:
    records = _cycle(0.0, _ALL) + _cycle(3.0, _ALL)
    summary = summarize(records, duration=6.0, error_count=0, ignored_count=0)

    text = to_markdown(summary, "噪声试运行")

    assert "本次采集未收到任何数据" not in text
    assert "Modbus 应答成功率" in text


def test_cue_arguments_are_parsed_and_sorted() -> None:
    assert parse_cues(["120:停止播放", "60:开始播放白噪声"]) == [
        (60.0, "开始播放白噪声"),
        (120.0, "停止播放"),
    ]


def test_a_malformed_cue_is_rejected_with_a_readable_message() -> None:
    with pytest.raises(ValueError, match="无法解析的 --cue 参数"):
        parse_cues(["开始播放"])
