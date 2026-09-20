"""Tests for ui.controller.MainController.

Uses the real backend stack (ApplicationRuntime + LocalApi + SimulatorDevice
+ LoopbackChannel) rather than mocks, so these tests also exercise
SimulatorDevice as the data source through the full pipeline the way the
task requires -- ui.controller is only allowed to reach it via api.

All controller methods complete synchronously (see controller.py's
docstring), so signals are collected with plain list-appending slots
rather than qtbot.waitSignal's event-loop-driven waiting.
"""

from __future__ import annotations

from api.local_api import LocalApi
from application.runtime import ApplicationRuntime
from communication.loopback import LoopbackChannel
from device.simulator import ConstantValueGenerator, SimulatedChannel, SimulatorDevice
from ui.controller import MainController


def _make_controller(
    device_id: str = "sim-1",
    accepted_commands: tuple[str, ...] = ("PING",),
    value: object = 1,
) -> tuple[MainController, ApplicationRuntime]:
    runtime = ApplicationRuntime()
    device = SimulatorDevice(
        device_id=device_id,
        channels=[
            SimulatedChannel(channel_id="ch1", generator=ConstantValueGenerator(value))
        ],
    )
    runtime.register_device(
        device, LoopbackChannel(), accepted_commands=accepted_commands
    )
    controller = MainController(LocalApi(runtime), client_id="test-client")
    return controller, runtime


def _controller_with_history(value: object = 1):
    """挂了内存存储的 controller，用于历史相关用例。"""
    from service.history import InMemoryHistoryStore

    controller, runtime = _make_controller(value=value)
    runtime.attach_history(InMemoryHistoryStore())
    return controller, runtime


def test_load_history_emits_what_was_stored(qtbot) -> None:
    controller, runtime = _controller_with_history(value=25.5)
    received: list[tuple[str, str, list]] = []
    controller.history_loaded.connect(
        lambda d, c, p: received.append((d, c, p))
    )

    runtime.report_data("sim-1", "ch1")
    runtime.history_recorder.flush()
    controller.load_history("sim-1", "ch1")

    assert len(received) == 1
    device_id, channel, points = received[0]
    assert (device_id, channel) == ("sim-1", "ch1")
    assert [point.value for point in points] == [25.5]


def test_load_history_without_a_store_emits_an_empty_list(qtbot) -> None:
    """没挂存储时发空列表而不是报错：历史查不到不该挡住窗口打开。"""
    controller, _ = _make_controller()
    received: list[list] = []
    controller.history_loaded.connect(lambda d, c, p: received.append(p))

    controller.load_history("sim-1", "ch1")

    assert received == [[]]


def test_load_history_passes_the_limit_through(qtbot) -> None:
    controller, runtime = _controller_with_history()
    received: list[list] = []
    controller.history_loaded.connect(lambda d, c, p: received.append(p))

    for _ in range(5):
        runtime.report_data("sim-1", "ch1")
    runtime.history_recorder.flush()
    controller.load_history("sim-1", "ch1", limit=2)

    assert len(received[0]) == 2


def test_refresh_devices_emits_devices_changed(qtbot) -> None:
    controller, _ = _make_controller(device_id="sim-1")
    received: list[list[str]] = []
    controller.devices_changed.connect(received.append)

    controller.refresh_devices()

    assert received == [["sim-1"]]


def test_refresh_device_status_emits_status(qtbot) -> None:
    controller, _ = _make_controller()
    received: list[tuple[str, bool, bool, str]] = []
    controller.device_status_changed.connect(lambda *a: received.append(a))

    controller.refresh_device_status("sim-1")

    assert received == [("sim-1", True, False, "")]


def test_refresh_device_status_unknown_device_emits_error(qtbot) -> None:
    controller, _ = _make_controller()
    errors: list[str] = []
    controller.error_occurred.connect(errors.append)

    controller.refresh_device_status("unknown")

    assert len(errors) == 1


def test_subscribe_delivers_data_received_from_simulator_device(qtbot) -> None:
    controller, runtime = _make_controller(value=99)
    received: list[tuple[str, str, str]] = []
    controller.data_received.connect(lambda *a: received.append(a))

    controller.subscribe("sim-1", "ch1")
    runtime.report_data("sim-1", "ch1")

    assert received == [("sim-1", "ch1", "99")]


def test_unsubscribe_stops_delivery(qtbot) -> None:
    controller, runtime = _make_controller()
    received: list[tuple[str, str, str]] = []
    controller.data_received.connect(lambda *a: received.append(a))

    controller.subscribe("sim-1", "ch1")
    controller.unsubscribe("sim-1", "ch1")
    runtime.report_data("sim-1", "ch1")

    assert received == []


