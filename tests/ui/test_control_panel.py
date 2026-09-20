"""Tests for ui.widgets.control_panel.ControlPanelWidget -- no api/controller
involved."""

from __future__ import annotations

from PyQt6.QtCore import Qt

from ui.widgets.control_panel import ControlPanelWidget


def test_subscribe_button_emits_channel_text(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)
    panel._channel_input.setCurrentText("ch1")

    with qtbot.waitSignal(panel.subscribe_clicked, timeout=1000) as blocker:
        qtbot.mouseClick(panel._subscribe_button, Qt.MouseButton.LeftButton)

    assert blocker.args == ["ch1"]


def test_unsubscribe_button_emits_channel_text(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)
    panel._channel_input.setCurrentText("ch1")

    with qtbot.waitSignal(panel.unsubscribe_clicked, timeout=1000) as blocker:
        qtbot.mouseClick(panel._unsubscribe_button, Qt.MouseButton.LeftButton)

    assert blocker.args == ["ch1"]


def test_unsubscribe_button_does_not_emit_when_channel_empty(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)
    received: list[str] = []
    panel.unsubscribe_clicked.connect(received.append)

    qtbot.mouseClick(panel._unsubscribe_button, Qt.MouseButton.LeftButton)

    assert received == []


def test_channel_combo_is_editable_with_preset_suggestions(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)

    assert panel._channel_input.isEditable() is True
    combo = panel._channel_input
    presets = [combo.itemText(i) for i in range(combo.count())]
    assert presets == ["temperature", "humidity", "noise"]


def test_subscribe_button_emits_preset_selected_from_dropdown(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)
    index = panel._channel_input.findText("humidity")
    assert index != -1
    panel._channel_input.setCurrentIndex(index)

    with qtbot.waitSignal(panel.subscribe_clicked, timeout=1000) as blocker:
        qtbot.mouseClick(panel._subscribe_button, Qt.MouseButton.LeftButton)

    assert blocker.args == ["humidity"]


def test_subscribe_button_does_not_emit_when_channel_empty(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)
    received: list[str] = []
    panel.subscribe_clicked.connect(received.append)

    qtbot.mouseClick(panel._subscribe_button, Qt.MouseButton.LeftButton)

    assert received == []


def test_acquire_button_emits_acquire_clicked(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)
    with qtbot.waitSignal(panel.acquire_clicked, timeout=1000):
        qtbot.mouseClick(panel._acquire_button, Qt.MouseButton.LeftButton)


def test_release_button_emits_release_clicked(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)
    with qtbot.waitSignal(panel.release_clicked, timeout=1000):
        qtbot.mouseClick(panel._release_button, Qt.MouseButton.LeftButton)


def test_send_command_button_emits_default_ping(qtbot) -> None:
    """With no interaction at all, the combo defaults to PING and sending
    must emit the real "PING" command string."""
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)

    with qtbot.waitSignal(panel.send_command_clicked, timeout=1000) as blocker:
        qtbot.mouseClick(panel._send_command_button, Qt.MouseButton.LeftButton)

    assert blocker.args == ["PING"]


def test_send_command_button_does_not_emit_when_custom_is_empty(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)
    _select_command_type(panel, "CUSTOM（自定义命令）")
    received: list[str] = []
    panel.send_command_clicked.connect(received.append)

    qtbot.mouseClick(panel._send_command_button, Qt.MouseButton.LeftButton)

    assert received == []


# -- command type QComboBox ---------------------------------------------------


def _select_command_type(panel: ControlPanelWidget, display_text: str) -> None:
    index = panel._cmd_type_combo.findText(display_text)
    assert index != -1, f"display text not found in combo: {display_text!r}"
    panel._cmd_type_combo.setCurrentIndex(index)


def test_command_type_combo_exists_with_all_options(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)

    assert panel._cmd_type_combo.count() == 6
    expected = [
        ("PING（设备心跳）", "PING"),
        ("RESET（重启设备）", "RESET"),
        ("CONFIG_GET（读取配置）", "CONFIG_GET"),
        ("CONFIG_SET（设置配置）", "CONFIG_SET"),
        ("FW_UPDATE（固件升级）", "FW_UPDATE"),
        ("CUSTOM（自定义命令）", "CUSTOM"),
    ]
    actual = [
        (panel._cmd_type_combo.itemText(i), panel._cmd_type_combo.itemData(i))
        for i in range(panel._cmd_type_combo.count())
    ]
    assert actual == expected


