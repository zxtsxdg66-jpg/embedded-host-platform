"""Interactive launcher for "PC 界面 + 手机网关一起跑" (scripts/run_all.py).

Peer of scripts/run_api_server_launcher.py; same two questions (which mode,
which COM port) and the same phone-address banner, all reused rather than
duplicated. The only difference is what it finally starts: run_all.py, which
serves the desktop UI and the gateway from a *single* runtime so they do not
fight over the one physical serial port.

Usage
-----
    python scripts/run_all_launcher.py
    python scripts/run_all_launcher.py --mode hardware --port-serial COM10

or double-click ``run_all_界面加网关.bat`` in the project root.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import run_all  # noqa: E402  (same scripts/ directory)

# Reused from the gateway launcher on purpose: the mode prompt, the port
# picker and the phone banner should behave identically no matter which
# launcher the user double-clicks. Duplicating them would let the two drift.
from run_api_server_launcher import (  # noqa: E402
    _print_phone_banner,
    _prompt_mode,
)
from run_gui_hardware import choose_port  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if "--mode" not in args:
        mode = _prompt_mode()
        if mode is None:
            print()
            print("已取消启动。")
            return 1
        args += ["--mode", mode]
    else:
        mode = args[args.index("--mode") + 1]

    if mode == "hardware" and "--port-serial" not in args:
        print()
        port = choose_port()
        if port is None:
            print()
            print("已取消启动。")
            return 1
        args += ["--port-serial", port]
        print(f"使用串口：{port}")

    http_port = run_all.run_api_server.DEFAULT_HTTP_PORT
    if "--port" in args:
        try:
            http_port = int(args[args.index("--port") + 1])
        except (IndexError, ValueError):
            http_port = run_all.run_api_server.DEFAULT_HTTP_PORT

    _print_phone_banner(http_port, mode)
    print("PC 界面窗口会同时打开；关闭窗口即同时停止网关。")
    print()

    return run_all.main(args)


if __name__ == "__main__":
    sys.exit(main())