def test_acquire_control_emits_control_acquired_and_status(qtbot) -> None:
    controller, _ = _make_controller()
    acquired: list[tuple[str, bool]] = []
    statuses: list[tuple[str, bool, bool, str]] = []
    controller.control_acquired.connect(lambda *a: acquired.append(a))
    controller.device_status_changed.connect(lambda *a: statuses.append(a))

    controller.acquire_control("sim-1")

    assert acquired == [("sim-1", True)]
    assert statuses == [("sim-1", True, True, "test-client")]


def test_second_client_cannot_acquire_already_held_device(qtbot) -> None:
    controller, runtime = _make_controller()
    controller.acquire_control("sim-1")

    other = MainController(LocalApi(runtime), client_id="other-client")
    acquired: list[tuple[str, bool]] = []
    other.control_acquired.connect(lambda *a: acquired.append(a))

    other.acquire_control("sim-1")

    assert acquired == [("sim-1", False)]


def test_release_control_frees_device(qtbot) -> None:
    controller, _ = _make_controller()
    controller.acquire_control("sim-1")
    statuses: list[tuple[str, bool, bool, str]] = []
    controller.device_status_changed.connect(lambda *a: statuses.append(a))

    controller.release_control("sim-1")

    assert statuses == [("sim-1", True, False, "")]


def test_submit_command_success_emits_result(qtbot) -> None:
    controller, _ = _make_controller(accepted_commands=("PING",))
    controller.acquire_control("sim-1")
    results: list[tuple[str, str, str]] = []
    controller.command_result_ready.connect(lambda *a: results.append(a))

    controller.submit_command("sim-1", "PING")

    assert len(results) == 1
    _, status, message = results[0]
    assert status == "SUCCESS"
    assert message == ""


def test_submit_command_unaccepted_emits_failed_result(qtbot) -> None:
    controller, _ = _make_controller(accepted_commands=("PING",))
    controller.acquire_control("sim-1")
    results: list[tuple[str, str, str]] = []
    controller.command_result_ready.connect(lambda *a: results.append(a))

    controller.submit_command("sim-1", "UNKNOWN")

    assert len(results) == 1
    _, status, message = results[0]
    assert status == "FAILED"
    assert message


def test_submit_command_without_acquiring_emits_error(qtbot) -> None:
    controller, _ = _make_controller()
    errors: list[str] = []
    controller.error_occurred.connect(errors.append)

    controller.submit_command("sim-1", "PING")

    assert len(errors) == 1


# -- alarm status / statistics (global subscriptions set up in __init__) ------


def _make_temperature_controller(
    value: float, device_id: str = "sim-1"
) -> tuple[MainController, ApplicationRuntime]:
    runtime = ApplicationRuntime()
    device = SimulatorDevice(
        device_id=device_id,
        channels=[
            SimulatedChannel(
                channel_id="temperature", generator=ConstantValueGenerator(value)
            )
        ],
    )
    runtime.register_device(device, LoopbackChannel())
    controller = MainController(LocalApi(runtime), client_id="test-client")
    return controller, runtime


def test_alarm_status_changed_emitted_on_violation(qtbot) -> None:
    from service.sensor_data_processor import TEMPERATURE_ALARM_MAX

    controller, runtime = _make_temperature_controller(TEMPERATURE_ALARM_MAX + 5)
    received: list[tuple] = []
    controller.alarm_status_changed.connect(lambda *a: received.append(a))

    # 两次：2026-09-09 起报警需连续确认，一次越限只是嫌疑。
    runtime.report_data("sim-1", "temperature")
    runtime.report_data("sim-1", "temperature")

    assert len(received) == 2
    device_id, channel, value, threshold, kind, triggered = received[1]
    assert device_id == "sim-1"
    assert channel == "temperature"
    assert triggered is True
    assert kind == "ABOVE_MAX"
    assert threshold == TEMPERATURE_ALARM_MAX


def test_alarm_status_changed_emitted_with_triggered_false_for_normal_value(
    qtbot,
) -> None:
    controller, runtime = _make_temperature_controller(20.0)
    received: list[tuple] = []
    controller.alarm_status_changed.connect(lambda *a: received.append(a))

    runtime.report_data("sim-1", "temperature")

    assert len(received) == 1
    assert received[0][-1] is False


def test_statistics_changed_emitted_for_any_channel(qtbot) -> None:
    controller, runtime = _make_controller(value=7)
    received: list[tuple] = []
    controller.statistics_changed.connect(lambda *a: received.append(a))

    runtime.report_data("sim-1", "ch1")
    runtime.report_data("sim-1", "ch1")

    assert len(received) == 2
    device_id, channel, current, minimum, maximum, average, sample_count = received[-1]
    assert device_id == "sim-1"
    assert channel == "ch1"
    assert current == 7
    assert minimum == 7
    assert maximum == 7
    assert average == 7
    assert sample_count == 2

# -- ventilation settings changed elsewhere -----------------------------------


