"""Record real STM32 data from the serial link and produce report-ready tables.

Why a separate tool rather than reading numbers off the GUI: an experiment needs
*quantified* results (frame counts, period jitter, error rates), and reading
them off a screen is neither accurate nor repeatable. This script logs every
received frame with a timestamp, then computes the statistics and emits both
a CSV (raw data, for plotting) and a Markdown table (paste straight into a
report).

It deliberately reuses the project's own receive path --
``SerialChannel`` -> ``HardwareDeviceReceiver`` -- rather than re-implementing
frame parsing. So the CRC checks, the byte-stream reassembly and the
``error_count``/``ignored_frame_count`` counters reported here are the real
ones from the system under test, not a second implementation that might
disagree with it.

**The serial port is exclusive**: close run_all_界面加网关.bat /
run_gui_hardware_真实硬件界面.bat /
any serial terminal before running this, or it will fail with
PermissionError(13).

Usage::

    # 10-minute stability run
    python scripts/collect_experiment_data.py --port COM10 --duration 600 \
        --label 长时间稳定性

    # 3-minute step-response run (breathe on the sensor midway)
    python scripts/collect_experiment_data.py --port COM10 --duration 180 \
        --label 温度阶跃响应 --sample-every 10
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
_SCRIPTS_DIR = Path(__file__).resolve().parent
for _path in (_SRC_DIR, _SCRIPTS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from recordings import RECORDINGS_DIR  # noqa: E402

from application.hardware_runtime import HardwareDeviceReceiver  # noqa: E402
from communication.exceptions import SerialConnectionError  # noqa: E402
from communication.serial import SerialChannel  # noqa: E402
from service.data_service_impl import InMemoryDataService  # noqa: E402

# 阈值从 service 层取，不在本脚本里另写一份字面量——报告里说的"越限"必须与
# 界面上真正触发报警的判据是同一个数，否则两边会各说各话
from service.sensor_data_processor import NOISE_ALARM_MAX  # noqa: E402

DEFAULT_BAUDRATE = 115200
DEFAULT_WIRE_ID = 1  # 与固件 User/main.c 的 STM32_DEVICE_ID 一致
DEFAULT_DEVICE_ID = "mcu-1"
DEFAULT_INTERVAL_SECONDS = 3.0  # 固件 SENSOR_CYCLE_INTERVAL_TICKS = 300 * 10ms
_POLL_SLEEP_SECONDS = 0.05
# 约 10 个采集周期后仍无噪声帧就预警——足够排除偶发超时，又不至于让操作者
# 白等一整场（本底实验曾因模块未上电空跑 15 分钟）
_NOISE_WARN_AFTER_SECONDS = 30.0

# 噪声通道单列出来，是因为只有它经 Modbus 请求-应答获取，失败方式与
# 温湿度（本地 I2C）不同，统计口径也不同。见 modbus_stats()。
NOISE_CHANNEL = "noise"


@dataclass(frozen=True)
class Record:
    """One received data point, with the moment it arrived."""

    elapsed: float  # 自采集开始的秒数（单调时钟，不受系统时间调整影响）
    wall_clock: str  # 便于与照片/录像对齐的墙上时间
    channel: str
    value: float
    valid: bool


def group_cycles(
    records: list[Record],
    expected_interval: float = DEFAULT_INTERVAL_SECONDS,
) -> list[set[str]]:
    """Group records into firmware acquisition cycles by arrival time.

    The firmware reports all three channels back to back at the end of one
    cycle (``User/main.c::finish_cycle_and_report``), so frames of one cycle
    arrive milliseconds apart while cycles are ``expected_interval`` apart.
    Anything closer together than half the interval therefore belongs to the
    same cycle.

    Grouping by time rather than by anchoring on the temperature frame is
    deliberate: temperature and humidity share the AHT20 and fail together
    (``main.c`` sets both ``valid`` flags from one read), so a cycle where the
    AHT20 failed has no temperature frame to anchor on but may still carry a
    noise frame.

    Returns one set of channel names per cycle, in arrival order.
    """
    if not records:
        return []
    threshold = expected_interval / 2 if expected_interval > 0 else 0.0
    cycles: list[set[str]] = [{records[0].channel}]
    for previous, current in zip(records, records[1:], strict=False):
        if current.elapsed - previous.elapsed > threshold:
            cycles.append(set())
        cycles[-1].add(current.channel)
    return cycles


def modbus_stats(
    cycles: list[set[str]],
    noise_channel: str = NOISE_CHANNEL,
) -> dict[str, Any]:
    """Success rate of the noise sensor's Modbus request/response exchange.

    Why the noise channel needs its own metric rather than reusing the
    per-channel frame-loss figure: on a failed Modbus read the firmware does
    not report the channel at all (``main.c``: ``if (data.noise.valid)``), it
    only logs to the debug UART. A missing noise frame is therefore a
    *sensor-side* failure, whereas the generic loss metric would attribute it
    to the serial link -- exactly the kind of misattribution the period-vs-loss
    analysis already had to correct once.

    Because all channels are reported within one cycle, the two causes can be
    told apart: a cycle that carried other channels but no noise frame is a
    Modbus failure; a cycle that carried nothing at all is a link problem and
    shows up as a missing cycle instead.
    """
    considered = [c for c in cycles if c]
    with_noise = [c for c in considered if noise_channel in c]
    # 只在"该周期确实收到了别的通道"时才算一次 Modbus 失败——整周期空白属于
    # 链路问题，由丢帧统计负责，不该记到传感器头上
    failures = [c for c in considered if noise_channel not in c and c]
    total = len(with_noise) + len(failures)
    return {
        "cycles_total": len(considered),
        "cycles_with_noise": len(with_noise),
        "cycles_without_noise": len(failures),
        "success_rate": (len(with_noise) / total) if total else None,
    }


def threshold_segments(
    records: list[Record],
    channel: str = NOISE_CHANNEL,
    threshold: float = NOISE_ALARM_MAX,
) -> list[dict[str, Any]]:
    """Split the channel's series into runs of "over threshold" / "under".

    The alarm rule is evaluated per data point with no hysteresis
    (``service/sensor_data_processor.py::_evaluate_threshold``: a bare
    ``value > threshold``), so what the UI shows is exactly this sequence of
    runs. Reporting how long each run lasted, rather than only how many
    points exceeded, is what distinguishes "the alarm held steady while the
    source was on" from "the alarm flickered" -- the two look identical in a
    min/max table.
    """
    series = [r for r in records if r.channel == channel and r.valid]
    if not series:
        return []
    segments: list[dict[str, Any]] = []
    for record in series:
        triggered = record.value > threshold
        if segments and segments[-1]["triggered"] == triggered:
            segments[-1]["end"] = record.elapsed
            segments[-1]["samples"] += 1
        else:
            segments.append(
                {
                    "triggered": triggered,
                    "start": record.elapsed,
                    "end": record.elapsed,
                    "samples": 1,
                }
            )
    return segments


def summarize(
    records: list[Record],
    duration: float,
    error_count: int,
    ignored_count: int,
    expected_interval: float = DEFAULT_INTERVAL_SECONDS,
) -> dict[str, Any]:
    """Compute every statistic the report needs. Pure function -- unit tested.

    Frame loss is estimated per channel rather than globally: the firmware
    skips a channel whose sensor read failed (see User/main.c), so a missing
    frame is meaningful information about that sensor, not about the link.
    """
    channels = sorted({r.channel for r in records})
    per_channel: dict[str, dict[str, Any]] = {}

    for channel in channels:
        series = [r for r in records if r.channel == channel]
        values = [r.value for r in series if r.valid]
        gaps = [
            b.elapsed - a.elapsed for a, b in zip(series, series[1:], strict=False)
        ]
        expected = int(duration / expected_interval) if expected_interval > 0 else 0
        gap_mean = statistics.fmean(gaps) if gaps else None
        # 判丢帧的参照量用**中位数**而不是均值：丢帧本身会把均值抬高，
        # 丢得越多参照越偏，可能把两帧的空档误判成一帧。中位数对离群值免疫。
        gap_reference = statistics.median(gaps) if gaps else None

        # 丢帧必须按"间隔是否出现跳变"判断，不能用"实收帧数 vs 设计周期折算的
        # 理论帧数"——固件的实际周期与设计值存在系统性偏差（见 period_deviation），
        # 那样算会把周期偏差误报成丢帧。一次丢帧的特征是该处间隔约为正常值的整数倍。
        dropped = 0
        if gap_reference and gap_reference > 0:
            for gap in gaps:
                missed = round(gap / gap_reference) - 1
                if missed > 0:
                    dropped += missed

        per_channel[channel] = {
            "count": len(series),
            "expected": expected,
            "dropped": dropped,
            "loss_rate": (
                0.0 if (len(series) + dropped) == 0
                else dropped / (len(series) + dropped)
            ),
            # 偏差必须与表格中"平均间隔"列同口径，即用 gap_mean 而非 gap_reference
            # （中位数）。二者混用会让同一行的两列对不上：读者用平均间隔除以设计周期
            # 算出的偏差，与本字段给出的数不一致。中位数只用于上面的丢帧判定。
            "period_deviation": (
                None
                if gap_mean is None or expected_interval <= 0
                else (gap_mean - expected_interval) / expected_interval
            ),
            "value_min": min(values) if values else None,
            "value_max": max(values) if values else None,
            "value_mean": statistics.fmean(values) if values else None,
            "gap_mean": gap_mean,
            # 标准差需要至少两个样本
            "gap_stdev": statistics.stdev(gaps) if len(gaps) > 1 else None,
            "gap_min": min(gaps) if gaps else None,
            "gap_max": max(gaps) if gaps else None,
        }

    cycles = group_cycles(records, expected_interval)
    return {
        "duration": duration,
        "total_frames": len(records),
        "error_count": error_count,
        "ignored_count": ignored_count,
        "expected_interval": expected_interval,
        "channels": per_channel,
        "cycles": len(cycles),
        "threshold_segments": threshold_segments(records),
        # 无论噪声通道有没有数据都算：**一帧都没收到**同样是必须被看见的结果，
        # 此前只在 NOISE_CHANNEL 出现过时才统计，导致"噪声全程失败"的报告
        # 与"这个实验本来就不含噪声"长得一模一样，整节被静默跳过
        "noise_frames": sum(1 for r in records if r.channel == NOISE_CHANNEL),
        # 仅在本次采集确实含噪声通道时才有意义；温湿度-only 的历史 CSV
        # 重新生成报告时会是 None，报告里相应整节不输出
        "modbus": modbus_stats(cycles) if NOISE_CHANNEL in channels else None,
    }


def _fmt(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def to_markdown(summary: dict[str, Any], label: str, samples: str = "") -> str:
    """Render the summary as report-ready Markdown tables."""
    lines = [
        f"# 实验记录：{label}",
        "",
        f"- 采集时长：{summary['duration']:.1f} s",
        f"- 期望采集周期：{summary['expected_interval']:.1f} s",
        f"- 接收数据帧总数：{summary['total_frames']}",
        f"- 采集周期数：{summary.get('cycles', '—')}",
        f"- 帧同步错误（丢弃的非法字节段）：{summary['error_count']}",
        f"- 已忽略的非数据帧：{summary['ignored_count']}",
        "",
        "## 各通道接收情况",
        "",
        "| 通道 | 实收帧数 | 缺失帧数 | 丢帧率 | 最小值 | 最大值 | 平均值 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for channel, s in summary["channels"].items():
        lines.append(
            f"| {channel} | {s['count']} | {s['dropped']} | "
            f"{s['loss_rate'] * 100:.2f}% | {_fmt(s['value_min'])} | "
            f"{_fmt(s['value_max'])} | {_fmt(s['value_mean'])} |"
        )
    lines += [
        "",
        "> 缺失帧数按**间隔跳变**判定（某处间隔约为正常间隔的整数倍即计为丢帧），"
        "而非用实收帧数与设计周期折算的理论帧数相减——固件实际周期与设计值存在"
        "系统性偏差（见下表），后者会把周期偏差误报为丢帧。",
    ]

    modbus = summary.get("modbus")
    if not modbus and summary.get("cycles") and not summary.get("noise_frames"):
        lines += [
            "",
            "## 噪声通道：本次采集未收到任何数据",
            "",
            f"本次共 {summary['cycles']} 个采集周期，**噪声通道一帧都没有收到**，"
            "而温湿度通道正常。可能原因按排查顺序：",
            "",
            "1. **噪声模块未上电**（电源线未接好、或接到了 3.3V 而非 5V 排针）；",
            "2. TXD/RXD 接反，或 P2 排针接触不良；",
            "3. 模块协议模式/波特率与固件假设不一致。",
            "",
            "> 温湿度正常说明开发板、USART1 链路与上位机都没有问题，"
            "问题被限定在噪声模块自身的供电或 USART3 接线上。"
            "**本次数据不能用于噪声通道的任何结论。**",
        ]
    if modbus:
        rate = modbus["success_rate"]
        lines += [
            "",
            f"> **注意：上表 `{NOISE_CHANNEL}` 一行的“缺失帧数”不可直接当作链路丢帧。**"
            "Modbus 读取失败时固件不上报该通道"
            "（`User/main.c`：`if (data.noise.valid)`），"
            "因此噪声通道的缺失反映的是**传感器侧的应答失败**，不是通信链路丢帧。"
            "正确口径见下一节。",
            "",
            "## Modbus 链路可靠性（噪声通道专有）",
            "",
            "噪声是三个通道中唯一经请求—应答往返获取的。由于三通道在同一采集周期内"
            "上报，可据此把“传感器没答上来”与“链路把帧弄丢了”区分开：",
            "",
            "| 指标 | 数值 |",
            "| --- | --- |",
            f"| 采集周期总数 | {modbus['cycles_total']} |",
            f"| 成功取得噪声读数的周期 | {modbus['cycles_with_noise']} |",
            f"| Modbus 读取失败的周期 | {modbus['cycles_without_noise']} |",
            "| **Modbus 应答成功率** | "
            + ("—" if rate is None else f"**{rate * 100:.2f}%**")
            + " |",
            "",
            "> 判定方式：某个采集周期收到了别的通道、唯独没有噪声帧，即计为一次 "
            "Modbus 读取失败；整个周期一帧都没有则属于链路问题，计入上表的缺失帧数。",
        ]

    lines += [
        "",
        "## 采集周期实测（相邻同通道帧的时间间隔）",
        "",
        "| 通道 | 平均间隔/s | 标准差/s | 最小/s | 最大/s | 相对设计周期偏差 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for channel, s in summary["channels"].items():
        deviation = s["period_deviation"]
        dev_text = "—" if deviation is None else f"{deviation * 100:+.2f}%"
        lines.append(
            f"| {channel} | {_fmt(s['gap_mean'], 3)} | {_fmt(s['gap_stdev'], 3)} | "
            f"{_fmt(s['gap_min'], 3)} | {_fmt(s['gap_max'], 3)} | {dev_text} |"
        )

    if modbus and modbus["cycles_without_noise"]:
        lines += [
            "",
            f"> **引用 `{NOISE_CHANNEL}` 一行的平均间隔与标准差时请注意**："
            f"本次有 {modbus['cycles_without_noise']} 个周期 Modbus 读取失败、"
            "未上报噪声帧，这些位置的间隔约为正常值的两倍，会把该行的平均值与"
            "标准差显著抬高。**这反映的是传感器应答失败，不是固件采集周期不稳**——"
            "末列的偏差取自间隔**中位数**，不受这些离群值影响，可直接引用；"
            "若需要引用噪声通道的周期稳定性，应改用中位数或剔除失败周期后再统计。",
        ]

    segments = summary.get("threshold_segments") or []
    if any(seg["triggered"] for seg in segments):
        triggered_runs = [s for s in segments if s["triggered"]]
        lines += [
            "",
            f"## 噪声越限与报警状态（阈值 {NOISE_ALARM_MAX:.0f} dB）",
            "",
            "| 区间 | 状态 | 起止/s | 持续/s | 采样点数 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for index, seg in enumerate(segments, start=1):
            state = "**越限（报警）**" if seg["triggered"] else "正常"
            lines.append(
                f"| {index} | {state} | {seg['start']:.1f} ~ {seg['end']:.1f} | "
                f"{seg['end'] - seg['start']:.1f} | {seg['samples']} |"
            )
        longest = max(s["end"] - s["start"] for s in triggered_runs)
        most_samples = max(s["samples"] for s in triggered_runs)
        lines += [
            "",
            f"- 报警触发次数：**{len(triggered_runs)}**",
            f"- 最长连续越限：**{longest:.1f} s**（{most_samples} 个采样点）",
            "",
            "> 阈值判定**无回差**（`service/sensor_data_processor.py` 中为逐点比较 "
            f"`value > {NOISE_ALARM_MAX:.0f}`）。因此若某次越限只持续 1~2 个采样点、"
            "且与正常区间交替出现，应判读为读数在阈值附近抖动，而非声源真的反复"
            "启停；反之，连续多个采样点稳定越限才能证明报警在持续生效。",
        ]

    if samples:
        lines += ["", "## 数值随时间变化", "", samples]
    return "\n".join(lines) + "\n"


def sample_table(records: list[Record], every: float) -> str:
    """A time-series table sampled every ``every`` seconds.

    This is what turns a step-response run (breathing on the sensor) into
    something presentable: one row per sampling instant, one column per
    channel, holding the most recent value of each.
    """
    if not records or every <= 0:
        return ""
    channels = sorted({r.channel for r in records})
    header = "| 时刻/s | " + " | ".join(channels) + " |"
    sep = "| --- | " + " | ".join("---" for _ in channels) + " |"
    rows = [header, sep]

    latest: dict[str, float] = {}
    index = 0
    end = records[-1].elapsed
    mark = 0.0
    body: list[str] = []
    while mark <= end:
        while index < len(records) and records[index].elapsed <= mark:
            r = records[index]
            if r.valid:
                latest[r.channel] = r.value
            index += 1
        cells = [_fmt(latest.get(c)) for c in channels]
        # 采集尚未开始时（第一帧还没到）不输出整行空值，那不是"测到了空"
        if any(cell != "—" for cell in cells):
            body.append(f"| {mark:.0f} | " + " | ".join(cells) + " |")
        mark += every
    return "\n".join(rows + body) if body else ""


def parse_cues(raw: list[str] | None) -> list[tuple[float, str]]:
    """Parse ``--cue 60:开始播放白噪声`` arguments into (seconds, message).

    Timed cues exist because a step-response run is only as repeatable as the
    operator's timing: the report needs "the stimulus began at t=60 s" to be
    true, not approximately true. Watching a stopwatch while also handling the
    sensor is how an earlier humidity run ended up with two stimuli and no
    baseline.
    """
    cues: list[tuple[float, str]] = []
    for item in raw or []:
        moment, _, message = item.partition(":")
        try:
            cues.append((float(moment), message.strip() or "（无说明）"))
        except ValueError:
            message = f"无法解析的 --cue 参数：{item!r}，应为 秒数:提示文字"
            raise ValueError(message) from None
    return sorted(cues)


def collect(
    port: str,
    duration: float,
    baudrate: int = DEFAULT_BAUDRATE,
    wire_id: int = DEFAULT_WIRE_ID,
    device_id: str = DEFAULT_DEVICE_ID,
    cues: list[tuple[float, str]] | None = None,
) -> tuple[list[Record], int, int]:
    """Open the serial port and record for ``duration`` seconds."""
    channel = SerialChannel(port=port, baudrate=baudrate)
    channel.connect()
    receiver = HardwareDeviceReceiver(
        device_id=device_id,
        wire_id=wire_id,
        channel=channel,
        data_service=InMemoryDataService(),
    )

    records: list[Record] = []
    started = time.monotonic()
    next_report = 10.0
    pending_cues = list(cues or [])
    warned_no_noise = False
    try:
        while True:
            elapsed = time.monotonic() - started
            if elapsed >= duration:
                break
            while pending_cues and elapsed >= pending_cues[0][0]:
                moment, message = pending_cues.pop(0)
                print()
                print("  " + "*" * 52)
                print(f"  *  t = {moment:.0f}s  →  {message}")
                print("  " + "*" * 52)
                print()
            for point in receiver.poll_until_empty():
                records.append(
                    Record(
                        elapsed=round(time.monotonic() - started, 3),
                        wall_clock=datetime.now().strftime("%H:%M:%S.%f")[:-3],
                        channel=point.channel,
                        value=float(point.value),
                        valid=bool(point.valid),
                    )
                )
            if elapsed >= next_report:
                noise_count = sum(1 for r in records if r.channel == NOISE_CHANNEL)
                print(
                    f"  [{elapsed:6.0f}s / {duration:.0f}s] "
                    f"已接收 {len(records)} 帧（噪声 {noise_count}），"
                    f"错误 {receiver.error_count}"
                )
                # 早期预警：温湿度在流而噪声一帧没有，说明噪声模块没通上电或接线
                # 有问题。不报的话要等整场跑完才发现——2026-08-18 的 15 分钟本底
                # 实验就是这样白跑了一次。
                if not warned_no_noise and elapsed >= _NOISE_WARN_AFTER_SECONDS:
                    if records and noise_count == 0:
                        print()
                        print("  " + "!" * 54)
                        print("  !  警告：已有数据在流，但噪声通道一帧都没收到。")
                        print("  !  多半是噪声模块没通上电，或 TXD/RXD 接线有问题。")
                        print("  !  建议 Ctrl+C 中止，排查后重跑，不要白等。")
                        print("  " + "!" * 54)
                        print()
                    warned_no_noise = True
                next_report += 10.0
            time.sleep(_POLL_SLEEP_SECONDS)
    except KeyboardInterrupt:
        print("\n已手动停止，正在保存已采集的数据……")
    finally:
        channel.disconnect()

    return records, receiver.error_count, receiver.ignored_frame_count


def read_csv(path: Path) -> list[Record]:
    """Load a previously recorded CSV back into records.

    Lets a report be regenerated after the statistics code is corrected,
    without having to repeat a hardware experiment that may not be
    reproducible (a step-response run depends on how the operator breathed
    on the sensor).
    """
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [
            Record(
                elapsed=float(row["elapsed_s"]),
                wall_clock=row["wall_clock"],
                channel=row["channel"],
                value=float(row["value"]),
                valid=bool(int(row["valid"])),
            )
            for row in csv.DictReader(f)
        ]


def write_csv(records: list[Record], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["elapsed_s", "wall_clock", "channel", "value", "valid"])
        for r in records:
            writer.writerow(
                [f"{r.elapsed:.3f}", r.wall_clock, r.channel, r.value, int(r.valid)]
            )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="STM32 串口，如 COM10（--from-csv 时不需要）")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument("--duration", type=float, help="采集时长（秒）")
    parser.add_argument(
        "--from-csv",
        default=None,
        help="不采集，直接用已有的 CSV 重新生成统计报告",
    )
    parser.add_argument("--label", default="实验", help="实验名称，用于文件名与标题")
    parser.add_argument(
        "--sample-every",
        type=float,
        default=15.0,
        help="时序表的采样间隔（秒），设为 0 则不生成",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help="固件的期望采集周期（秒），用于计算理论帧数",
    )
    parser.add_argument(
        "--cue",
        action="append",
        default=None,
        metavar="秒数:提示",
        help="到达指定时刻时在终端醒目提示，可重复，如 --cue 60:开始播放白噪声",
    )
    parser.add_argument("--wire-id", type=int, default=DEFAULT_WIRE_ID)
    parser.add_argument("--device-id", default=DEFAULT_DEVICE_ID)
    parser.add_argument(
        "--out-dir",
        default=str(RECORDINGS_DIR),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    if args.from_csv:
        source = Path(args.from_csv)
        records = read_csv(source)
        errors = ignored = 0  # 原始 CSV 不含计数器，按 0 记并在报告中留空
        duration = args.duration if args.duration else (
            records[-1].elapsed if records else 0.0
        )
        print(f"从 {source} 重新生成报告，共 {len(records)} 帧。")
    else:
        if not args.port or not args.duration:
            print("采集模式需要同时提供 --port 与 --duration。")
            return 1
        duration = args.duration
        print(f"开始采集：{args.label}")
        print(f"串口 {args.port} @ {args.baudrate}，时长 {duration:.0f} 秒")
        print("（按 Ctrl+C 可提前结束并保存已采集的数据）\n")

        try:
            records, errors, ignored = collect(
                port=args.port,
                duration=duration,
                baudrate=args.baudrate,
                wire_id=args.wire_id,
                device_id=args.device_id,
                cues=parse_cues(args.cue),
            )
        except ValueError as exc:
            print(f"\n{exc}")
            return 1
        except SerialConnectionError as exc:
            print(f"\n串口打开失败：{exc}")
            print("最常见原因是该串口已被别的程序占用——请先关闭")
            print("run_all_界面加网关.bat、run_gui_hardware_真实硬件界面.bat")
            print("或串口调试助手，再重新运行本脚本。")
            return 1

    if not records:
        print("\n未收到任何数据帧。请检查：板子是否上电、串口号是否正确、")
        print("固件是否在运行（红绿灯是否闪烁）。")
        return 1

    summary = summarize(
        records,
        duration=duration,
        error_count=errors,
        ignored_count=ignored,
        expected_interval=args.interval,
    )
    samples = sample_table(records, args.sample_every)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = out_dir / f"{args.label}_{stamp}.csv"
    md_path = out_dir / f"{args.label}_{stamp}.md"

    if not args.from_csv:
        write_csv(records, csv_path)
    md_path.write_text(to_markdown(summary, args.label, samples), encoding="utf-8")

    print(f"\n完成，共 {len(records)} 帧。")
    if not args.from_csv:
        print(f"  原始数据：{csv_path}")
    print(f"  统计表格：{md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
