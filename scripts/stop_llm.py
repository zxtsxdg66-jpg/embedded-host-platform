"""把本地语言模型从内存里卸下来，必要时连服务一起停掉。

**为什么需要这个脚本。** `OLLAMA_KEEP_ALIVE = -1` 是刻意设的——演示时不希望
模型空闲五分钟就被卸载、下一个问题又卡住 9 秒（见 `scripts/start_llm.py`）。
代价是它**永远不会自己退出**：`/api/ps` 里 `expires_at` 显示的是 2318 年，
3.1 GB 内存就这么一直占着。所以"关掉"这件事必须显式做，没有自动路径。

两级停法，对应两种真实需求：

- **卸载模型**（默认）：内存放出来，服务留着。下次提问会重新载入（约 9 秒），
  但不用等托盘程序重新拉起服务。跑完一轮训练、要腾内存干别的时用这一级。
- **停掉服务**（``--server``）：连 `ollama.exe` 与托盘程序 `ollama app.exe`
  一起结束。托盘程序必须一并结束——只杀 `ollama.exe` 的话它会把服务再拉起来，
  看上去像"杀不掉"。关机前或彻底不用时用这一级。

用法::

    python scripts/stop_llm.py            # 卸载模型，服务保留
    python scripts/stop_llm.py --server   # 卸载并停掉服务与托盘程序
    python scripts/stop_llm.py --status   # 只看驻留情况，不动任何东西

退出码：0 已达到目标状态（含"本来就没在跑"）；1 没能停下来（原因已打印）。

卸载不会删除任何模型文件。磁盘上那 3.4 GB 权重原地不动，
这个脚本只管内存与进程。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

# 与 start_llm.py 共用主机、端口、模型名与两个取数小函数。
# 直接 import 同目录的脚本：`python scripts/stop_llm.py` 会把 scripts/ 放进
# sys.path[0]，因此这行在任何工作目录下都成立。之所以不复制一份常量过来，
# 是因为端口或模型名将来只该有一处需要改。
import start_llm  # noqa: E402  （放在标准库之后，属于本地脚本）

# 托盘程序在前：它是服务的父级看门狗，先结束它才不会被重新拉起。
PROCESS_NAMES = ("ollama app.exe", "ollama.exe")


def loaded_models() -> list[dict]:
    """当前**驻留在内存里**的模型。

    与 `start_llm.installed_models()` 的区别是这个脚本的全部意义所在：
    那个问的是"磁盘上装了什么"（`/api/tags`），这个问的是"内存里正占着什么"
    （`/api/ps`）。装了但没载入的模型不占内存，也就没什么可关的。
    """
    payload = start_llm._get("/api/ps")
    if not payload:
        return []
    return list(payload.get("models", []))


def describe(models: list[dict]) -> str:
    """把 /api/ps 的原始字节数说成人话。"""
    parts = []
    for entry in models:
        name = entry.get("name", "?")
        size = entry.get("size", 0)
        parts.append(f"{name}（{size / 1024 ** 3:.1f} GB）")
    return "、".join(parts)


def unload(model: str, timeout: float = 20.0) -> bool:
    """请服务把模型放掉：一次 ``keep_alive: 0`` 的空请求。

    这是 Ollama 官方的卸载方式，不是变通做法——`keep_alive` 传 0 表示
    "用完立刻卸"，配空 prompt 就退化成一次纯粹的卸载指令，不会真去推理。
    因为 `OLLAMA_KEEP_ALIVE = -1` 是环境级设置，只能靠单次请求覆盖它。
    """
    body = json.dumps({"model": model, "prompt": "", "keep_alive": 0}).encode("utf-8")
    request = urllib.request.Request(
        f"{start_llm._base_url()}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            resp.read()
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        print(f"  ✗ 卸载请求失败：{type(exc).__name__}: {exc}")
        return False
    return True


def wait_until_unloaded(deadline: float) -> bool:
    """等 /api/ps 真的空掉。

    请求返回不等于内存已经放掉——服务是异步收尾的，紧接着查一次
    往往还能看到那个模型。所以这里以 `/api/ps` 为准轮询，而不是以请求成功为准。
    """
    while time.time() < deadline:
        if not loaded_models():
            return True
        time.sleep(0.3)
    return not loaded_models()


def stop_processes() -> tuple[int, int]:
    """结束托盘程序与服务进程，返回（结束成功数, 本来就没在跑的数）。"""
    if os.name != "nt":
        print("  ✗ --server 目前只实现了 Windows 下的停法")
        return 0, 0

    stopped = absent = 0
    for name in PROCESS_NAMES:
        result = subprocess.run(  # noqa: S603
            ["taskkill", "/F", "/IM", name],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"  ✓ 已结束 {name}")
            stopped += 1
        else:
            # taskkill 找不到进程时返回 128，这不是失败：目标状态已经达到
            print(f"  · {name} 本来就没在运行")
            absent += 1
    return stopped, absent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="卸载本地语言模型，必要时连服务一起停掉",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--server", action="store_true", help="卸载后再停掉服务与托盘程序"
    )
    parser.add_argument(
        "--status", action="store_true", help="只看驻留情况，不动任何东西"
    )
    parser.add_argument(
        "--timeout", type=float, default=20.0, help="等待上限（秒），默认 20"
    )
    args = parser.parse_args(argv)

    print(f"本地语言模型 @ {start_llm._base_url()}")

    if not start_llm.server_alive():
        print("  · 服务未运行，模型自然也没占内存")
        if args.server:
            # 服务不应答不代表进程不在（可能卡在启动一半），照样清一遍
            stop_processes()
        return 0

    resident = loaded_models()
    if resident:
        print(f"  · 当前驻留：{describe(resident)}")
    else:
        print("  · 当前没有模型驻留内存")

    if args.status:
        return 0

    deadline = time.time() + args.timeout
    for entry in resident:
        name = entry.get("name", "")
        if not name:
            continue
        print(f"  … 正在卸载 {name}")
        if not unload(name, args.timeout):
            return 1

    if resident and not wait_until_unloaded(deadline):
        still = describe(loaded_models())
        print(f"  ✗ 仍在驻留：{still}")
        print("    可用 --server 直接停掉服务进程")
        return 1
    if resident:
        print("  ✓ 已卸载，内存已释放")

    if args.server:
        stop_processes()
        if start_llm.server_alive():
            print("  ✗ 服务仍在应答，可能是托盘程序又把它拉了起来")
            return 1
        print("  ✓ 服务已停止")
        print("\n下次要用时跑 start_llm_启动本地模型.bat，它会重新拉起并预热。")
    else:
        print("\n服务仍在运行。下次提问会重新载入模型（约 9 秒），")
        print("想连服务一起停就加 --server。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
