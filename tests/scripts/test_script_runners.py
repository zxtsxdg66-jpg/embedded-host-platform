"""按钮背后那两个 runner：它们**真的**拉起了哪个脚本、带了哪些参数。

2026-09-21 补。在此之前 `make_cloud_sync_runner` / `make_cloud_view_runner`
一条测试都没有——而这一族正是本项目反复栽过的地方：`ui` 只拿到一个可调用
对象，出了问题界面上看不出任何异常（2026-09-18 的标签错配就是这样，
按钮压根没出现，全程无报错）。

这一组守的是**参数**，因为参数是这次改动的全部内容：上云按钮从这天起带
`--snapshot`，少了它，按钮就只会补齐已结束的整点时段——而"把现在的数据
传上去"恰好是加这个按钮的人想做的事，且失败时毫无迹象：脚本正常退出、
控制台一切正常，只是云上没有当前这一小时。
"""

from __future__ import annotations

from pathlib import Path

from scripts import automation_wiring
from scripts.automation_wiring import (
    make_cloud_sync_runner,
    make_cloud_view_runner,
)


class _Recorder:
    """记下 Popen 收到的命令行，不真的起进程。"""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command, **kwargs):  # noqa: ANN001, ANN204
        self.commands.append([str(part) for part in command])
        return object()


def _run(monkeypatch, make) -> tuple[list[str], list[str]]:
    recorder = _Recorder()
    monkeypatch.setattr(automation_wiring.subprocess, "Popen", recorder)
    messages: list[str] = []
    make(messages.append)()
    assert len(recorder.commands) == 1
    return recorder.commands[0], messages


def test_the_upload_button_asks_for_a_current_hour_snapshot(monkeypatch) -> None:
    """**这一条是本次改动的锚。**

    归档按整点切，当前这一小时永远不会被归档（`scripts/cloud_sync.py`）。
    没有 `--snapshot`，按钮在整点之前做不到"把现在的数据传上去"，
    而它不会报错——只是云上少了当前这一小时。
    """
    command, messages = _run(monkeypatch, make_cloud_sync_runner)

    assert Path(command[1]).name == "cloud_sync.py"
    assert "--snapshot" in command
    assert len(messages) == 1


def test_the_view_button_passes_no_arguments(monkeypatch) -> None:
    """只读的那个不带参数——顺带钉住"args 默认为空"这件事：
    默认带上参数会让下一个用这个工厂的按钮莫名其妙地多一个开关。"""
    command, messages = _run(monkeypatch, make_cloud_view_runner)

    assert Path(command[1]).name == "cloud_view.py"
    assert command[2:] == []
    assert len(messages) == 1


def test_both_runners_point_at_scripts_that_exist(monkeypatch) -> None:
    """拼错脚本名的表现是"点了按钮什么都没发生"，与"脚本自己失败了"
    在界面上长得一模一样。"""
    for make in (make_cloud_sync_runner, make_cloud_view_runner):
        command, _ = _run(monkeypatch, make)
        assert Path(command[1]).is_file(), command[1]


def test_a_failure_to_start_only_logs_a_line(monkeypatch) -> None:
    """用户按的是聊天面板里的一个按钮，不该因此弹出异常对话框。"""

    def explode(*_args, **_kwargs):
        raise OSError("no such file")

    monkeypatch.setattr(automation_wiring.subprocess, "Popen", explode)
    messages: list[str] = []
    make_cloud_sync_runner(messages.append)()

    assert len(messages) == 1
    assert "失败" in messages[0]
