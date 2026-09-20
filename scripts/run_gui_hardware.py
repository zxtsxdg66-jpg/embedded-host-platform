"""Interactive launcher for Hardware mode: pick a serial port, then start the GUI.

Why this exists
---------------
Hardware mode needs ``--port COMx``, but the COM number is not stable: it
changes with which USB socket the board is plugged into, and can change
again after a replug. So it cannot be baked into a double-clickable .bat
the way Simulator mode can. This script asks instead of hardcoding.

Why it does not just auto-pick the only port: a typical Windows machine
already has serial ports that are *not* the board. On the development
machine this was written on, COM3 and COM4 both existed before any board
was connected -- both Bluetooth virtual ports (``BTHENUM`` hardware ids).
Silently selecting "the first port" would have picked a Bluetooth port and
produced a confusing timeout instead of an obvious error. This script
therefore shows every port with its description, and marks the ones whose
hardware id looks like a USB-to-serial bridge (the探索者 V3 board reaches
the PC through an on-board CH340C, so it will show up as one of those).

Delegates to scripts/run_gui.py rather than duplicating any composition
logic -- it only decides the ``--port`` value and forwards everything else.

Usage
-----
    python scripts/run_gui_hardware.py
    python scripts/run_gui_hardware.py --baudrate 115200
    python scripts/run_gui_hardware.py --port COM7      # skip the prompt

or double-click ``run_gui_hardware_真实硬件界面.bat`` in the project root.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import run_gui  # noqa: E402  (same scripts/ directory)
from serial.tools import list_ports  # noqa: E402

from communication.exceptions import (  # noqa: E402
    SerialConnectionError,
    SerialPortNotFoundError,
)

# Substrings that suggest a USB-to-serial bridge rather than e.g. a
# Bluetooth virtual port. Matched case-insensitively against both the
# description and the hardware id. CH340 is what the 探索者 V3 board uses;
# the others are common alternatives on other boards/adapters.
_USB_SERIAL_HINTS = (
    "CH340",
    "CH910",
    "CP210",
    "FT232",
    "FTDI",
    "USB-SERIAL",
    "USB SERIAL",
    "USB\\VID",
    "SILICON LABS",
    "PROLIFIC",
)

# Substrings that suggest a port which is definitely *not* a board.
_UNLIKELY_HINTS = ("BTHENUM", "BLUETOOTH")


def _looks_like_usb_serial(description: str, hwid: str) -> bool:
    haystack = f"{description} {hwid}".upper()
    if any(hint in haystack for hint in _UNLIKELY_HINTS):
        return False
    return any(hint in haystack for hint in _USB_SERIAL_HINTS)


def _safe(text: str) -> str:
    """Render text that the current console encoding can actually print.

    Port descriptions come from Windows and are localized (Chinese on this
    machine). A double-clicked .bat may run under a console codepage that
    cannot encode them, and an UnicodeEncodeError while merely *listing*
    ports would be an absurd way to fail. Unprintable characters are
    replaced instead.
    """
    encoding = sys.stdout.encoding or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def choose_port() -> str | None:
    """Prompt for a serial port. Returns None if there is nothing to pick."""
    ports = sorted(list_ports.comports(), key=lambda p: p.device)

    if not ports:
        print("没有检测到任何串口。")
        print()
        print("请检查：")
        print("  1. 开发板是否已通过 USB 线连接（用板上的 USB_UART 口）")
        print("  2. 数据线是否是充电线（有些线只有电源芯，不传数据）")
        print("  3. CH340 驱动是否已安装（设备管理器里看有没有带感叹号的设备）")
        return None

    likely: list[int] = []
    print("检测到以下串口：")
    print()
    for index, port in enumerate(ports, start=1):
        description = _safe(port.description or "")
        if _looks_like_usb_serial(port.description or "", port.hwid or ""):
            likely.append(index)
            marker = "  <-- 可能是开发板"
        else:
            marker = ""
        print(f"  [{index}] {port.device:<8} {description}{marker}")
    print()

    default_index = likely[0] if len(likely) == 1 else None
    if default_index is not None:
        prompt = f"请选择串口编号（直接回车 = {ports[default_index - 1].device}）: "
    else:
        if not likely:
            print("提示：没有识别出明显的 USB 转串口设备。上面列出的可能都是蓝牙")
            print("      等虚拟串口。如果开发板已插好，请确认 CH340 驱动已安装。")
            print()
        prompt = "请选择串口编号: "

    while True:
        try:
            answer = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None

        if not answer and default_index is not None:
            return ports[default_index - 1].device

        if answer.isdigit() and 1 <= int(answer) <= len(ports):
            return ports[int(answer) - 1].device

        # Also accept a port name typed directly, e.g. "COM7".
        for port in ports:
            if answer.upper() == port.device.upper():
                return port.device

        print(f"无效输入：{_safe(answer)!r}，请输入 1~{len(ports)} 之间的编号。")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    # If the caller already supplied --port, respect it and skip the prompt.
    if "--port" not in args:
        port = choose_port()
        if port is None:
            print()
            print("已取消启动。")
            return 1
        args += ["--port", port]
        print(f"使用串口：{port}")
        print()

    if "--mode" not in args:
        args += ["--mode", "hardware"]

    # A raw traceback is a poor way to tell someone who double-clicked a .bat
    # that the board came unplugged. These two are the failures that actually
    # happen in practice: the port vanished between listing and opening, or
    # something else already holds it open.
    try:
        return run_gui.main(args)
    except SerialPortNotFoundError as exc:
        print()
        print(f"打不开串口：{exc}")
        print()
        print("常见原因：")
        print("  1. 开发板在选择串口之后被拔掉了")
        print("  2. 用 --port 指定了一个当前不存在的串口号")
        print("  3. 板子重新插拔后 COM 号变了（重新运行本程序会重新扫描）")
        return 1
    except SerialConnectionError as exc:
        print()
        print(f"串口存在但打不开：{exc}")
        print()
        print("常见原因：")
        print("  1. 串口已被其它程序占用（串口调试助手、另一个本程序窗口、")
        print("     STM32CubeProgrammer 等），先把它们关掉")
        print("  2. 权限不足")
        return 1


if __name__ == "__main__":
    sys.exit(main())
