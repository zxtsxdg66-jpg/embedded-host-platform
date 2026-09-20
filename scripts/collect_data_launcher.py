"""Interactive launcher for scripts/collect_thesis_data.py.

Peer of the other launchers in this directory: it exists so the data runs can
be started by double-clicking, without remembering COM ports or argument
names. The experiment presets match the plan in
docs/07_Thesis/范文分析与写作计划.md so that the runs are reproducible and
consistently labelled.

Usage::

    python scripts/collect_data_launcher.py

or double-click ``collect_data_实验数据采集.bat`` in the project root.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import collect_thesis_data  # noqa: E402  (same scripts/ directory)
from run_gui_hardware import choose_port  # noqa: E402

# (菜单文字, 时长秒, 时序表采样间隔秒, 标签, 操作提示)
#
# 噪声相关的三个预设（4/5/6）在噪声传感器到货后新增。采样间隔比温湿度实验短，
# 因为声压级的变化比温湿度快得多，15 s 一采会把过程糊掉。
_PRESETS: list[tuple[str, float, float, str, str]] = [
    (
        "试运行（60 秒）——先确认链路与输出正常，建议第一次先跑这个",
        60, 10, "试运行", "",
    ),
    (
        "温湿度阶跃响应（180 秒）——中途对传感器哈气",
        180, 10, "温湿度阶跃响应", "",
    ),
    (
        "长时间稳定性（1 小时）——挂着即可，不必盯屏",
        3600, 300, "长时间稳定性", "",
    ),
    (
        "噪声试运行（60 秒）——确认噪声通道与 Modbus 应答正常",
        60, 10, "噪声试运行",
        "保持环境安静即可，本次只看噪声通道有没有稳定出数、Modbus 成功率是否 100%。",
    ),
    (
        "噪声阶跃响应（180 秒）——60s 安静 / 60s 放白噪声 / 60s 恢复",
        180, 5, "噪声阶跃响应",
        "分三段，全程不要说话、不要移动手机：\n"
        "    0~60 s    保持安静，什么都不做（记录基线）\n"
        "   60~120 s   手机播放白噪声，距传感器约 30 cm，音量固定不变\n"
        "  120~180 s   停止播放，恢复安静（记录回落过程）\n"
        "  脚本每 10 秒会打印一次进度，按提示切换即可。\n"
        "  注意：采集周期 3 s、模块响应 400 ms，所以声源必须**持续**，\n"
        "  拍手这类瞬时声源大概率采不到。",
    ),
    (
        "噪声越限报警（180 秒）——85 dB 播放/暂停交替，触发与解除各两次",
        180, 5, "噪声越限报警",
        "**先把音量调好（约 85 dB），全程只按播放/暂停，不要再动音量。**\n"
        "    0~30 s    暂停（安静）      预期：无报警\n"
        "   30~60 s    播放 ~85 dB       预期：报警触发并保持\n"
        "   60~90 s    暂停              预期：报警自动解除\n"
        "   90~120 s   播放 ~85 dB       预期：再次触发\n"
        "  120~150 s   暂停              预期：再次解除\n"
        "  150~180 s   暂停（收尾）\n"
        "  脚本会在每个切换点喊你，按提示按播放/暂停即可。\n"
        "  为什么低电平用“暂停”而不是“调到 70~80”：阈值判定无回差（逐点比较\n"
        "  value > 80），低电平若贴近 80 会自己抖过阈值，就分不清报警是被你\n"
        "  调下来的还是自己翻转的；暂停后是本底约 38 dB，绝对低于阈值，无歧义。\n"
        "  跑完记得截图：活动日志红字、指标卡红框，以及暂停后颜色自动消失。",
    ),
    (
        "报警阈值抖动（60 秒，可选）——实证无回差导致的状态翻转",
        60, 5, "报警阈值抖动",
        "让白噪声在 78~83 dB 之间缓慢飘动（手动小幅调音量即可），持续 60 秒。\n"
        "  目的不是演示报警正常，而是**实证一条设计局限**：当前按单点阈值判定、\n"
        "  无迟滞也无持续时间确认，读数贴近阈值时报警状态会反复翻转。\n"
        "  这个结果用于论文的局限/展望，不是失败的实验。",
    ),
    (
        "环境本底噪声（15 分钟）——为报警阈值取值提供实测依据",
        900, 60, "环境本底噪声",
        "全程保持你日常的环境状态即可（正常呼吸、不刻意制造声音也不刻意静音）。\n"
        "  结束后可另外单独记录几个可复现的场景值（正常交谈 / 播放音乐 / 拍手），\n"
        "  写进 docs/07_Thesis/实验数据/人工实验记录.md。",
    ),
    ("自定义时长", 0, 0, "", ""),
]

# 定时提示：到点由脚本在终端醒目喊出来，不用自己盯秒表。只有分段协议的实验需要。
_CUES: dict[str, list[str]] = {
    "噪声阶跃响应": [
        "--cue", "60:现在开始播放白噪声（距传感器约 30 cm，音量保持不变）",
        "--cue", "120:现在停止播放，恢复安静",
        "--cue", "170:还有 10 秒结束，保持安静",
    ],
    # 每段 30 s ≈ 10 个采样点（周期 3.09 s），足够看清报警状态稳定保持而非瞬时抖动
    "噪声越限报警": [
        "--cue", "30:按【播放】——预期报警触发",
        "--cue", "60:按【暂停】——预期报警自动解除",
        "--cue", "90:按【播放】——预期再次触发",
        "--cue", "120:按【暂停】——预期再次解除",
        "--cue", "170:还有 10 秒结束，保持安静",
    ],
    "报警阈值抖动": [
        "--cue", "0:开始——让音量在 78~83 dB 之间缓慢来回飘动",
        "--cue", "50:还有 10 秒结束",
    ],
}


def _prompt_preset() -> tuple[float, float, str, str] | None:
    print()
    print("请选择实验类型：")
    print()
    for index, (text, _, _, _, _) in enumerate(_PRESETS, start=1):
        print(f"  [{index}] {text}")
    print()

    raw = input("请输入编号（直接回车 = 试运行）: ").strip()
    if not raw:
        raw = "1"
    if not raw.isdigit() or not 1 <= int(raw) <= len(_PRESETS):
        print("输入无效。")
        return None

    _, duration, sample, label, hint = _PRESETS[int(raw) - 1]
    if duration > 0:
        return duration, sample, label, hint

    try:
        duration = float(input("采集时长（秒）: ").strip())
        sample = float(input("时序表采样间隔（秒，直接回车 = 15）: ").strip() or "15")
    except ValueError:
        print("输入无效。")
        return None
    label = input("实验名称（用于文件名）: ").strip() or "自定义实验"
    return duration, sample, label, ""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    print("=" * 56)
    print("  论文实验数据采集")
    print("=" * 56)
    print()
    print("注意：串口同一时间只能被一个程序打开。开始前请先关闭")
    print("      run_all_界面加网关.bat / run_gui_hardware_真实硬件界面.bat /")
    print("      run_api_server_手机网关.bat")
    print("      以及串口调试助手，否则会提示“拒绝访问”。")

    chosen = _prompt_preset()
    if chosen is None:
        return 1
    duration, sample, label, hint = chosen

    print()
    port = choose_port()
    if port is None:
        print()
        print("已取消。")
        return 1

    minutes = duration / 60.0
    print()
    print(f"实验：{label}")
    print(f"串口：{port}")
    print(f"时长：{duration:.0f} 秒（约 {minutes:.1f} 分钟）")
    if hint:
        print()
        print("操作步骤：")
        print(f"  {hint}")
    print()
    input("按回车开始采集……")
    print()

    return collect_thesis_data.main(
        args
        + [
            "--port",
            port,
            "--duration",
            str(duration),
            "--label",
            label,
            "--sample-every",
            str(sample),
        ]
        + _CUES.get(label, [])
    )


if __name__ == "__main__":
    sys.exit(main())
