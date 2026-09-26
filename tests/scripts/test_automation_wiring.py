"""Every launcher must wire the device automations identically.

These tests exist because of a real defect: when ventilation, spoken
alarms and the board's alarm-state display were added on 2026-09-07, only
``scripts/run_gui.py`` was wired. ``run_api_server_手机网关.bat`` and
``run_all_界面加网关.bat`` silently ran without any of them --
and that launcher
is
the mode used to demonstrate the phone and the desktop together. Nothing
raised; the fan simply never turned on.

So these are not tests of ``automation_wiring``'s internals. They are
tests that no launcher has drifted away from it, which is the failure
mode that actually occurred.
"""

from __future__ import annotations

from application.alarm_state_dispatcher import ALARM_STATE_COMMAND
from application.answer_dispatcher import ANSWER_SHOW_COMMAND
from application.fan_dispatcher import (
    DEFAULT_FAN_OFF_COMMAND,
    DEFAULT_FAN_ON_COMMAND,
)
from scripts import run_api_server, run_gui
from scripts.automation_wiring import (
    ACCEPTED_COMMANDS,
    AUTOMATION_COMMANDS,
    attach_language_model,
    dispatch_automations,
    enable_automations,
    make_poll_once,
)
from service.alarm_announcer import AlertKind
from service.ventilation_controller import FanDecision, FanMode

_BUILDERS = (
    ("run_gui", run_gui.build_simulator_runtime),
    ("run_api_server", run_api_server.build_simulator_runtime),
)


# -- every launcher installs all three dispatchers ----------------------------


def test_every_simulator_builder_installs_all_three_dispatchers() -> None:
    for name, build in _BUILDERS:
        runtime = build()[0]
        assert runtime.fan_dispatcher is not None, f"{name}: no fan dispatcher"
        assert runtime.alert_dispatcher is not None, f"{name}: no alert dispatcher"
        assert runtime.alarm_state_dispatcher is not None, (
            f"{name}: no alarm-state dispatcher"
        )


def test_every_launcher_uses_the_shared_accepted_command_set() -> None:
    """A device that does not list a command rejects it before the wire.

    ``run_api_server`` used to register devices with ``("PING",)`` only, so
    even a dispatched FAN_ON would have been refused by DeviceManager's
    simulated-ack path.
    """
    assert run_gui._ACCEPTED_COMMANDS == ACCEPTED_COMMANDS


# -- the command set actually covers what the dispatchers send ---------------


def test_accepted_commands_cover_every_automation_command() -> None:
    expected = {
        DEFAULT_FAN_ON_COMMAND,
        DEFAULT_FAN_OFF_COMMAND,
        ALARM_STATE_COMMAND,
        ANSWER_SHOW_COMMAND,
        *(kind.value for kind in AlertKind),
    }
    assert expected <= set(AUTOMATION_COMMANDS)
    assert expected <= set(ACCEPTED_COMMANDS)


def test_ping_is_still_accepted() -> None:
    """The manual control panel and the Android client both use it."""
    assert "PING" in ACCEPTED_COMMANDS


# -- the poll callable actually dispatches -----------------------------------


class _CountingRunner:
    def __init__(self) -> None:
        self.run_count = 0

    def run_once(self) -> None:
        self.run_count += 1


def test_make_poll_once_runs_the_runner_then_dispatches() -> None:
    """The ordering matters: data has to move up before the automations
    can act on it, and the send must happen here rather than inside the
    data callback (see application/fan_dispatcher.py)."""
    runtime = run_gui.build_simulator_runtime()[0]
    runner = _CountingRunner()
    fan = runtime.fan_dispatcher
    assert fan is not None

    poll_once = make_poll_once(runtime, runner)
    fan.handle_decision(
        FanDecision(should_run=True, reason="test", mode=FanMode.AUTO)
    )
    assert fan.applied_state is False  # nothing sent yet

    poll_once()

    assert runner.run_count == 1
    assert fan.applied_state is True


def test_dispatch_automations_is_safe_before_anything_is_enabled() -> None:
    """A launcher that never calls enable_automations must not crash."""
    from application.runtime import ApplicationRuntime

    dispatch_automations(ApplicationRuntime())  # must not raise


