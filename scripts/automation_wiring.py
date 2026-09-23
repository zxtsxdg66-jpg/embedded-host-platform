"""Shared wiring for the three device automations, used by every launcher.

The automations -- ventilation, spoken alarms, and the board's alarm-state
display -- each need three things done consistently:

1. the device must *accept* their command types, or DeviceManager's
   simulated-ack path rejects them in Simulator mode;
2. ``runtime.enable_*`` must be called, or the dispatchers are never
   installed;
3. ``dispatch_pending()`` must be driven from the poll loop, never from a
   data callback (see application/fan_dispatcher.py's module docstring for
   why sending from the callback re-enters the serial read loop).

This module exists because getting one of the three right in one launcher
and wrong in another is exactly what happened: when the automations were
added on 2026-09-07 only ``scripts/run_gui.py`` was wired, so
``run_api_server_手机网关.bat`` and ``run_all_界面加网关.bat``
silently ran without any of them -- and the latter is the mode used to
demonstrate the phone and the desktop together. Nothing failed loudly; the fan simply
never turned
on. Centralising the three steps here means a future automation is either
wired everywhere or nowhere, rather than in whichever launcher its author
happened to be editing.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

# 本模块被两族调用方共用，而它们给的 sys.path 不一样：
#   * 启动器一族（run_gui / run_all / run_api_server）只加 src/ 与 scripts/，
#     彼此之间用平级 import（`import run_api_server`）；
#   * 分析脚本一族（assistant_benchmark / demo_rehearsal）加的是**项目根**，
#     用包路径（`from scripts.automation_wiring import ...`）；pytest 同此。
# 所以这里不能假定哪一种存在。自己把 scripts/ 补上，再用平级 import，
# 三种上下文就都成立。
#
# 2026-09-17 踩过：`question_log` 落地时这里写成了 `from scripts.question_log
# import ...`，在启动器一族下根目录不在 path 上，四个启动器全部
# ModuleNotFoundError 起不来——而测试是以包路径导入的，全绿。
_SCRIPTS_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPTS_DIR.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from question_log import QuestionLog  # noqa: E402  (same scripts/ directory)

from api.local_api import LocalApi  # noqa: E402 (see sys.path setup above)
from application.alarm_state_dispatcher import ALARM_STATE_COMMAND  # noqa: E402
from application.answer_dispatcher import ANSWER_SHOW_COMMAND  # noqa: E402
from application.export_status import LedgerExportStatus  # noqa: E402
from application.fan_dispatcher import (  # noqa: E402
    DEFAULT_FAN_OFF_COMMAND,
    DEFAULT_FAN_ON_COMMAND,
)
from application.runtime import ApplicationRuntime  # noqa: E402
from core.models import DeviceId  # noqa: E402
from llm.ollama import DEFAULT_MODEL, OllamaClient  # noqa: E402
from service.alarm_announcer import AlertKind  # noqa: E402
from service.assistant.models import Answer  # noqa: E402
from service.history import HistoryStore  # noqa: E402
from storage.export_ledger import SqliteExportLedger  # noqa: E402
from storage.sqlite_history import (  # noqa: E402
    DEFAULT_DATABASE_PATH,
    SqliteHistoryStore,
)

AUTOMATION_COMMANDS: tuple[str, ...] = (
    DEFAULT_FAN_ON_COMMAND,
    DEFAULT_FAN_OFF_COMMAND,
    *(kind.value for kind in AlertKind),
    ALARM_STATE_COMMAND,
    ANSWER_SHOW_COMMAND,
)
"""Command types the automations dispatch.

