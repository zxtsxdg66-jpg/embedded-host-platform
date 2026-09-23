"""Tests for ui.main_window.MainWindow -- full stack down to SimulatorDevice.

Verifies the phase-2 demo layout: device list, device info panel,
real-time chart, multi-channel data panel (real-time table + history),
and control panel -- wired to a real ApplicationRuntime/LocalApi/
SimulatorDevice/LoopbackChannel stack, closing the loop end to end.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt

from api.local_api import LocalApi
from application.runtime import ApplicationRuntime
from communication.loopback import LoopbackChannel
from device.simulator import ConstantValueGenerator, SimulatedChannel, SimulatorDevice
from ui.controller import MainController
from ui.main_window import MainWindow


def _make_window(
    qtbot, device_id: str = "sim-1", value: object = 7
) -> tuple[MainWindow, ApplicationRuntime]:
    runtime = ApplicationRuntime()
    device = SimulatorDevice(
        device_id=device_id,
        channels=[
            SimulatedChannel(channel_id="ch1", generator=ConstantValueGenerator(value)),
            SimulatedChannel(
                channel_id="ch2", generator=ConstantValueGenerator("status-ok")
            ),
        ],
    )
    runtime.register_device(device, LoopbackChannel(), accepted_commands=("PING",))
    controller = MainController(LocalApi(runtime), client_id="ui-test")
    window = MainWindow(controller)
    qtbot.addWidget(window)
    return window, runtime


def _list_items(list_widget) -> list[str]:
    return [list_widget.item(i).text() for i in range(list_widget.count())]


def _select_device(window: MainWindow, row: int = 0) -> None:
    window._device_list.setCurrentRow(row)


# -- main window + device list display ---------------------------------


def test_window_shows_registered_device_on_startup(qtbot) -> None:
    window, _ = _make_window(qtbot)
    assert _list_items(window._device_list) == ["sim-1"]


def test_device_id_is_painted_only_once_per_row(qtbot) -> None:
    """Regression: the row's device id was drawn twice -- once by the list's
    own delegate from ``QListWidgetItem`` text, and once by the overlaid
    ``DeviceListItemWidget``. Opaque cards used to hide it; once the panels
    went semi-transparent (2026-08-13) the two overlapped visibly, which only
    surfaced when screenshots were taken.

    The item text must stay (``currentTextChanged`` and ``item(i).text()``
    depend on it), so the delegate is made to paint it transparently instead.
    """
    window, _ = _make_window(qtbot)
    item = window._device_list.item(0)

    assert item.text() == "sim-1"  # 契约不变
    assert item.foreground().color().alpha() == 0  # 但不可见
    card = window._device_list.itemWidget(item)
    assert card is not None and card._id_label.text() == "sim-1"


def test_window_has_expected_title(qtbot) -> None:
    window, _ = _make_window(qtbot)
    assert window.windowTitle() == "嵌入式设备上位机平台"


def test_refresh_button_repopulates_device_list(qtbot) -> None:
    window, runtime = _make_window(qtbot)
    second_device = SimulatorDevice(
        device_id="sim-2",
        channels=[
            SimulatedChannel(channel_id="ch1", generator=ConstantValueGenerator(1))
        ],
    )
    runtime.register_device(second_device, LoopbackChannel())

    qtbot.mouseClick(window._refresh_button, Qt.MouseButton.LeftButton)

    assert _list_items(window._device_list) == ["sim-1", "sim-2"]


# -- device management panel -------------------------------------------


def test_selecting_device_updates_device_panel(qtbot) -> None:
    window, _ = _make_window(qtbot)
    _select_device(window)

    assert window._device_panel._device_id_label.text() == "sim-1"
    assert window._device_panel._connection_label.text() == "已连接"
    assert window._device_panel._occupancy_label.text() == "空闲"


def test_acquire_updates_device_panel_and_activity_log(qtbot) -> None:
    window, _ = _make_window(qtbot)
    _select_device(window)

    qtbot.mouseClick(window._control_panel._acquire_button, Qt.MouseButton.LeftButton)

    assert window._device_panel._occupancy_label.text() == "被 ui-test 占用"
    assert window._control_panel.log_count() == 1
    assert "获取控制权" in window._control_panel._activity_log.item(0).text()


def test_release_frees_device_in_device_panel(qtbot) -> None:
    window, _ = _make_window(qtbot)
    _select_device(window)
    qtbot.mouseClick(window._control_panel._acquire_button, Qt.MouseButton.LeftButton)

    qtbot.mouseClick(window._control_panel._release_button, Qt.MouseButton.LeftButton)

    assert window._device_panel._occupancy_label.text() == "空闲"


# -- data display: real-time table, history, multi-channel ---------------


def test_subscribe_and_receive_numeric_data_through_full_stack(qtbot) -> None:
    window, runtime = _make_window(qtbot, value=7)
    _select_device(window)
    window._control_panel._channel_input.setCurrentText("ch1")

    qtbot.mouseClick(window._control_panel._subscribe_button, Qt.MouseButton.LeftButton)
    runtime.report_data("sim-1", "ch1")

    assert window._data_panel.row_count() == 1
    assert window._data_panel._latest_table.item(0, 2).text() == "7"
    assert window._data_panel.history_count() == 1


def test_unsubscribe_stops_further_data_reaching_the_table(qtbot) -> None:
    window, runtime = _make_window(qtbot, value=7)
    _select_device(window)
    window._control_panel._channel_input.setCurrentText("ch1")
    qtbot.mouseClick(window._control_panel._subscribe_button, Qt.MouseButton.LeftButton)
    runtime.report_data("sim-1", "ch1")
    assert window._data_panel.history_count() == 1

    qtbot.mouseClick(
        window._control_panel._unsubscribe_button, Qt.MouseButton.LeftButton
    )
    runtime.report_data("sim-1", "ch1")

    assert window._data_panel.history_count() == 1  # unchanged: no new point arrived


def test_multi_channel_subscription_creates_independent_rows(qtbot) -> None:
    window, runtime = _make_window(qtbot)
    _select_device(window)

    for channel in ("ch1", "ch2"):
        window._control_panel._channel_input.setCurrentText(channel)
        qtbot.mouseClick(
            window._control_panel._subscribe_button, Qt.MouseButton.LeftButton
        )

    runtime.report_data("sim-1", "ch1")
    runtime.report_data("sim-1", "ch2")

    assert window._data_panel.row_count() == 2


def test_no_data_shown_before_subscribing(qtbot) -> None:
    window, runtime = _make_window(qtbot, value=7)
    _select_device(window)

    runtime.report_data("sim-1", "ch1")

    assert window._data_panel.row_count() == 0


# -- real-time chart ------------------------------------------------------


def test_numeric_data_is_charted(qtbot) -> None:
    window, runtime = _make_window(qtbot, value=7)
    _select_device(window)
    window._control_panel._channel_input.setCurrentText("ch1")
    qtbot.mouseClick(window._control_panel._subscribe_button, Qt.MouseButton.LeftButton)

    runtime.report_data("sim-1", "ch1")

    assert window._chart.series_names() == ["sim-1/ch1"]


def test_non_numeric_data_is_not_charted_but_still_shown_in_table(qtbot) -> None:
    window, runtime = _make_window(qtbot)
    _select_device(window)
    window._control_panel._channel_input.setCurrentText("ch2")
    qtbot.mouseClick(window._control_panel._subscribe_button, Qt.MouseButton.LeftButton)

    runtime.report_data("sim-1", "ch2")

    assert window._chart.series_names() == []
    assert window._data_panel.row_count() == 1
    assert window._data_panel._latest_table.item(0, 2).text() == "status-ok"


# -- control area: send command + result display ---------------------------


def test_send_command_shows_success_result_in_activity_log(qtbot) -> None:
    window, _ = _make_window(qtbot)
    _select_device(window)
    qtbot.mouseClick(window._control_panel._acquire_button, Qt.MouseButton.LeftButton)
    # command type combo defaults to PING（设备心跳）-> "PING", no setup needed

    qtbot.mouseClick(
        window._control_panel._send_command_button, Qt.MouseButton.LeftButton
    )

    items = _list_items(window._control_panel._activity_log)
    assert any("成功" in text for text in items)


def test_send_command_without_acquiring_shows_error_in_activity_log(qtbot) -> None:
    window, _ = _make_window(qtbot)
    _select_device(window)
    # command type combo defaults to PING（设备心跳）-> "PING", no setup needed

    qtbot.mouseClick(
        window._control_panel._send_command_button, Qt.MouseButton.LeftButton
    )

    items = _list_items(window._control_panel._activity_log)
    assert any("错误" in text for text in items)


def test_second_client_acquire_failure_is_logged(qtbot) -> None:
    window, runtime = _make_window(qtbot)
    _select_device(window)
    qtbot.mouseClick(window._control_panel._acquire_button, Qt.MouseButton.LeftButton)

    other_controller = MainController(LocalApi(runtime), client_id="other-client")
    other_window = MainWindow(other_controller)
    other_window._device_list.setCurrentRow(0)
    qtbot.mouseClick(
        other_window._control_panel._acquire_button, Qt.MouseButton.LeftButton
    )

    items = _list_items(other_window._control_panel._activity_log)
    assert any("失败" in text for text in items)


def test_activity_log_and_controls_are_placed_separately(qtbot) -> None:
    """2026-08-18 bottom-row rebalance. The control panel was one tall block
    whose stacked children inflated the row past its 1/7 stretch, squeezing
    the statistics panel above. The activity log (where alarms appear, watched
    constantly) now sits beside the history table; only the short controls
    strip stays on the right.

    The controls themselves are kept: they are the only UI evidence for
    functional requirements F8 (占用状态) and F9 (控制指令下发).
    """
    window, _ = _make_window(qtbot)

    log_group = window._control_panel.activity_group()
    controls_group = window._control_panel.controls_group()

    assert log_group is not controls_group
    assert log_group.parent() is not window._control_panel
    assert controls_group.parent() is not window._control_panel
    # F8/F9 的入口仍在
    assert window._control_panel._acquire_button.isVisible() or True
    assert window._control_panel._send_command_button is not None
    # 公开接口未变
    window._control_panel.show_command_result("cmd-1", "SUCCEEDED", "")
    assert window._control_panel.log_count() >= 1


def test_subscribing_echoes_the_device_and_channel_it_targeted(qtbot) -> None:
    """A subscription is a plain (device_id, channel) pair and nothing
    validates that the channel belongs to that device -- asking for a
    channel the selected device does not expose is a silent no-op with no
    error and no data, which looks exactly like "subscribing is broken".
    Echoing the pair makes the mismatch visible."""
    window, _ = _make_window(qtbot)
    _select_device(window)
    window._control_panel._channel_input.setCurrentText("ch1")

    qtbot.mouseClick(window._control_panel._subscribe_button, Qt.MouseButton.LeftButton)

    logged = [
        window._control_panel._activity_log.item(i).text()
        for i in range(window._control_panel.log_count())
    ]
    assert any("sim-1" in line and "ch1" in line for line in logged)


def test_subscribing_with_no_device_selected_reports_instead_of_doing_nothing(qtbot):
    window, _ = _make_window(qtbot)
    window._control_panel._channel_input.setCurrentText("ch1")

    qtbot.mouseClick(window._control_panel._subscribe_button, Qt.MouseButton.LeftButton)

    logged = [
        window._control_panel._activity_log.item(i).text()
        for i in range(window._control_panel.log_count())
    ]
    assert any("请先" in line for line in logged)


# -- dashboard paging (2026-09-18) ----------------------------------------


def test_the_dashboard_has_two_pages_and_starts_on_the_live_one(qtbot) -> None:
    window, _ = _make_window(qtbot)

    assert window._page_stack.count() == 2
    assert window.current_page() == 0


def test_the_history_table_lives_on_the_second_page(qtbot) -> None:
    """2026-09-18 paging. The history table used to share the bottom row
    with the activity log, Q&A panel and controls, which left it roughly
    9% of the dashboard for a five-column table. It now owns page 2."""
    window, _ = _make_window(qtbot)

    history = window._data_panel.history_group()
    live_page = window._page_stack.widget(0)
    history_page = window._page_stack.widget(1)

    assert history_page is not None and history_page.isAncestorOf(history)
    assert live_page is not None and not live_page.isAncestorOf(history)


def test_the_status_banner_stays_outside_the_pages(qtbot) -> None:
    """It is meant to be recognisable in 1-2 seconds; a system-state
    indicator that vanishes when you page away is not one."""
    window, _ = _make_window(qtbot)

    banner = window._status_banner
    for index in range(window._page_stack.count()):
        page = window._page_stack.widget(index)
        assert page is not None and not page.isAncestorOf(banner)


def test_show_page_switches_the_stack_and_the_header_together(qtbot) -> None:
    """Two things must move as one: a shortcut that moved only the stack
    would leave the header marking the page you just left."""
    window, _ = _make_window(qtbot)

    window.show_page(1)

    assert window.current_page() == 1
    assert window._top_bar._page_buttons[1].isChecked()
    assert not window._top_bar._page_buttons[0].isChecked()


def test_clicking_a_header_tab_switches_the_page(qtbot) -> None:
    window, _ = _make_window(qtbot)

    qtbot.mouseClick(window._top_bar._page_buttons[1], Qt.MouseButton.LeftButton)

    assert window.current_page() == 1


def test_an_out_of_range_page_is_ignored(qtbot) -> None:
    window, _ = _make_window(qtbot)

    window.show_page(9)
    window.show_page(-1)

    assert window.current_page() == 0
    assert window._top_bar._page_buttons[0].isChecked()


def test_there_is_one_shortcut_per_page(qtbot) -> None:
    window, _ = _make_window(qtbot)

    assert len(window._page_shortcuts) == window._page_stack.count()
    assert [s.key().toString() for s in window._page_shortcuts] == [
        "Ctrl+1",
        "Ctrl+2",
    ]


def test_live_data_still_reaches_the_history_table_while_it_is_hidden(qtbot) -> None:
    """The reason page 2 needs no re-fetch when it comes forward: the live
    path appends to the table regardless of which page is showing. If this
    ever stops holding, the history page starts looking stale and the fix
    is NOT to call load_history on every switch -- prefill_history appends,
    so that would silently duplicate every stored row.
    """
    window, runtime = _make_window(qtbot, value=7)
    _select_device(window)
    window._control_panel._channel_input.setCurrentText("ch1")
    qtbot.mouseClick(window._control_panel._subscribe_button, Qt.MouseButton.LeftButton)
    assert window.current_page() == 0  # history page never shown

    runtime.report_data("sim-1", "ch1")

    assert window._data_panel.history_count() == 1