def test_enable_automations_is_idempotent_enough_to_recall() -> None:
    """Calling it twice replaces the dispatchers rather than doubling them."""
    from application.runtime import ApplicationRuntime

    runtime = ApplicationRuntime()
    enable_automations(runtime, "dev-1")
    first = runtime.fan_dispatcher
    enable_automations(runtime, "dev-1")

    assert runtime.fan_dispatcher is not first
    assert runtime.fan_dispatcher is not None


# -- the language model is wired the same way everywhere ----------------------


def test_attach_is_skipped_when_disabled() -> None:
    from application.runtime import ApplicationRuntime
    from service.assistant.llm_port import NullLlmClient

    runtime = ApplicationRuntime()
    available, detail = attach_language_model(runtime, enabled=False)

    assert available is False
    assert "--no-llm" in detail
    assert isinstance(runtime.assistant.llm, NullLlmClient)


def test_attach_reports_why_it_failed_rather_than_raising() -> None:
    """A missing model server is an ordinary state. The reason is returned
    so a launcher can show it on screen -- without it, "no model" and
    "model silently failing" look identical: every answer stays 「系统」."""
    from application.runtime import ApplicationRuntime
    from service.assistant.llm_port import NullLlmClient

    runtime = ApplicationRuntime()
    # Port 1 is reserved and never listening.
    available, detail = attach_language_model(runtime, model="none")
    if available:  # a real Ollama is running on this machine
        return
    assert detail
    assert isinstance(runtime.assistant.llm, NullLlmClient)


# ⚠ 下面这几条用 ``inspect.getsource()`` 只检查**源码文本**里有没有某些符号，
# **不验证启动器能不能真的跑起来**。2026-09-17 吃过亏：`automation_wiring` 里一行
# `from scripts.question_log import ...` 让四个启动器全部 ModuleNotFoundError，
# 而这些守卫照样全绿（pytest 以包路径导入，项目根天然在 sys.path 上，恰好绕开）。
# 真正能拦住那类问题的是 ``test_launchers_actually_start.py``——它用子进程真跑入口。
# 两者互补：这里守"接线有没有漏"，那里守"接上了能不能起来"。


def test_every_gui_launcher_wires_the_assistant() -> None:
    """run_all.py once drove runner.run_once() directly and never touched
    the automations; the same drift left it without a model client too."""
    import inspect

    from scripts import run_all

    source = inspect.getsource(run_all)
    assert "attach_language_model" in source
    assert "deliver_assistant_answer" in source
    assert "set_assistant_model_status" in source

    source = inspect.getsource(run_gui)
    assert "attach_language_model" in source
    assert "deliver_assistant_answer" in source
    assert "set_assistant_model_status" in source


def test_every_gateway_launcher_pushes_assistant_answers_to_phones() -> None:
    """The gateway launchers must feed the WebSocket sink too. Without it a
    phone gets the template answer from REST and never the model's later,
    better one -- a silent half-feature, which is the failure mode this
    module exists to catch.

    run_api_server additionally has to attach the model at all: it is the
    headless launcher, and nothing else in it would have done so.
    """
    import inspect

    from scripts import run_all

    source = inspect.getsource(run_api_server)
    assert "assistant_sink" in source
    assert "attach_language_model" in source

    source = inspect.getsource(run_all)
    assert "assistant_sink" in source


def test_every_dispatcher_the_wiring_installs_is_also_flushed() -> None:
    """Installing a dispatcher and forgetting to drive it is a silent
    half-feature: it records what to show and never sends it. The answer
    display was added this way and only the end-to-end run caught it --
    its command was missing from ACCEPTED_COMMANDS, so every frame was
    rejected before reaching the wire while nothing logged a word."""
    from application.runtime import ApplicationRuntime
    from communication.loopback import LoopbackChannel
    from device.simulator import (
        ConstantValueGenerator,
        SimulatedChannel,
        SimulatorDevice,
    )

    runtime = ApplicationRuntime()
    device = SimulatorDevice(
        device_id="sim-1",
        channels=[
            SimulatedChannel(channel_id="temperature",
                             generator=ConstantValueGenerator(21.0))
        ],
    )
    runtime.register_device(
        device, LoopbackChannel(), accepted_commands=ACCEPTED_COMMANDS
    )
    enable_automations(runtime, "sim-1")

    assert runtime.fan_dispatcher is not None
    assert runtime.alert_dispatcher is not None
    assert runtime.alarm_state_dispatcher is not None
    assert runtime.answer_dispatcher is not None

    # Asked end to end rather than by inspecting command names: what broke
    # was the device rejecting the command, which no name comparison sees.
    runtime.report_data("sim-1", "temperature")
    runtime.ask("现在温度多少")
    dispatch_automations(runtime)

    assert runtime.answer_dispatcher.dispatch_count == 1
    assert runtime.answer_dispatcher.failure_count == 0


