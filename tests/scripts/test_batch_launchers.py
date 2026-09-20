"""根目录那些可双击的 `.bat` 启动器，文件格式必须对。

2026-09-17 踩到：新写的 `cloud_sync_导出并上传.bat` /
`cloud_view_查看云端.bat` 用裸 LF 换行，
`cmd.exe` 解析批处理时行结构直接散掉——它把注释碎片当成命令去执行，报出
一串 `'rule' 不是内部或外部命令`、`此时不应有 else`，退出码 255。脚本本身
（`scripts/cloud_sync.py`）完全正常，故障点只在 `.bat` 这层包装。

普查后发现这不是孤例：`collect_data_实验数据采集.bat` 同样是裸 LF 且带中文，属于同一种
待爆的雷；`run_gui_模拟数据界面.bat` 等四个是裸 LF 但纯 ASCII，侥幸能跑——只要谁给它们
加一行中文注释就会崩，而那时错误信息跟"加了一行注释"毫无关联，极难定位。

所以把它钉成测试，而不是写一条"记得用 CRLF"的规矩：这类约束靠记性迟早会漏。
"""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _batch_files() -> list[Path]:
    return sorted(_ROOT.glob("*.bat"))


def test_there_are_batch_launchers_to_check() -> None:
    """先确认真的找到了文件——否则下面几条会因为列表为空而空过。"""
    assert len(_batch_files()) >= 8


@pytest.mark.parametrize("path", _batch_files(), ids=lambda p: p.name)
def test_every_batch_file_uses_crlf(path: Path) -> None:
    """`cmd.exe` 对裸 LF 的批处理行为不可靠，带中文时必崩。"""
    raw = path.read_bytes()
    bare_lf = raw.count(b"\n") - raw.count(b"\r\n")

    assert bare_lf == 0, (
        f"{path.name} 有 {bare_lf} 处裸 LF 换行。"
        "cmd.exe 会把行结构解析错，带中文时直接崩（2026-09-17 实测）。"
    )


@pytest.mark.parametrize("path", _batch_files(), ids=lambda p: p.name)
def test_every_batch_file_is_valid_utf8(path: Path) -> None:
    """中文必须是 UTF-8。

    这些 `.bat` 开头都有 `chcp 65001`，正是按 UTF-8 显示中文的前提；
    存成 GBK 反而会显示成乱码。既有的 `start_llm_启动本地模型.bat` 就是 UTF-8。
    """
    path.read_bytes().decode("utf-8")


@pytest.mark.parametrize("path", _batch_files(), ids=lambda p: p.name)
def test_a_batch_file_with_chinese_declares_the_code_page(path: Path) -> None:
    """含中文就必须先 `chcp 65001`，否则控制台按 GBK 解释 UTF-8 字节。

    纯 ASCII 的启动器不需要这一行，所以只在含非 ASCII 时要求。
    """
    raw = path.read_bytes()
    if all(byte < 128 for byte in raw):
        return
    assert b"chcp 65001" in raw, f"{path.name} 含中文却没有 chcp 65001"