Register devices with these (plus whatever else they accept) or the
commands are rejected before they reach the wire.
"""

ACCEPTED_COMMANDS: tuple[str, ...] = ("PING", *AUTOMATION_COMMANDS)
"""The full set every launcher registers its devices with."""


def enable_automations(runtime: ApplicationRuntime, device_id: DeviceId) -> None:
    """Install the ventilation, announcement and alarm-state dispatchers.

    ``device_id`` is the device that physically carries the fan, the
    speaker and the screen. In Simulator mode there is no such hardware,
    but the path is still wired so the feature can be demonstrated and
    tested without a board -- commands are acknowledged by DeviceManager's
    simulated-ack path, and everything above DataService behaves exactly
    as in Hardware mode.
    """
    runtime.enable_fan_control(device_id)
    runtime.enable_alert_announcements(device_id)
    runtime.enable_alarm_state_mirroring(device_id)
    runtime.enable_answer_display(device_id)


def dispatch_automations(runtime: ApplicationRuntime) -> None:
    """Flush whatever the automations decided during the last data cycle.

    Call from the poll loop, immediately after ``runner.run_once()`` --
    never from a data callback. Cheap and safe to call every cycle: each
    dispatcher returns immediately when it has nothing to send, and none
    of them raise.
    """
    for dispatcher in (
        runtime.fan_dispatcher,
        runtime.alert_dispatcher,
        runtime.alarm_state_dispatcher,
        runtime.answer_dispatcher,
    ):
        if dispatcher is not None:
            dispatcher.dispatch_pending()


AssistantAnswerSink = Callable[[str, str], None]
"""Receives ``(text, source)`` when a language model finishes rewording an
answer. Plain strings, so a launcher can hand this straight to a Qt view
without either side importing the other's types."""


def make_poll_once(
    runtime: ApplicationRuntime,
    runner: object,
    on_assistant_answer: AssistantAnswerSink | None = None,
    on_assistant_detail: Callable[[Answer], None] | None = None,
) -> Callable[[], None]:
    """Build the callable a launcher's timer/thread should drive.

    One drive cycle: move data up, act on what the automations decided
    while it moved, persist whatever accumulated, then collect anything
    the language model finished.
    ``runner`` is anything with ``run_once()`` -- the two runner types
    share that shape but no base class.

    The assistant is polled here for the same reason everything else is:
    a CPU-only model takes seconds to answer, and this process has no
    thread to wait on. ``poll_assistant()`` returns None on almost every
    cycle, so the cost is a null check.

    ``on_assistant_detail`` receives the same late answer as a whole
    :class:`Answer`, trace included -- the web console's view of what the
    exit checks did (added 2026-09-23). It is separate from
    ``on_assistant_answer`` so the ``(text, source)`` sink the desktop
    controller shares keeps its shape.
    """
    run_once = runner.run_once  # type: ignore[attr-defined]

    def poll_once() -> None:
        run_once()
        dispatch_automations(runtime)
        # 落盘放在提前 return 之前：run_api_server 不传 on_assistant_answer
        # 之外的东西时也必须写历史。把它放到 return 之后，就会变成
        # "界面模式记得下来、网关模式记不下来"——正是本模块存在的那类漂移。
        runtime.history_recorder.flush_if_due()
        if on_assistant_answer is None and on_assistant_detail is None:
            return
        improved = runtime.poll_assistant()
        if improved is None:
            return
        if on_assistant_answer is not None:
            on_assistant_answer(improved.text, improved.source.value)
        if on_assistant_detail is not None:
            on_assistant_detail(improved)

    return poll_once


class LoggingApi(LocalApi):
    """``LocalApi`` 加一件事：把每次提问与它的即时答案写进问答日志。

    做成子类而不是包装器，是因为只有 ``ask()`` 需要改——其余十几个方法原样继承，
    没有一处需要转发，也就没有"新增接口方法后忘了在包装器里补一遍"这种漂移。
    呈现端拿到的仍然是一个 ``ApiInterface``，界面与网关都不知道日志的存在。
    """

    def __init__(self, runtime: ApplicationRuntime, log: QuestionLog, *,
                 source: str = "pc") -> None:
        super().__init__(runtime)
        self._log = log
        self._source = source

    def ask(self, question: str) -> Answer:
        answer = super().ask(question)
        self._log.record_question(question, answer, source=self._source)
        return answer