def test_command_type_combo_defaults_to_ping(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)

    assert panel._cmd_type_combo.currentText() == "PING（设备心跳）"
    assert panel._cmd_type_combo.currentData() == "PING"


def test_custom_command_edit_disabled_by_default(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)

    assert panel._custom_command_edit.isEnabled() is False


def test_custom_command_edit_disabled_for_non_custom_selection(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)

    _select_command_type(panel, "RESET（重启设备）")

    assert panel._custom_command_edit.isEnabled() is False


def test_selecting_custom_enables_the_custom_command_edit(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)

    _select_command_type(panel, "CUSTOM（自定义命令）")

    assert panel._custom_command_edit.isEnabled() is True


def test_switching_away_from_custom_disables_and_clears_the_edit(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)
    _select_command_type(panel, "CUSTOM（自定义命令）")
    panel._custom_command_edit.setText("MY_CMD")

    _select_command_type(panel, "PING（设备心跳）")

    assert panel._custom_command_edit.isEnabled() is False
    assert panel._custom_command_edit.text() == ""


def test_sending_ping_emits_the_real_ping_string(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)
    _select_command_type(panel, "PING（设备心跳）")

    with qtbot.waitSignal(panel.send_command_clicked, timeout=1000) as blocker:
        qtbot.mouseClick(panel._send_command_button, Qt.MouseButton.LeftButton)

    assert blocker.args == ["PING"]


def test_sending_a_non_custom_selection_emits_its_command_data() -> None:
    panel = ControlPanelWidget()
    _select_command_type(panel, "FW_UPDATE（固件升级）")
    received: list[str] = []
    panel.send_command_clicked.connect(received.append)

    panel._send_command_button.click()

    assert received == ["FW_UPDATE"]


def test_sending_custom_emits_the_custom_edit_contents(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)
    _select_command_type(panel, "CUSTOM（自定义命令）")
    panel._custom_command_edit.setText("MY_CUSTOM_CMD")

    with qtbot.waitSignal(panel.send_command_clicked, timeout=1000) as blocker:
        qtbot.mouseClick(panel._send_command_button, Qt.MouseButton.LeftButton)

    assert blocker.args == ["MY_CUSTOM_CMD"]


def test_sending_custom_strips_surrounding_whitespace(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)
    _select_command_type(panel, "CUSTOM（自定义命令）")
    panel._custom_command_edit.setText("  MY_CMD  ")

    with qtbot.waitSignal(panel.send_command_clicked, timeout=1000) as blocker:
        qtbot.mouseClick(panel._send_command_button, Qt.MouseButton.LeftButton)

    assert blocker.args == ["MY_CMD"]


def test_custom_selection_ignores_leftover_non_custom_state() -> None:
    """Switching to a non-CUSTOM entry after CUSTOM must send that entry's
    own command data, not anything left over in the (now-cleared) custom edit."""
    panel = ControlPanelWidget()
    _select_command_type(panel, "CUSTOM（自定义命令）")
    panel._custom_command_edit.setText("LEFTOVER")
    _select_command_type(panel, "CONFIG_GET（读取配置）")
    received: list[str] = []
    panel.send_command_clicked.connect(received.append)

    panel._send_command_button.click()

    assert received == ["CONFIG_GET"]


def test_show_command_result_appends_to_log_with_message(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)

    panel.show_command_result("cmd-1", "SUCCESS", "")
    panel.show_command_result("cmd-2", "FAILED", "device did not accept it")

    assert panel.log_count() == 2
    assert panel._activity_log.item(0).text() == "命令 cmd-1：成功"
    assert (
        panel._activity_log.item(1).text()
        == "命令 cmd-2：失败（device did not accept it）"
    )


