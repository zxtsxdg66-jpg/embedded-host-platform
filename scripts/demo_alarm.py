"""Demonstrate the alarm path live: lower a threshold for a while, then restore it.

Why this exists
---------------
The room is rarely above 35 °C or 80 dB(A), so on the day of a demonstration
the board's screen would sit on "正常" and the alarm path -- threshold
judgement, the alarm bitmap sent to the board, the LCD, the voice alert, the
phone and the web console -- would never be seen working. This script lowers
the threshold of one or more channels below the current reading, starts the
normal ``run_all.py`` launcher, and after a set time puts the original
thresholds back, so the screen goes "报警" and then back to "正常" without
touching the environment.

**No source file changes.** The thresholds live in two in-memory tables --
the alarm judgement (``service.sensor_data_processor``) and the assistant's
facts (``service.assistant.retrieval``) -- and both are read on every
reading, so changing the tables takes effect immediately. Both are changed
together, so the screen and a spoken answer name the same threshold. They
are restored when the timer fires and again when the launcher exits.

What to expect on the board: the channel's line turns "报警" within one or
two acquisition cycles (3 s each); the voice alert plays once (the host
waits for two confirming readings and then has a 30 s cooldown); after
``--for`` seconds the line returns to "正常".

Usage::

    # temperature alarm for 60 s, then back to normal (pick a value just
    # below the room's current reading)
    python scripts/demo_alarm.py --temperature-max 20 \
        --mode hardware --port-serial COM9

    # keep it lowered until the window is closed
    python scripts/demo_alarm.py --noise-max 35 --for 0 \
        --mode hardware --port-serial COM9

Every option not listed below is passed to ``run_all.py`` unchanged.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import threading
from collections.abc import Callable
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
_SCRIPTS_DIR = Path(__file__).resolve().parent
for _path in (_SRC_DIR, _SCRIPTS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from core.models import ChannelId  # noqa: E402
from device.sensors.channels import (  # noqa: E402
    HUMIDITY_CHANNEL,
    NOISE_CHANNEL,
    TEMPERATURE_CHANNEL,
)
from service import sensor_data_processor  # noqa: E402
from service.assistant import retrieval  # noqa: E402

DEFAULT_SECONDS = 60.0


def lower_thresholds(maxima: dict[ChannelId, float]) -> Callable[[], None]:
    """Set the upper alarm bound of each channel; return a function that undoes it.

    Only ``maximum`` changes; a channel's lower bound and hysteresis stay as
    they are. The returned function may be called more than once.
    """
    tables = (sensor_data_processor._ALARM_RULES, retrieval._ALARM_RULES)
    originals = [dict(table) for table in tables]
    for table in tables:
        for channel, maximum in maxima.items():
            table[channel] = dataclasses.replace(table[channel], maximum=maximum)

    def restore() -> None:
        for table, original in zip(tables, originals, strict=True):
            table.update(original)

    return restore


def parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description="Lower alarm thresholds for a while, then start run_all.py.",
        epilog="Every other option is passed to run_all.py.",
    )
    parser.add_argument("--temperature-max", type=float, default=None)
    parser.add_argument("--humidity-max", type=float, default=None)
    parser.add_argument("--noise-max", type=float, default=None)
    parser.add_argument(
        "--for",
        dest="seconds",
        type=float,
        default=DEFAULT_SECONDS,
        help=f"seconds before the thresholds are restored; 0 = until exit "
        f"(default: {DEFAULT_SECONDS:g})",
    )
    demo, launcher = parser.parse_known_args(argv)
    if (
        demo.temperature_max is None
        and demo.humidity_max is None
        and demo.noise_max is None
    ):
        parser.error(
            "give at least one of --temperature-max / --humidity-max / --noise-max"
        )
    return demo, launcher


def main(argv: list[str] | None = None) -> int:
    demo, launcher = parse_args(sys.argv[1:] if argv is None else argv)
    maxima: dict[ChannelId, float] = {}
    if demo.temperature_max is not None:
        maxima[TEMPERATURE_CHANNEL] = demo.temperature_max
    if demo.humidity_max is not None:
        maxima[HUMIDITY_CHANNEL] = demo.humidity_max
    if demo.noise_max is not None:
        maxima[NOISE_CHANNEL] = demo.noise_max

    restore = lower_thresholds(maxima)
    lowered = "、".join(
        f"{channel} 上限 {value:g}" for channel, value in maxima.items()
    )
    print(f"[demo] 报警阈值已临时调为：{lowered}")
    if demo.seconds > 0:

        def _restore_and_say() -> None:
            restore()
            print(f"[demo] {demo.seconds:g} 秒到，阈值已恢复原值，屏幕应回到「正常」")

        timer = threading.Timer(demo.seconds, _restore_and_say)
        timer.daemon = True
        timer.start()
        print(f"[demo] {demo.seconds:g} 秒后自动恢复")
    else:
        print("[demo] 保持到窗口关闭")

    import run_all  # imported late: it pulls in PyQt6 and the whole launcher

    try:
        return run_all.main(launcher)
    finally:
        restore()


if __name__ == "__main__":
    sys.exit(main())
