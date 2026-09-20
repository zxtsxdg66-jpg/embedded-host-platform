"""Tests for ui.widgets.status_banner.StatusBannerWidget -- no
api/controller involved."""

from __future__ import annotations

from ui.widgets.status_banner import StatusBannerWidget


def test_new_banner_is_normal(qtbot) -> None:
    banner = StatusBannerWidget()
    qtbot.addWidget(banner)

    assert banner.current_state() == "normal"
    assert banner.message() == "系统正常"


def test_set_alarm_true_switches_to_alarm_state(qtbot) -> None:
    banner = StatusBannerWidget()
    qtbot.addWidget(banner)

    banner.set_alarm("mcu-1", "noise", "噪声超过上限", True)

    assert banner.current_state() == "alarm"
    assert "噪声超过上限" in banner.message()


def test_clearing_the_only_alarm_returns_to_normal(qtbot) -> None:
    banner = StatusBannerWidget()
    qtbot.addWidget(banner)
    banner.set_alarm("mcu-1", "noise", "噪声超过上限", True)

    banner.set_alarm("mcu-1", "noise", "噪声超过上限", False)

    assert banner.current_state() == "normal"


def test_multiple_alarms_all_appear_in_the_message(qtbot) -> None:
    banner = StatusBannerWidget()
    qtbot.addWidget(banner)

    banner.set_alarm("mcu-1", "noise", "噪声超过上限", True)
    banner.set_alarm("mcu-1", "temperature", "温度偏高", True)

    assert banner.current_state() == "alarm"
    assert "噪声超过上限" in banner.message()
    assert "温度偏高" in banner.message()


def test_warning_shown_when_no_alarm_is_active(qtbot) -> None:
    banner = StatusBannerWidget()
    qtbot.addWidget(banner)

    banner.show_warning("设备未找到")

    assert banner.current_state() == "warning"
    assert "设备未找到" in banner.message()


def test_alarm_takes_priority_over_pending_warning(qtbot) -> None:
    banner = StatusBannerWidget()
    qtbot.addWidget(banner)
    banner.show_warning("设备未找到")

    banner.set_alarm("mcu-1", "noise", "噪声超过上限", True)

    assert banner.current_state() == "alarm"


def test_clear_warning_returns_to_normal(qtbot) -> None:
    banner = StatusBannerWidget()
    qtbot.addWidget(banner)
    banner.show_warning("设备未找到")

    banner.clear_warning()

    assert banner.current_state() == "normal"
