"""把本地语言模型拉起来并等它真的可用。

**为什么需要这个脚本。** Ollama 在本机不是系统服务，而是靠"启动文件夹"里的
`Ollama.lnk` 自启（`Get-CimInstance Win32_StartupCommand` 实测确认）。这带来两个
在演示当天才会咬人的性质：

- 必须**登录进桌面**才会起——远程或锁屏状态下服务并不存在；
- 托盘程序拉起服务需要几秒，而模型首次加载还要再几秒。开发期间机器一直没关，
  所以这两段延迟从未暴露过。

脚本做四件事，每件都能单独失败并给出可执行的下一步：探测服务、必要时拉起、
确认模型已下载、**发一次真实请求把模型载入内存**。最后一步不能省——
服务活着不等于模型可用，而"可用"正是问答功能唯一关心的事。

用法::

    python scripts/start_llm.py              # 拉起并预热
    python scripts/start_llm.py --check      # 只探测，不启动任何东西
    python scripts/start_llm.py --timeout 90 # 冷启动慢时放宽等待

退出码：0 可用；1 不可用（原因已打印）。可直接用在批处理里做前置检查。

问答功能**不依赖**本脚本：模型缺席时系统照常回答，只是措辞用模板。
这个脚本解决的是"演示时希望它在"，不是"没它就不行"。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# 与 src/llm/ollama.py 保持一致；此处不 import src，脚本要能在任何环境下先跑起来
HOST = "127.0.0.1"
PORT = 11434
MODEL = "qwen3.5:4b"

# 安装位置来自 docs/decisions/02-llm.md：刻意装在 D 盘，
# 因为目标机 C 盘只剩 49.6 GB 而模型是会持续增长的部分。
OLLAMA_EXE_CANDIDATES = (
    Path(r"D:\Ollama\ollama.exe"),
    Path(r"D:\Ollama\ollama app.exe"),
)

# 服务自己的日志。它启动时会把**实际生效**的配置整行打出来，
# 这是唯一能证明"服务在用哪个模型目录"的一手材料，见 effective_config()。
SERVER_LOG = Path(os.environ.get("LOCALAPPDATA", "")) / "Ollama" / "server.log"

WARMUP_PROMPT = "现在温度是 24.8℃。"
"""预热用的一句话。刻意与改写档的真实输入同形——预热的目的是把模型载入内存
并把系统提示的 KV 前缀算好，用一句不相干的话就白热了。"""


def _base_url() -> str:
    return f"http://{HOST}:{PORT}"


def _get(path: str, timeout: float = 2.0):
    try:
        with urllib.request.urlopen(f"{_base_url()}{path}", timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return None


def server_alive(timeout: float = 2.0) -> bool:
    """服务是否应答。用 /api/tags 而非 / ：前者顺带证明它能读到模型目录。"""
    return _get("/api/tags", timeout) is not None


def installed_models() -> list[str]:
    payload = _get("/api/tags")
    if not payload:
        return []
    return [m.get("name", "") for m in payload.get("models", [])]


def find_executable() -> Path | None:
    for candidate in OLLAMA_EXE_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def start_server(executable: Path) -> None:
    """后台拉起 `ollama serve`，不占用当前控制台。

    用 DETACHED_PROCESS 而不是简单的 Popen：本脚本多半是被别的批处理调用的，
    调用方退出时不该把刚拉起来的服务一起带走。
    """
    creation = 0
    if os.name == "nt":
        creation = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    subprocess.Popen(  # noqa: S603
        [str(executable), "serve"],
        creationflags=creation,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_until_alive(deadline: float) -> bool:
    while time.time() < deadline:
        if server_alive():
            return True
        time.sleep(0.5)
    return False


def warm_up(model: str, deadline: float) -> tuple[bool, float]:
    """发一次真实请求，把模型从磁盘载入内存。

    返回 (是否成功, 耗时)。**这一步不能省**：服务活着只说明端口通了，
    而首次推理要从磁盘读 3.4 GB 权重，演示现场那几秒的停顿正是从这里来的。
    """
    body = json.dumps(
        {
            "model": model,
            "prompt": WARMUP_PROMPT,
            "stream": False,
            "think": False,
            "options": {"num_predict": 16, "temperature": 0.3},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{_base_url()}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    started = time.time()
    remaining = max(deadline - started, 5.0)
    try:
        with urllib.request.urlopen(request, timeout=remaining) as resp:
            json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError) as exc:
        print(f"  预热请求失败：{type(exc).__name__}: {exc}")
        return False, time.time() - started
    return True, time.time() - started


def _user_env(name):
    """读用户级环境变量（Windows 注册表）。

    不能只看 ``os.environ``：这两个变量是用**用户级**设的，而任何早于它们
    设置时刻启动的进程都继承不到——本脚本第一次跑就撞上了，明明 PowerShell
    查得到值，脚本却报"未设置"。真正决定行为的是 **Ollama 服务进程启动时**
    看到的值，注册表里那份才是权威。
    """
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _kind = winreg.QueryValueEx(key, name)
            return str(value)
    except (OSError, ImportError, FileNotFoundError):
        return None


def effective_config(log: Path | None = None) -> dict[str, str]:
    """读**服务实际生效**的配置，来源是 Ollama 启动时打的那行 server config。

    为什么不能只看环境变量或注册表：Ollama 0.33 起，桌面应用把设置迁进了
    ``%LOCALAPPDATA%\\Ollama\\db.sqlite``，应用内的模型路径**优先于**
    ``OLLAMA_MODELS``。2026-09-10 就为此丢过一次模型：注册表指向 D 盘，
    自动升级把应用内设置填成了 C 盘默认值，服务去空目录里找，
    而本脚本照着注册表打了个 ✓——**一边显示配置正确，一边报模型没装**。
    权威只有一个：服务自己说它在用哪个目录。

    返回解析到的键值；日志不存在或格式变了就返回空字典，由调用方回落。
    """
    path = SERVER_LOG if log is None else log
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    config: dict[str, str] = {}
    for line in text.splitlines():
        if 'msg="server config"' in line:
            # 形如 env="map[K:V K2:V2 ...]"，值里可能有空格（路径），
            # 因此切到"下一个全大写键名加冒号"为止，而不是切到空格。
            for name in ("OLLAMA_MODELS", "OLLAMA_KEEP_ALIVE"):
                found = re.search(rf"{name}:(.*?)(?= [A-Z][A-Z0-9_]*:|\]\"?$)", line)
                if found:
                    # 日志里反斜杠是转义过的
                    config[name] = found.group(1).strip().replace("\\\\", "\\")
        if "total blobs:" in line:
            found = re.search(r"total blobs:\s*(\d+)", line)
            if found:
                config["blobs"] = found.group(1)
    return config


def _describe_keep_alive(value: str) -> str:
    """-1 在日志里会被打成 2562047h47m16s（Go 的最大 Duration），翻译回人话。"""
    return "永不卸载" if value.startswith("2562047h") or value == "-1" else value


def report_environment():
    """打印决定成败却容易被忘记的两项配置，**以服务实际生效的值为准**。

    读不到服务日志时才回落到注册表——那时只能回答"设了没有"，
    回答不了"服务在不在用"，所以措辞上也不能说得像是确认过。
    """
    config = effective_config()

    if config.get("OLLAMA_MODELS"):
        models_dir = config["OLLAMA_MODELS"]
        blobs = config.get("blobs")
        seen = f"，服务读到 {blobs} 个模型文件" if blobs is not None else ""
        mark = "✗" if blobs == "0" else "✓"
        print(f"  {mark} 模型目录（服务实际在用）= {models_dir}{seen}")

        registry = _user_env("OLLAMA_MODELS")
        if registry and Path(registry) != Path(models_dir):
            print(f"    ! 与环境变量 OLLAMA_MODELS = {registry} 不一致")
            print("      Ollama 0.33 起以应用内设置为准，不再看这个变量")
            print("      （%LOCALAPPDATA%\\Ollama\\db.sqlite 里的 settings.models）")
            print("      在 Ollama 应用的设置里改模型位置，或让默认路径指向真实目录")
        if blobs == "0":
            print("      服务在这个目录下一个文件都没读到——模型多半没丢，是路径漂了")

        keep_alive = config.get("OLLAMA_KEEP_ALIVE", "")
        if keep_alive:
            described = _describe_keep_alive(keep_alive)
            mark = "✓" if described == "永不卸载" else "!"
            print(f"  {mark} 模型驻留 = {described}    设为 -1 才不会空闲五分钟后卸载")
        return

    # 回落：读不到服务日志（没装、装在别处、非 Windows）
    print(f"  … 读不到服务日志（{SERVER_LOG}），以下只是“变量设了没有”，")
    print("    不代表服务实际在用——服务起来后再跑一次本脚本即可看到真实值")
    for name, why in (
        ("OLLAMA_MODELS", "模型目录；未设则回落到 C 盘"),
        ("OLLAMA_KEEP_ALIVE", "设为 -1 才不会空闲五分钟后卸载模型"),
    ):
        registry = _user_env(name)
        inherited = os.environ.get(name)
        if registry:
            note = "" if inherited else "（本终端未继承，不影响已启动的服务）"
            print(f"  · {name} = {registry}    {why} {note}")
        else:
            print(f"  ✗ {name} 未设置    {why}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="拉起本地语言模型并等它真的可用",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--check", action="store_true", help="只探测，不启动任何东西"
    )
    parser.add_argument(
        "--timeout", type=float, default=60.0, help="总等待上限（秒），默认 60"
    )
    parser.add_argument("--model", default=MODEL, help=f"模型名，默认 {MODEL}")
    args = parser.parse_args(argv)

    model = args.model
    deadline = time.time() + args.timeout

    print(f"本地语言模型：{model} @ {_base_url()}")
    report_environment()

    # 1. 服务
    if server_alive():
        print("  ✓ 服务已在运行")
    elif args.check:
        print("  ✗ 服务未运行（--check 模式不启动）")
        return 1
    else:
        executable = find_executable()
        if executable is None:
            print("  ✗ 服务未运行，且找不到 ollama.exe")
            print("    预期位置：" + " 或 ".join(str(p) for p in OLLAMA_EXE_CANDIDATES))
            print("    若装在别处，直接手工执行一次 `ollama serve` 即可")
            return 1
        print(f"  … 服务未运行，正在拉起：{executable}")
        start_server(executable)
        if not wait_until_alive(deadline):
            print("  ✗ 拉起后仍未应答，可能是端口被占或安装损坏")
            return 1
        print("  ✓ 服务已就绪")

    # 2. 模型是否下载
    models = installed_models()
    if model not in models:
        print(f"  ✗ 模型 {model} 未下载。已装：{', '.join(models) or '（无）'}")
        print(f"    执行：ollama pull {model}")
        return 1
    print(f"  ✓ 模型已下载（本机共 {len(models)} 个）")

    if args.check:
        print("  （--check 模式，跳过预热）")
        return 0

    # 3. 预热——服务活着不等于模型可用
    print("  … 预热中（首次要从磁盘载入约 3.4 GB，请稍候）")
    ok, seconds = warm_up(model, deadline)
    if not ok:
        return 1
    print(f"  ✓ 预热完成，耗时 {seconds:.1f} s")
    if seconds > 15:
        print("    （偏慢，多半是冷启动；再跑一次通常在 1 秒内）")
    print("\n模型可用。现在启动上位机即可，问答会走模型改写。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
