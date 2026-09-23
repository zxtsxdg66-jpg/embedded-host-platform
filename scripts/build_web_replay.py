"""Build the web console's replay data from real recordings.

2026-09-23, for the web console's replay mode
(docs/decisions/08-web.md). Output:
``web/replay/replay-data.js``, which the console loads when no gateway is
reachable -- including on GitHub Pages, where there never is one.

**Every message in the replay is produced by the running system's own code,
offline.** The recordings (``scripts/recordings.py``) hold readings, not
bytes, so each reading is encoded into a protocol frame and pushed through
a pipe into the real HardwareDeviceReceiver with a real LinkMonitor; the
real SensorDataProcessor and VentilationController react to what it
publishes; the gateway's own serializers (gateway.events) turn every
callback into the message a live WebSocket client would have received.
Only the timestamps are rewritten, to the moments the readings were taken.
The replay is therefore the live pipeline with the source swapped -- not a
second implementation of the console's logic in JavaScript.

Two sessions are built:

- ``hour``: the one-hour stability run on the real board (3489 frames).
  Its frames are **re-encoded** from the recorded readings -- the capture
  kept values, not raw bytes -- which the console states plainly.
- ``faults``: a short session of the in-process virtual STM32 with fault
  injection (fixed seed), run through the same receiver, so the protocol
  inspector has resyncs and CRC failures to show that the real code caught.

Plus ``assistant``: the constrained Q&A recordings from
the recorded model Q&A session (``约束展示实录_*.json`` under
``recordings.ASSISTANT_RECORDINGS_DIR``), trace included.

This script imports ``src/`` and therefore lives in ``scripts/``: ``web/``
never imports Python (CONTRIBUTING.md).

Usage::

    python scripts/build_web_replay.py
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
for _path in (_ROOT / "src", _ROOT / "scripts", _ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from recordings import ASSISTANT_RECORDINGS_DIR, RECORDINGS_DIR  # noqa: E402
from virtual_stm32 import FaultPlan, VirtualStm32, build_frame  # noqa: E402

from application.hardware_runtime import HardwareDeviceReceiver  # noqa: E402
from application.runtime import ApplicationRuntime  # noqa: E402
from communication.pipe import make_pipe_pair  # noqa: E402
from device.capability import ChannelDescriptor, DeviceCapability  # noqa: E402
from device.remote import RemoteDevice  # noqa: E402
from device.sensors.channels import (  # noqa: E402
    HUMIDITY_CHANNEL,
    NOISE_CHANNEL,
    TEMPERATURE_CHANNEL,
)
from device.state import ConnectionState, DeviceStatus  # noqa: E402
from gateway.events import (  # noqa: E402
    alarm_status_message,
    data_point_message,
    fan_decision_message,
    link_event_message,
    statistics_message,
    ventilation_payload,
)

DATA_DIR = RECORDINGS_DIR
BASELINE_DIR = ASSISTANT_RECORDINGS_DIR
OUT = _ROOT / "web" / "replay" / "replay-data.js"

HOUR_RUN = "长时间稳定性_20260819_001038.csv"
HOUR_START = datetime(2026, 8, 19, 0, 10, 38)
"""From the recording's file name; the CSV's own clock column is not dated."""
DEVICE_ID = "mcu-1"
CHANNELS = (TEMPERATURE_CHANNEL, HUMIDITY_CHANNEL, NOISE_CHANNEL)

FAULT_CYCLES = 60
FAULT_SEED = 20260923
FAULT_PLAN = FaultPlan(split=0.25, merge=0.3, garbage=0.12, bitflip=0.06)


def _pipeline() -> tuple[
    ApplicationRuntime, HardwareDeviceReceiver, Any, list[dict[str, Any]]
]:
    """Hardware-mode composition over a pipe, with every callback recorded.

    The subscriptions are the ones gateway.server.create_app makes, fed to
    the same serializers -- so a message here is what a WebSocket client
    of a live gateway would have received for the same reading.
    """
    runtime = ApplicationRuntime()
    host, device_end = make_pipe_pair()
    host.connect()
    device_end.connect()
    device = RemoteDevice(
        device_id=DEVICE_ID,
        capability=DeviceCapability(
            commands=(),
            channels=tuple(ChannelDescriptor(channel_id=c) for c in CHANNELS),
        ),
        status=DeviceStatus(connection_state=ConnectionState.CONNECTED),
    )
    registration = runtime.devices.register(device, host)
    runtime.watch_alarms_for(device)
    receiver = HardwareDeviceReceiver(
        DEVICE_ID, registration.wire_id, host, runtime.data_service,
        monitor=runtime.link_monitor,
    )

    sink: list[dict[str, Any]] = []
    for channel in CHANNELS:
        runtime.subscribe(
            DEVICE_ID, channel, lambda p: sink.append(data_point_message(p))
        )
    runtime.subscribe_statistics(
        lambda d, c, s: sink.append(statistics_message(d, c, s))
    )
    runtime.subscribe_alarm_status(lambda s: sink.append(alarm_status_message(s)))
    runtime.subscribe_fan_decision(lambda d: sink.append(fan_decision_message(d)))
    runtime.subscribe_link_events(lambda e: sink.append(link_event_message(e)))
    return runtime, receiver, device_end, sink


def _stamp(messages: list[dict[str, Any]], moment: datetime) -> list[dict[str, Any]]:
    """Rewrite wall-clock stamps to the moment the reading was recorded."""
    iso = moment.isoformat()
    for message in messages:
        if message.get("timestamp") is not None:
            message["timestamp"] = iso
    return messages


def build_hour() -> dict[str, Any]:
    with (DATA_DIR / HOUR_RUN).open(encoding="utf-8-sig", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r["valid"] == "1"]
    runtime, receiver, device_end, sink = _pipeline()
    timeline: list[list[Any]] = []
    for row in rows:
        elapsed = float(row["elapsed_s"])
        device_end.send(build_frame(1, row["channel"], float(row["value"])))
        receiver.poll_until_empty()
        for message in _stamp(sink[:], HOUR_START + timedelta(seconds=elapsed)):
            timeline.append([round(elapsed, 3), message])
        sink.clear()
    stats = runtime.get_link_statistics()
    assert stats.frames == len(rows) == 3489, (stats.frames, len(rows))
    assert stats.checksum_errors == stats.resyncs == 0
    return {
        "title": "一小时稳定性实验（2026-08-19）",
        "source": f"{DATA_DIR.relative_to(_ROOT).as_posix()}/{HOUR_RUN}",
        "note": "录制时只保存了读数；帧字节是按协议重新编码后送入真实接收器的，"
                "其余消息均由系统自身的统计、报警与通风判定代码产生。",
        "start": HOUR_START.isoformat(),
        "duration": timeline[-1][0],
        "ventilation": ventilation_payload(runtime.get_ventilation_settings(), None),
        "messages": timeline,
    }


def build_faults() -> dict[str, Any]:
    runtime, receiver, device_end, sink = _pipeline()
    virtual = VirtualStm32(device_end, device_id=1, faults=FAULT_PLAN,
                           seed=FAULT_SEED, verbose=False)
    start = datetime(2026, 9, 23, 12, 0, 0)
    timeline: list[list[Any]] = []
    for cycle in range(FAULT_CYCLES):
        virtual.cycle()
        receiver.poll_until_empty()
        t = cycle * 3.0
        for message in _stamp(sink[:], start + timedelta(seconds=t)):
            if message["type"] == "link_event":
                timeline.append([t, message])
        sink.clear()
    stats = runtime.get_link_statistics()
    assert stats.resyncs == virtual.injected["garbage"]
    assert stats.checksum_errors == virtual.injected["bitflip"]
    return {
        "title": "故障注入会话（虚拟 STM32，固定随机种子）",
        "source": (
            "scripts/virtual_stm32.py 的 VirtualStm32，"
            "经真实 HardwareDeviceReceiver"
        ),
        "note": "虚拟设备故意拆帧、并帧、插入杂散字节、翻转 CRC 位；"
                "下面的每一条事件都是真实接收器代码判出来的。",
        "injected": virtual.injected,
        "caught": {"resyncs": stats.resyncs, "checksum_errors": stats.checksum_errors,
                   "frames": stats.frames},
        "cycles": FAULT_CYCLES,
        "duration": (FAULT_CYCLES - 1) * 3.0,
        "messages": timeline,
    }


_VERDICT_CODES = [
    ("长度上限", "too_long"),
    ("建议措辞", "advice"),
    ("凭空判断", "unsupported_judgement"),
    ("接地校验", "ungrounded_number"), ("越限断言", "unsupported_alarm"),
    ("改写为空", "too_short"), ("无改写", "no_reply"), ("采纳", "accepted"),
]


def _verdict_code(label: str) -> str:
    return next(code for key, code in _VERDICT_CODES if key in label)


def build_assistant() -> dict[str, Any]:
    path = sorted(BASELINE_DIR.glob("约束展示实录_*.json"))[-1]
    record = json.loads(path.read_text(encoding="utf-8"))
    items = []
    groups = (("现行配置_温度0.3", "现行配置"), ("对照_温度0.8", "采样温度 0.8"))
    for group, label in groups:
        seen: set[str] = set()
        for row in record[group]:
            if group == "对照_温度0.8":
                blocked = any(
                    str(t["verdict"]).startswith("拦下") for t in row["rephrase"]
                )
                if not blocked or row["question"] in seen:
                    continue
                seen.add(row["question"])
            items.append({
                "question": row["question"],
                "config": label,
                "first": {"text": row["first_text"], "source": row["first_source"]},
                "text": row["final_text"],
                "source": row["final_source"],
                "intent": None if row["intent"] is None
                else {"kind": row["intent"].upper(), "channel": row["channel"]},
                "facts": row["rephrase"][0]["facts"] if row["rephrase"] else None,
                "applied": row["applied"],
                "trace": [
                    {"template": t["template"], "reply": t["model"],
                     "verdict": _verdict_code(str(t["verdict"])), "retry": i > 0}
                    for i, t in enumerate(row["rephrase"])
                ],
            })
    return {
        "source": path.relative_to(_ROOT).as_posix(),
        "note": "2026-09-23 走正式装配录制，本地模型 qwen3.5:4b，数据源为仿真模式。",
        "items": items,
    }


def main() -> int:
    data = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "hour": build_hour(),
        "faults": build_faults(),
        "assistant": build_assistant(),
    }
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "// 由 scripts/build_web_replay.py 生成，请勿手改。\n"
        f"window.EHP_REPLAY = {blob};\n",
        encoding="utf-8",
    )
    print(f"已生成 {OUT}（{OUT.stat().st_size / 1024:.0f} KB）")
    print(f"  一小时：{len(data['hour']['messages'])} 条消息")
    faults = data["faults"]
    print(f"  故障注入：注入 {faults['injected']}，判出 {faults['caught']}")
    print(f"  问答实录：{len(data['assistant']['items'])} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
