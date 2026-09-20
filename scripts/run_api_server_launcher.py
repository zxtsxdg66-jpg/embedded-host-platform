"""Interactive launcher for the Android gateway (REST + WebSocket).

Peer of scripts/run_gui_hardware.py, for the gateway instead of the GUI.
It exists to answer the two questions that otherwise require looking
things up by hand every time:

1. **Which mode?** Simulator (no board needed) or Hardware (real STM32).
   Hardware mode additionally needs a COM port, chosen with the same
   picker scripts/run_gui_hardware.py uses -- imported, not duplicated.

2. **What address do I type into the phone?** This is the part that
   actually goes wrong in practice, so the launcher prints it in a banner
   rather than leaving it to ``ipconfig``. See scripts/lan_address.py for
   why picking that address correctly is not trivial on this machine (a
   VPN/proxy adapter would otherwise be reported).

Delegates to scripts/run_api_server.py for all composition and serving --
this module only chooses arguments and prints guidance.

Usage
-----
    python scripts/run_api_server_launcher.py
    python scripts/run_api_server_launcher.py --mode simulator
    python scripts/run_api_server_launcher.py --port 9000

or double-click ``run_api_server_手机网关.bat`` in the project root.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import run_api_server  # noqa: E402  (same scripts/ directory)
from lan_address import find_candidates  # noqa: E402
from run_gui_hardware import choose_port  # noqa: E402

DEFAULT_HTTP_PORT = 8000


def _prompt_mode() -> str | None:
    """Ask whether to run against simulated data or a real board."""
    print("请选择运行模式：")
    print()
    print("  [1] 模拟模式  —— 不需要任何硬件，数据由 PC 软件模拟（默认）")
    print("  [2] 硬件模式  —— 从真实 STM32 串口读取数据")
    print()
    while True:
        try:
            answer = input("请输入编号（直接回车 = 模拟模式）: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if not answer or answer == "1":
            return "simulator"
        if answer == "2":
            return "hardware"
        print(f"无效输入：{answer!r}，请输入 1 或 2。")


def _print_phone_banner(http_port: int, mode: str) -> None:
    """Print the address to type into the phone, prominently."""
    candidates = find_candidates()

    print()
    print("=" * 56)
    if not candidates:
        print("  没有检测到可用的局域网地址。")
        print()
        print("  请确认这台电脑已连接 Wi-Fi 或网线，然后重新启动本程序。")
        print("  也可以手动执行 ipconfig 查看 IPv4 地址。")
    else:
        best = candidates[0]
        print("  在手机 App 里填写：")
        print()
        print(f"      IP   :  {best.ip}")
        print(f"      端口 :  {http_port}")
        print()
        print(f"  （来自网卡：{best.adapter or '未知'}）")
        if len(candidates) > 1:
            print()
            print("  若连不上，可以改试这些地址：")
            for candidate in candidates[1:]:
                label = candidate.adapter or "未知网卡"
                print(f"      {candidate.ip:<16} {label}")
    print("=" * 56)
    print()
    print("先用手机浏览器打开下面的地址验证连通性，能看到一段 JSON 就说明通了：")
    if candidates:
        print(f"    http://{candidates[0].ip}:{http_port}/health")
    print()
    if mode == "simulator":
        print("注意：当前是模拟模式，数据由 PC 软件生成，不是真实 STM32 采集值。")
        print()
    print("连不上时依次检查：手机与电脑是否同一个 Wi-Fi、手机是否开着代理/VPN、")
    print("Windows 防火墙是否放行 Python、路由器是否开启了 AP 隔离。")
    print()
    print("按 Ctrl+C 停止服务。")
    print()


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

    # Hardware mode needs a serial port; reuse the GUI launcher's picker so
    # the two launchers behave identically (including its handling of
    # Bluetooth virtual ports).
    if mode == "hardware" and "--port-serial" not in args:
        print()
        port = choose_port()
        if port is None:
            print()
            print("已取消启动。")
            return 1
        args += ["--port-serial", port]
        print(f"使用串口：{port}")

    http_port = DEFAULT_HTTP_PORT
    if "--port" in args:
        try:
            http_port = int(args[args.index("--port") + 1])
        except (IndexError, ValueError):
            http_port = DEFAULT_HTTP_PORT

    _print_phone_banner(http_port, mode)

    return run_api_server.main(args)


if __name__ == "__main__":
    sys.exit(main())
