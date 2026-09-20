"""关闭脚本的可测部分。

与 `test_start_llm.py` 同样的取舍：真去杀进程、发网络请求的部分不进单测，
但**判定逻辑**必须测——这个脚本的每一条分支都对应一种"看起来关掉了其实没关"
的假象：请求成功不等于内存放掉（服务异步收尾）、只杀 `ollama.exe` 会被托盘
程序重新拉起、`taskkill` 找不到进程返回 128 却不是失败。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
# stop_llm 内部 `import start_llm`：正常运行时靠 sys.path[0]，测试里要手工补上
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_spec = importlib.util.spec_from_file_location("stop_llm", _SCRIPTS / "stop_llm.py")
assert _spec and _spec.loader
stop_llm = importlib.util.module_from_spec(_spec)
sys.modules["stop_llm"] = stop_llm
_spec.loader.exec_module(stop_llm)


_RESIDENT = {
    "models": [{"name": "qwen3.5:4b", "size": 3134277548, "size_vram": 0}]
}


def test_loaded_models_reads_the_process_list(monkeypatch) -> None:
    """问的是"内存里占着什么"（/api/ps），不是"磁盘上装了什么"（/api/tags）。"""
    monkeypatch.setattr(stop_llm.start_llm, "_get", lambda path, *a, **k: _RESIDENT)
    assert [m["name"] for m in stop_llm.loaded_models()] == ["qwen3.5:4b"]


def test_loaded_models_is_empty_when_the_server_is_down(monkeypatch) -> None:
    monkeypatch.setattr(stop_llm.start_llm, "_get", lambda *a, **k: None)
    assert stop_llm.loaded_models() == []


def test_describe_turns_bytes_into_something_readable() -> None:
    assert stop_llm.describe(_RESIDENT["models"]) == "qwen3.5:4b（2.9 GB）"


def test_unload_sends_keep_alive_zero(monkeypatch) -> None:
    """卸载靠的就是这一个字段：环境级的 KEEP_ALIVE=-1 只能被单次请求覆盖。
    这个断言要是塌了，脚本会安静地变成"发一次请求然后什么也没发生"。"""
    sent = {}

    class _Resp:
        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, *a, **k):
        sent.update(json.loads(request.data))
        return _Resp()

    monkeypatch.setattr(stop_llm.urllib.request, "urlopen", fake_urlopen)

    assert stop_llm.unload("qwen3.5:4b") is True
    assert sent["keep_alive"] == 0
    assert sent["model"] == "qwen3.5:4b"


def test_unload_failure_is_reported_not_raised(monkeypatch) -> None:
    monkeypatch.setattr(
        stop_llm.urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(OSError("down")),
    )
    assert stop_llm.unload("qwen3.5:4b") is False


def test_status_mode_changes_nothing(monkeypatch, capsys) -> None:
    """--status 是给"先看看再决定"用的，它动手就失去意义了。"""
    monkeypatch.setattr(stop_llm.start_llm, "server_alive", lambda *a, **k: True)
    monkeypatch.setattr(stop_llm, "loaded_models", lambda: _RESIDENT["models"])

    def fail_if_called(*_a, **_k):
        raise AssertionError("--status 不应卸载任何东西")

    monkeypatch.setattr(stop_llm, "unload", fail_if_called)
    monkeypatch.setattr(stop_llm, "stop_processes", fail_if_called)

    assert stop_llm.main(["--status"]) == 0
    assert "qwen3.5:4b" in capsys.readouterr().out


def test_a_dead_server_is_success_not_failure(monkeypatch, capsys) -> None:
    """"本来就没在跑"就是目标状态。这里返回 1 会让批处理误判成出错。"""
    monkeypatch.setattr(stop_llm.start_llm, "server_alive", lambda *a, **k: False)
    assert stop_llm.main([]) == 0
    assert "服务未运行" in capsys.readouterr().out


def test_missing_processes_are_not_treated_as_failure(monkeypatch, capsys) -> None:
    """taskkill 找不到进程返回 128。把它当失败，第二次运行就会报错。"""
    monkeypatch.setattr(
        stop_llm.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 128, "", "not found"),
    )
    stopped, absent = stop_llm.stop_processes()
    assert (stopped, absent) == (0, len(stop_llm.PROCESS_NAMES))
    assert "本来就没在运行" in capsys.readouterr().out


def test_the_tray_program_is_stopped_before_the_server() -> None:
    """顺序不是随手排的：托盘程序是服务的看门狗，后杀它就会看到服务"杀不掉"。"""
    assert stop_llm.PROCESS_NAMES[0] == "ollama app.exe"


def test_unloading_waits_for_the_memory_to_actually_be_released(monkeypatch) -> None:
    """请求返回不等于内存已放掉，服务是异步收尾的。以 /api/ps 为准。"""
    monkeypatch.setattr(stop_llm, "loaded_models", lambda: _RESIDENT["models"])
    assert stop_llm.wait_until_unloaded(stop_llm.time.time() + 0.2) is False

    monkeypatch.setattr(stop_llm, "loaded_models", list)
    assert stop_llm.wait_until_unloaded(stop_llm.time.time() + 0.2) is True