def test_a_fan_mode_set_elsewhere_reaches_the_view(qtbot) -> None:
    """The phone is the case this exists for: it asks the gateway to turn
    the fan on, which moves the same VentilationController the PC panel
    edits. Without this the PC kept showing 「自动」 beside a fan card
    already reading 「手动常开」."""
    from service.ventilation_controller import FanMode

    controller, runtime = _make_temperature_controller(21.0)
    controller.refresh_ventilation_settings()

    received: list[tuple] = []
    controller.ventilation_settings_changed.connect(lambda *a: received.append(a))

    # Stands in for the phone: something outside this screen moves the
    # setting, and the next reading is when the screen finds out.
    runtime.set_fan_mode(FanMode.MANUAL_ON)
    runtime.report_data("sim-1", "temperature")

    assert received[-1][2] == "MANUAL_ON"


def test_unchanged_settings_are_not_re_emitted(qtbot) -> None:
    """A reading arrives every cycle. Re-emitting each time would rewrite
    the spin-boxes under a user who is halfway through typing one."""
    controller, runtime = _make_temperature_controller(21.0)
    controller.refresh_ventilation_settings()

    received: list[tuple] = []
    controller.ventilation_settings_changed.connect(lambda *a: received.append(a))
    runtime.report_data("sim-1", "temperature")
    runtime.report_data("sim-1", "temperature")

    assert received == []


def test_a_remote_instruction_is_labelled_differently_from_a_question(qtbot) -> None:
    """手机提问只是上下文；手机下发的指令改变了本机的行为，
    而那正是有人回头追问"风扇怎么自己开了"时要找的那一行。"""
    controller, _ = _make_controller()
    seen: list[str] = []
    controller.remote_activity.connect(seen.append)

    controller.note_remote_question("现在噪声多少", "噪声 47.3dB。", applied=False)
    controller.note_remote_question(
        "把风扇打开", "已把风扇切到手动常开。", applied=True
    )

    assert "提问" in seen[0]
    assert "下发" in seen[1]
    assert "把风扇打开" in seen[1]


# -- 上云提议的动作标签（2026-09-18） -----------------------------------------


def test_the_view_tag_and_the_panel_agree() -> None:
    """把两端钉在一起。**第一版就是在这里错的**：控制器发的是意图枚举的值
    ``cloud_sync_hint``，而面板的处理器注册在 ``cloud_sync`` 下，
    标签送到了、匹配不上、答案底下什么都没有——全程没有任何报错。

    这条断言不测行为，测的是两个模块对同一个字符串的约定。"""
    from ui.controller import OFFER_TAGS
    from ui.widgets.assistant_panel import _ACTION_LABELS

    assert set(OFFER_TAGS.values()) <= set(_ACTION_LABELS)


def test_only_a_positive_pending_count_offers_the_button() -> None:
    """0 与 None 都不给按钮，各有各的理由：0 是"都传完了"，
    给了按钮等于说还有事可做；None 是"台账读不到"，
    而那句答话让用户自己去双击 bat——按钮会跟紧挨着的这句话打架。"""
    from service.assistant.models import (
        Answer,
        AnswerSource,
        Facts,
        Intent,
        IntentKind,
    )
    from ui.controller import _offer_tag

    def answer(pending: int | None) -> Answer:
        return Answer(
            text="",
            source=AnswerSource.TEMPLATE,
            intent=Intent(kind=IntentKind.CLOUD_SYNC_HINT),
            facts=Facts(kind=IntentKind.CLOUD_SYNC_HINT, pending_uploads=pending),
        )

    assert _offer_tag(answer(12)) == "cloud_sync"
    assert _offer_tag(answer(0)) == ""
    assert _offer_tag(answer(None)) == ""


def test_an_ordinary_answer_carries_no_tag() -> None:
    """默认必须是不给按钮：每一个进 OFFER_TAGS 的意图都等于开了一条
    通往程序之外的可点路径。"""
    from service.assistant.models import (
        Answer,
        AnswerSource,
        Facts,
        Intent,
        IntentKind,
    )
    from ui.controller import _offer_tag

    for kind in (IntentKind.CURRENT_VALUE, IntentKind.DELETE_REQUEST, IntentKind.HELP):
        reply = Answer(
            text="",
            source=AnswerSource.TEMPLATE,
            intent=Intent(kind=kind),
            facts=Facts(kind=kind),
        )
        assert _offer_tag(reply) == "", kind


def test_the_view_offer_needs_no_precondition() -> None:
    """上传要有待传时段才给按钮；查看没有这个前提——
    "云上什么都没有"本身也是一个值得看到的答案。"""
    from service.assistant.models import (
        Answer,
        AnswerSource,
        Facts,
        Intent,
        IntentKind,
    )
    from ui.controller import _offer_tag

    reply = Answer(
        text="",
        source=AnswerSource.TEMPLATE,
        intent=Intent(kind=IntentKind.CLOUD_VIEW_HINT),
        facts=Facts(kind=IntentKind.CLOUD_VIEW_HINT),
    )

    assert _offer_tag(reply) == "cloud_view"