def test_show_control_result_reflects_acquired_and_failed(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)

    panel.show_control_result(True)
    panel.show_control_result(False)

    assert "获取控制权" in panel._activity_log.item(0).text()
    assert "失败" in panel._activity_log.item(1).text()


def test_show_error_appends_to_log(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)

    panel.show_error("device not found")

    assert panel._activity_log.item(0).text() == "错误：device not found"


def test_show_alarm_appends_a_red_log_entry(qtbot) -> None:
    from PyQt6.QtGui import QColor

    panel = ControlPanelWidget()
    qtbot.addWidget(panel)

    panel.show_alarm("mcu-1", "temperature", 36.5, 35.0, "ABOVE_MAX")

    assert panel.log_count() == 1
    item = panel._activity_log.item(0)
    assert "mcu-1/temperature" in item.text()
    assert "超过上限" in item.text()
    assert "36.50" in item.text()
    assert "35.00" in item.text()
    assert item.foreground().color() == QColor("red")


def test_show_alarm_below_min_uses_the_below_min_label(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)

    panel.show_alarm("mcu-1", "humidity", 20.0, 30.0, "BELOW_MIN")

    assert "低于下限" in panel._activity_log.item(0).text()


# -- 调试控制折叠（2026-09-07 新增）-------------------------------------------


def test_debug_controls_are_collapsed_by_default(qtbot) -> None:
    """演示中处于边缘地位的调试操作默认收起，功能保留但不占版面。"""
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)

    assert panel.controls_expanded() is False


def test_toggling_expands_and_collapses_the_debug_controls(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)

    panel._toggle_button.click()
    assert panel.controls_expanded() is True

    panel._toggle_button.click()
    assert panel.controls_expanded() is False


def test_set_controls_expanded_keeps_the_toggle_in_sync(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)

    panel.set_controls_expanded(True)

    assert panel.controls_expanded() is True
    assert panel._toggle_button.isChecked() is True


def test_collapsing_does_not_remove_any_control(qtbot) -> None:
    """折叠只是隐藏——F8（占用状态）/F9（控制指令下发）的界面证据必须仍然存在。"""
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)

    assert panel._acquire_button is not None
    assert panel._release_button is not None
    assert panel._send_command_button is not None
    assert panel._subscribe_button is not None


# -- channel options follow the selected device -------------------------------
#
# Before 2026-09-08 the combo always offered temperature/humidity/noise
# regardless of which device was selected. In Simulator mode each simulator
# is its own device with **one** channel, so two of every three choices
# subscribed to nothing: the call succeeded, the activity log said
# "已订阅", and no data ever arrived. Hardware mode hid it because there one
# device carries all three channels.


def test_set_channel_options_replaces_the_offered_list(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)

    panel.set_channel_options(["humidity"])

    assert panel.channel_options() == ["humidity"]


def test_a_single_channel_is_preselected(qtbot) -> None:
    """Making the only valid choice the default is what turns Simulator
    mode's one-channel-per-device layout from a trap into the obvious
    thing."""
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)

    panel.set_channel_options(["noise"])

    assert panel._channel_input.currentText() == "noise"


def test_several_channels_leave_the_choice_open(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)

    panel.set_channel_options(["temperature", "humidity", "noise"])

    assert panel.channel_options() == ["temperature", "humidity", "noise"]
    assert panel._channel_input.currentText() == ""


def test_a_still_valid_selection_survives_the_refresh(qtbot) -> None:
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)
    panel.set_channel_options(["temperature", "humidity"])
    panel._channel_input.setCurrentText("humidity")

    panel.set_channel_options(["humidity", "noise"])

    assert panel._channel_input.currentText() == "humidity"


def test_a_device_declaring_nothing_keeps_the_generic_presets(qtbot) -> None:
    """The platform fixes no channel-id enum, so an undeclared device must
    stay operable rather than end up with a blank control."""
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)

    panel.set_channel_options([])

    assert panel.channel_options() == ["temperature", "humidity", "noise"]


def test_the_combo_stays_editable(qtbot) -> None:
    """A device may report a channel it never declared."""
    panel = ControlPanelWidget()
    qtbot.addWidget(panel)
    panel.set_channel_options(["temperature"])

    assert panel._channel_input.isEditable()