def logging_answer_sink(
    log: QuestionLog, sink: AssistantAnswerSink | None
) -> AssistantAnswerSink:
    """把迟到的模型改写记进日志，再交给原来的去向。

    串在中间而不是替换：改写结果照样要送到界面与手机，日志只是顺路记一笔。
    """

    def deliver(text: str, source: str) -> None:
        log.record_late_answer(text, source)
        if sink is not None:
            sink(text, source)

    return deliver


def logging_question_observer(
    log: QuestionLog, observer: Callable[[str, Answer], None] | None
) -> Callable[[str, Answer], None]:
    """同上，用于手机那一路的提问观察者。

    ``run_api_server`` 此前**根本没有设置观察者**，手机在那个启动器下问的话无人看得见；
    接上日志时一并补上，否则三个启动器里又只有两个记得下来——
    这正是本模块开头说的那类漂移。
    """

    def observe(question: str, answer: Answer) -> None:
        log.record_question(question, answer, source="phone")
        if observer is not None:
            observer(question, answer)

    return observe


def attach_history(
    runtime: ApplicationRuntime, path: Path | str = DEFAULT_DATABASE_PATH
) -> HistoryStore:
    """Open the history database and start recording into it.

    Lives here, not in each launcher, for the reason this module exists:
    persisting in one launcher and forgetting the others would mean the
    phone-and-desktop demo (``run_all_界面加网关.bat``) silently kept no history
    while the desktop-only one did. That is the 2026-09-07 shape of bug
    exactly.

    Never raises. ``SqliteHistoryStore`` reports a failed open through its
    own counters rather than by throwing, so a read-only disk costs the
    history feature and nothing else -- acquisition, alarms, ventilation
    and the assistant all carry on.

    Returns the store so the launcher can ``close()`` it on the way out,
    next to where it already flushes the question log.
    """
    store = SqliteHistoryStore(path)
    runtime.attach_history(store)
    return store


def attach_language_model(
    runtime: ApplicationRuntime, model: str = DEFAULT_MODEL, enabled: bool = True
) -> tuple[bool, str]:
    """Probe the local model server once and attach it if it answers.

    Returns ``(available, detail)``; ``detail`` explains the "no" case so a
    launcher can put the reason on screen rather than only in a console
    line nobody reads. Never raises: a missing model server is an ordinary
    state, and the assistant answers from templates without one.

    Lives here rather than in each launcher for the same reason the
    automation wiring does -- doing it in one launcher and forgetting the
    others is a mistake this project has already made twice.
    """
    if not enabled:
        return False, "已用 --no-llm 关闭"
    client = OllamaClient(model=model)
    if not client.probe():
        return False, client.last_error or "无法连接本地模型服务"
    runtime.attach_language_model(client)
    return True, ""


def attach_export_status(
    runtime: ApplicationRuntime, path: Path | str = DEFAULT_DATABASE_PATH
) -> SqliteExportLedger:
    """Let the assistant see how many archived hours await upload.

    Lives here for the reason this whole module exists: wiring it into one
    launcher and forgetting the others is the 2026-09-07 shape of bug, and
    it is exactly what happened to the question log before 09-17.

    Read-only. The port it satisfies exposes a count and nothing else, so
    attaching it cannot give the assistant a way to upload anything --
    starting an upload stays with the desktop button (see
    :func:`make_cloud_sync_runner`).

    Never raises: the ledger reports a failed open through its own
    counters, and the adapter turns anything else into 0. Returns the
    ledger so a launcher can ``close()`` it alongside the history store.
    """
    ledger = SqliteExportLedger(path)
    runtime.attach_export_status(LedgerExportStatus(ledger))
    return ledger


