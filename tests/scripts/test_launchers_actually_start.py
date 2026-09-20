"""每个启动器都必须**真的能起来**，而不只是源码里有那几个符号。

2026-09-17 踩到：`scripts/automation_wiring.py` 里把 `question_log` 写成了
`from scripts.question_log import ...`。启动器一族只把 `src/` 与 `scripts/`
加进 `sys.path`、**从不加项目根**，于是 `No module named 'scripts'`，
`run_gui` / `run_all` / `run_api_server` / `run_gui_hardware` 四个全部起不来——
上位机根本打不开。

而当时测试是全绿的。原因值得记住：`test_automation_wiring.py` 里那几条守卫用
`inspect.getsource()` 检查源码里有没有出现某些符号，**只验文本、不验能否运行**；
pytest 自己又是以包路径（`scripts.automation_wiring`）导入的，项目根天然在
`sys.path` 上，恰好绕开了这个 bug。两件事叠加，测试给出的是虚假的安全感。

所以这组用例用**子进程**真的去跑那些入口。`scripts/` 下有两族入口，验法不同：

* **带 argparse 的**（`run_gui`/`run_all`/`run_api_server`/`cloud_sync`/`cloud_view`）
  跑 `--help`：走完整条 import 链后由 argparse 打印并以 0 退出，既验出 import
  问题，又不会真的拉起窗口、串口或服务器。
* **纯交互的**（`run_gui_hardware`、两个 `*_launcher`、`collect_data_launcher`）
  没有 `--help`，一上来就 `input()` 让人选串口或模式。喂空 stdin 让它以
  `EOFError` 收场是**预期行为**，这里只断言 stderr 里没有 import 类错误——
  要守的是"import 链通不通"，不是"能不能无人值守跑完"。

这正是本项目反复验证过的那条经验——"能编译/测试通过"不等于"功能真的能用"
（见 `docs/05_Test/Project_Status_Context.md` 第 8 节）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts"

_IMPORT_ERRORS = ("ModuleNotFoundError", "ImportError")

WITH_ARGPARSE = [
    "run_gui.py",
    "run_all.py",
    "run_api_server.py",
    "cloud_sync.py",
    "cloud_view.py",
]

INTERACTIVE = [
    "run_gui_hardware.py",
    "run_all_launcher.py",
    "run_api_server_launcher.py",
    "collect_data_launcher.py",
]
"""纯交互入口：无 argparse，启动即 `input()`。

不含 `automation_wiring.py`、`question_log.py` 这类被 import 的模块——它们没有
`main()`，正确性由上面这些入口起得来间接保证。
"""


def _run(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SCRIPTS / name), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        input="",           # 交互入口据此以 EOFError 收场，不会挂住
        timeout=120,
        cwd=str(_ROOT),
    )


def _assert_no_import_error(
    name: str, result: subprocess.CompletedProcess[str]
) -> None:
    for marker in _IMPORT_ERRORS:
        assert marker not in result.stderr, (
            f"{name} 启动时出现 {marker}：\n{result.stderr[-800:]}"
        )


@pytest.mark.parametrize("name", WITH_ARGPARSE)
def test_an_argparse_launcher_prints_help(name: str) -> None:
    """`--help` 能正常打印即说明整条 import 链是通的。"""
    result = _run(name, "--help")

    _assert_no_import_error(name, result)
    assert result.returncode == 0, (
        f"{name} --help 退出码 {result.returncode}\n"
        f"--- stdout ---\n{result.stdout[-600:]}\n"
        f"--- stderr ---\n{result.stderr[-600:]}"
    )


@pytest.mark.parametrize("name", INTERACTIVE)
def test_an_interactive_launcher_imports_cleanly(name: str) -> None:
    """纯交互入口：允许因空 stdin 而 EOFError，但不许有 import 错误。

    换句话说，它至少要活到"开口问人"那一步——能问，就说明模块全部加载完了。
    """
    result = _run(name)

    _assert_no_import_error(name, result)


@pytest.mark.parametrize("name", WITH_ARGPARSE + INTERACTIVE)
def test_the_launcher_does_not_need_the_project_root_on_sys_path(name: str) -> None:
    """启动器不得依赖项目根在 `sys.path` 上。

    这是上面那个 bug 的根：`.bat` 跑的是 `python scripts\\xxx.py`，Python 只会
    把 **`scripts/` 目录**加进 `sys.path`，项目根不在其中。用 `-P`（等价于
    `PYTHONSAFEPATH`）连脚本所在目录都不自动加，是更严格的一档——脚本必须
    自己把需要的路径补齐。
    """
    result = subprocess.run(
        [sys.executable, "-P", str(_SCRIPTS / name), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        input="",
        timeout=120,
        cwd=str(_ROOT),
    )

    assert "No module named 'scripts'" not in result.stderr, (
        f"{name} 依赖项目根在 sys.path 上：\n{result.stderr[-800:]}"
    )
