"""Tests for ui.widgets.device_list_item.DeviceListItemWidget -- no
api/controller involved."""

from __future__ import annotations

from ui.widgets.device_list_item import DeviceListItemWidget


def test_new_item_shows_device_id_and_unknown_status(qtbot) -> None:
    item = DeviceListItemWidget("mcu-1")
    qtbot.addWidget(item)

    assert item.device_id() == "mcu-1"
    assert item._connection_label.text() == "状态未知"


def test_set_status_connected_and_occupied(qtbot) -> None:
    item = DeviceListItemWidget("mcu-1")
    qtbot.addWidget(item)

    item.set_status(True, True, "client-1")

    assert item._connection_label.text() == "已连接"
    assert item._occupancy_label.text() == "被 client-1 占用"


def test_set_status_disconnected_and_free(qtbot) -> None:
    item = DeviceListItemWidget("mcu-1")
    qtbot.addWidget(item)

    item.set_status(False, False, "")

    assert item._connection_label.text() == "未连接"
    assert item._occupancy_label.text() == "空闲"


def test_set_selected_updates_property(qtbot) -> None:
    item = DeviceListItemWidget("mcu-1")
    qtbot.addWidget(item)

    item.set_selected(True)
    assert item.property("selected") == "true"

    item.set_selected(False)
    assert item.property("selected") == "false"