def make_cloud_view_runner(
    on_message: Callable[[str], None],
) -> Callable[[], None]:
    """Build the callable behind the desktop's 「查看云端归档」 button.

    Only reads: ``cloud_view.py`` lists what is in the bucket and opens
    the console, it never uploads or deletes. It still goes through a
    button rather than being run by the assistant directly, and still
    lives here rather than in ``ui`` -- both for the same reason as the
    upload runner: **the line is who starts a subprocess**, not how risky
    the subprocess is.
    """
    return _make_script_runner(
        "cloud_view.py",
        started="已打开云端归档清单（只读），详见新开的控制台窗口",
        failed="启动云端查看脚本失败",
        on_message=on_message,
    )


def make_cloud_sync_runner(
    on_message: Callable[[str], None],
) -> Callable[[], None]:
    """Build the callable behind the desktop's 「导出并上传」 button.

    Launching the upload lives here, in the composition layer, and not in
    ``ui`` -- the view must not create or name a subprocess (``CLAUDE.md``
    架构原则). What the window receives is a plain callable.

    Runs ``scripts/cloud_sync.py --snapshot`` **in a subprocess**, the same
    entry ``cloud_snapshot_上传当前时段快照.bat`` double-clicks, rather than
    importing and calling its ``main()``: that script reads credentials,
    opens network connections and can take a while, none of which belongs
    on the Qt thread that is also drawing the chart. A crash in it costs an
    exit code, not the window.

    **Why the button carries ``--snapshot`` and the plain script does not**
    (2026-09-21): archives cover whole clock hours, and the hour in
    progress is deliberately never archived -- exporting half an hour and
    recording it in the ledger would lose the rest of it silently. So
    without the flag, "把现在的数据传上去" is impossible before the hour
    ends, and that is precisely what a demo asks for. ``--snapshot`` adds
    a clearly-named, ledger-free copy of the current hour on top of the
    normal catch-up. The flag stays opt-in on the command line so
    unattended use keeps the strict whole-hours behaviour; the two
    human-facing entries (this button and its ``.bat``) pass it, because a
    person clicking means "now".

    Detached on purpose -- this returns as soon as the child starts. The
    button reports that it started and the child's own console shows the
    rest; waiting here would freeze the UI for the length of an upload,
    which is the thing this design was trying to avoid.

    ``on_message`` puts one line in the activity log, so a click leaves a
    trace next to the alarms and the remote commands. Failing to start is
    reported the same way rather than raised: the user pressed a button in
    a chat panel, and an exception dialog is not what that should produce.
    """

    return _make_script_runner(
        "cloud_sync.py",
        args=("--snapshot",),
        started="已启动上云脚本（补齐已结束时段，并截一份当前时段快照），"
        "进度见新开的控制台窗口",
        failed="启动上云脚本失败",
        on_message=on_message,
    )


def _make_script_runner(
    script_name: str,
    *,
    args: tuple[str, ...] = (),
    started: str,
    failed: str,
    on_message: Callable[[str], None],
) -> Callable[[], None]:
    """两个按钮共用的那一段：拉起 ``scripts/<name>`` 并留一行活动日志。

    抽出来而不是复制一份，是因为这里的每一条约定都必须对两个按钮同时成立——
    子进程而非 import（脚本要读凭证、连公网，不该跑在画图表的 Qt 线程上）、
    不等它结束（等一次上传会把界面冻住，而那正是按钮方案要避开的）、
    启动失败只留一行日志不抛异常（用户按的是聊天面板里的一个按钮，
    不该因此弹出异常对话框）。复制一份就等于让这些约定有两个版本。
    """

    def run() -> None:
        script = _ROOT / "scripts" / script_name
        try:
            subprocess.Popen(  # noqa: S603 -- fixed path, no user input
                [sys.executable, str(script), *args],
                cwd=str(_ROOT),
            )
        except OSError as exc:
            on_message(f"{failed}：{exc}")
            return
        on_message(started)

    return run
