"""Tests for ui.widgets.device_panel.DevicePanelWidget -- no api/controller
involved."""

from __future__ import annotations

from ui.widgets.device_panel import DevicePanelWidget


def test_initial_labels_are_placeholders(qtbot) -> None:
    panel = DevicePanelWidget()
    qtbot.addWidget(panel)

    assert panel._device_id_label.text() == "-"
    assert panel._connection_label.text() == "-"
    assert panel._occupancy_label.text() == "-"


def test_set_status_connected_and_free(qtbot) -> None:
    panel = DevicePanelWidget()
    qtbot.addWidget(panel)

    panel.set_status("sim-1", True, False, "")

    assert panel._device_id_label.text() == "sim-1"
    assert panel._connection_label.text() == "已连接"
    assert panel._occupancy_label.text() == "空闲"


def test_set_status_disconnected_and_occupied(qtbot) -> None:
    panel = DevicePanelWidget()
    qtbot.addWidget(panel)

    panel.set_status("sim-1", False, True, "client-1")

    assert panel._connection_label.text() == "未连接"
    assert panel._occupancy_label.text() == "被 client-1 占用"


def test_clear_resets_to_placeholders(qtbot) -> None:
    panel = DevicePanelWidget()
    qtbot.addWidget(panel)
    panel.set_status("sim-1", True, True, "client-1")

    panel.clear()

    assert panel._device_id_label.text() == "-"
    assert panel._connection_label.text() == "-"
    assert panel._occupancy_label.text() == "-"


def test_capability_note_is_user_facing_not_internal_debug_text(qtbot) -> None:
    panel = DevicePanelWidget()
    qtbot.addWidget(panel)

    text = panel._capability_label.text()

    assert text == "未获取"
    for internal_name in ("ApiInterface", "DeviceStatusView", "View", "API"):
        assert internal_name not in text