# -- 历史记录也必须三个启动器一起接 ---------------------------------------------


def test_every_launcher_records_history() -> None:
    """三个启动器都要接上历史存储，且都要在退出前落盘关库。

    与本模块开头那段说的是同一件事：09-07 的自动通风、09-08 的模型，
    都是只接了一个启动器。历史记录更难发现——不接的那个照常显示、
    照常报警、照常问答，只是什么都没留下，而"没留下"要等下次想查
    才看得出来。所以这条守卫和模型那两条一样，直接读源码断言符号。

    `service.history.NullHistoryStore` 的文档注释点名了本用例：
    默认不存的宽容设计，正是靠这里兜住"忘了接"。
    """
    import inspect

    from scripts import run_all

    for module in (run_gui, run_all, run_api_server):
        source = inspect.getsource(module)
        assert "attach_history" in source, module.__name__
        assert "history_recorder.flush()" in source, module.__name__
        assert "history_store.close()" in source, module.__name__


def test_the_poll_loop_persists_before_its_early_return() -> None:
    """`make_poll_once` 里落盘必须在 `on_assistant_answer` 的提前 return 之前。

    run_api_server 那条路径不传界面回调，若把 flush 放在 return 之后，
    就会变成"界面模式记得下来、网关模式记不下来"——同一种漂移换个位置。
    """
    import inspect

    source = inspect.getsource(make_poll_once)
    flush_at = source.index("history_recorder.flush_if_due()")
    # 2026-09-26 起提前 return 的条件多了 on_assistant_steps，写成了多行括号；
    # 这里只找条件的第一项，断言的顺序关系不变。
    return_at = source.index("on_assistant_answer is None")
    assert flush_at < return_at


def test_attaching_history_starts_recording_published_readings(tmp_path) -> None:
    """接上之后，已注册设备的读数要真的进库。

    覆盖 attach_history() 里"为既有设备补订阅"那一段：存储是在设备
    注册之后才挂上的，若只给将来注册的设备订阅，模拟模式下三个设备
    全部先于它注册，结果就是一条也记不到。
    """
    from application.runtime import ApplicationRuntime
    from communication.loopback import LoopbackChannel
    from device.simulator import (
        ConstantValueGenerator,
        SimulatedChannel,
        SimulatorDevice,
    )
    from scripts.automation_wiring import attach_history as wire_history

    runtime = ApplicationRuntime()
    runtime.register_device(
        SimulatorDevice(
            device_id="sim-1",
            channels=[
                SimulatedChannel(channel_id="temperature",
                                 generator=ConstantValueGenerator(21.0))
            ],
        ),
        LoopbackChannel(),
        accepted_commands=ACCEPTED_COMMANDS,
    )

    store = wire_history(runtime, tmp_path / "history.sqlite")
    runtime.report_data("sim-1", "temperature")
    runtime.history_recorder.flush()

    assert [point.value for point in runtime.query_history("sim-1", "temperature")] == [
        21.0
    ]
    assert store.count() == 1
    store.close()


def test_the_poll_loop_forwards_answering_steps_every_cycle() -> None:
    """步骤要每轮都送出，而不是等模型结果回来才送（2026-09-26）。

    ask() 在网关的请求线程上记下步骤；若只在 poll_assistant 有结果时才取，
    不接模型时这些步骤就永远不会离开日志。
    """
    runtime = run_gui.build_simulator_runtime()[0]
    received: list[object] = []
    poll_once = make_poll_once(
        runtime, _CountingRunner(), on_assistant_steps=received.extend
    )
    runtime.ask("现在温度多少")
    poll_once()
    kinds = [step.kind.value for step in received]  # type: ignore[attr-defined]
    assert kinds[0] == "received"
    assert kinds[-1] == "answered"
    poll_once()
    assert len(received) == len(kinds)  # drained once, not resent


def test_every_gateway_launcher_pushes_answering_steps() -> None:
    """两个带网关的启动器都要接步骤推送，否则网页的实时流程在那种模式下安静地不亮。"""
    import inspect

    from scripts import run_all

    for module in (run_api_server, run_all):
        assert "assistant_steps_sink" in inspect.getsource(module), module.__name__
