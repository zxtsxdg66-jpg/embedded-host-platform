"""启动脚本的可测部分。

脚本本身要拉进程、发网络请求，那些不适合进单测；但它的**判定逻辑**——
服务活没活、模型装没装、环境变量读哪一份——是纯函数，而且正是最容易
出错的地方：第一版就把"读 os.environ"当成了"变量设了没有"，
结果在一个早于变量设置时刻打开的终端里误报"未设置"。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "start_llm.py"
_spec = importlib.util.spec_from_file_location("start_llm", _SCRIPT)
assert _spec and _spec.loader
start_llm = importlib.util.module_from_spec(_spec)
sys.modules["start_llm"] = start_llm
_spec.loader.exec_module(start_llm)


class _Response:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_server_alive_is_false_when_nothing_answers(monkeypatch) -> None:
    """探测失败必须**返回 False 而不是抛异常**：模型不可用是这个功能的
    正常状态之一，不是错误。"""

    def refuse(*_args, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(start_llm.urllib.request, "urlopen", refuse)
    assert start_llm.server_alive() is False


def test_installed_models_reads_the_tag_list(monkeypatch) -> None:
    payload = {"models": [{"name": "qwen3.5:4b"}, {"name": "other:1b"}]}
    monkeypatch.setattr(
        start_llm.urllib.request, "urlopen", lambda *a, **k: _Response(payload)
    )
    assert start_llm.installed_models() == ["qwen3.5:4b", "other:1b"]


def test_installed_models_is_empty_when_the_server_is_down(monkeypatch) -> None:
    monkeypatch.setattr(
        start_llm.urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(OSError("down")),
    )
    assert start_llm.installed_models() == []


def test_environment_is_read_from_the_registry_not_just_the_process() -> None:
    """第一版只看 ``os.environ``，于是在一个早于变量设置时刻打开的终端里
    报"未设置"，而 PowerShell 查得到值。真正决定行为的是 Ollama 服务启动时
    看到的那一份，注册表里的才是权威。

    这里只断言函数存在且不抛——具体取值依赖本机注册表，不适合写死。
    """
    value = start_llm._user_env("OLLAMA_MODELS")
    assert value is None or isinstance(value, str)


def test_reporting_the_environment_never_raises(capsys) -> None:
    """这是启动脚本的第一步输出。它自己崩掉，用户就看不到后面所有诊断了。

    两条分支都要报出模型目录：读得到服务日志时报"服务实际在用"的那个，
    读不到时回落到注册表并明说这只是"设了没有"。因此这里断言的是
    两条分支共有的字样，而不是某一份配置来源的变量名。
    """
    start_llm.report_environment()
    out = capsys.readouterr().out
    assert "模型目录" in out or "OLLAMA_MODELS" in out


def test_check_mode_reports_a_dead_server_without_starting_anything(
    monkeypatch, capsys
) -> None:
    """``--check`` 的用途是在批处理里做前置判断，它绝不能顺手拉起进程。"""
    monkeypatch.setattr(start_llm, "server_alive", lambda *a, **k: False)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("--check 模式不应启动任何进程")

    monkeypatch.setattr(start_llm, "start_server", fail_if_called)

    assert start_llm.main(["--check"]) == 1
    assert "未运行" in capsys.readouterr().out


def test_a_missing_model_names_the_command_that_fixes_it(
    monkeypatch, capsys
) -> None:
    """报错要给出**下一步能敲什么**，而不只是说不行。"""
    monkeypatch.setattr(start_llm, "server_alive", lambda *a, **k: True)
    monkeypatch.setattr(start_llm, "installed_models", lambda: ["other:1b"])

    assert start_llm.main(["--model", "qwen3.5:4b"]) == 1
    out = capsys.readouterr().out
    assert "ollama pull qwen3.5:4b" in out


def test_warm_up_failure_is_reported_not_raised(monkeypatch) -> None:
    """预热失败同样是正常状态：模型没就绪，问答退回模板即可。"""
    monkeypatch.setattr(
        start_llm.urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(TimeoutError("too slow")),
    )
    ok, seconds = start_llm.warm_up("qwen3.5:4b", start_llm.time.time() + 1)
    assert ok is False
    assert seconds >= 0


@pytest.mark.parametrize("argv", [["--check"], ["--timeout", "5"]])
def test_argument_parsing_accepts_the_documented_forms(monkeypatch, argv) -> None:
    monkeypatch.setattr(start_llm, "server_alive", lambda *a, **k: False)
    assert start_llm.main(argv) == 1


# --- 服务实际生效的配置（2026-09-10 补） ------------------------------------
#
# 起因是一次真实事故：Ollama 自动升级把模型路径迁进了应用自己的 db.sqlite，
# 该设置优先于 OLLAMA_MODELS。注册表仍指向 D 盘，服务却去 C 盘空目录里找，
# 于是脚本一边打 ✓ 一边报"模型未下载"。判据从此改为服务自己打的那行日志。

_LOG_SAMPLE = (
    'time=2026-09-10T12:39:01.348+08:00 level=INFO source=routes.go:1955 '
    'msg="server config" env="map[CUDA_VISIBLE_DEVICES: OLLAMA_HOST:'
    'http://127.0.0.1:11434 OLLAMA_KEEP_ALIVE:2562047h47m16.854775807s '
    'OLLAMA_MODELS:C:\\\\Users\\\\user\\\\.ollama\\\\models '
    'OLLAMA_NOHISTORY:false]"\n'
    'time=2026-09-10T12:39:01.358+08:00 level=INFO source=images.go:957 '
    'msg="total blobs: 0"\n'
)


def test_effective_config_reads_what_the_server_actually_uses(tmp_path) -> None:
    log = tmp_path / "server.log"
    log.write_text(_LOG_SAMPLE, encoding="utf-8")

    config = start_llm.effective_config(log)

    assert config["OLLAMA_MODELS"] == r"C:\Users\user\.ollama\models"
    assert config["OLLAMA_KEEP_ALIVE"] == "2562047h47m16.854775807s"
    assert config["blobs"] == "0"


def test_effective_config_keeps_paths_that_contain_spaces(tmp_path) -> None:
    """值切到"下一个全大写键名"为止，不能切到空格——否则装在
    `Program Files` 下的路径会被截成半截，报出一个不存在的目录。"""
    log = tmp_path / "server.log"
    log.write_text(
        'msg="server config" env="map[OLLAMA_MODELS:D:\\\\Program Files\\\\models '
        'OLLAMA_NOHISTORY:false]"\n',
        encoding="utf-8",
    )

    config = start_llm.effective_config(log)
    assert config["OLLAMA_MODELS"] == r"D:\Program Files\models"


def test_effective_config_is_empty_when_there_is_no_log(tmp_path) -> None:
    """没装、装在别处、非 Windows 都会走到这里，必须回落而不是抛。"""
    assert start_llm.effective_config(tmp_path / "nope.log") == {}


def test_a_drifted_model_path_is_called_out(monkeypatch, capsys) -> None:
    """这正是那次事故的形状：服务用 C 盘、注册表写着 D 盘、读到 0 个文件。"""
    monkeypatch.setattr(
        start_llm,
        "effective_config",
        lambda *a, **k: {
            "OLLAMA_MODELS": r"C:\Users\user\.ollama\models",
            "OLLAMA_KEEP_ALIVE": "2562047h47m16.854775807s",
            "blobs": "0",
        },
    )
    monkeypatch.setattr(start_llm, "_user_env", lambda name: r"D:\Ollama\models")

    start_llm.report_environment()
    out = capsys.readouterr().out

    assert "✗" in out
    assert "不一致" in out
    assert r"D:\Ollama\models" in out


def test_a_matching_model_path_is_not_flagged(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        start_llm,
        "effective_config",
        lambda *a, **k: {"OLLAMA_MODELS": r"D:\Ollama\models", "blobs": "4"},
    )
    monkeypatch.setattr(start_llm, "_user_env", lambda name: r"D:\Ollama\models")

    start_llm.report_environment()
    out = capsys.readouterr().out

    assert "不一致" not in out
    assert "服务读到 4 个模型文件" in out


def test_keep_alive_max_duration_is_translated() -> None:
    """-1 在日志里被 Go 打成 2562047h47m16s，照搬出来没人看得懂。"""
    assert start_llm._describe_keep_alive("2562047h47m16.854775807s") == "永不卸载"
    assert start_llm._describe_keep_alive("-1") == "永不卸载"
    assert start_llm._describe_keep_alive("5m0s") == "5m0s"
