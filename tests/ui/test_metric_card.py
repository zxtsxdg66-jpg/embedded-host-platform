"""Tests for ui.widgets.metric_card.MetricCardWidget -- no api/controller
involved."""

from __future__ import annotations

from ui.widgets.metric_card import MetricCardWidget


def test_new_card_shows_placeholder_value(qtbot) -> None:
    card = MetricCardWidget("温度", "temperature", "°C")
    qtbot.addWidget(card)

    assert card.current_value() is None
    assert card._value_label.text() == "--"
    assert card.channel_id() == "temperature"


def test_update_value_sets_value_and_meta(qtbot) -> None:
    card = MetricCardWidget("温度", "temperature", "°C")
    qtbot.addWidget(card)

    card.update_value(26.4, "10:00:00")

    # 2026-09-18: 卡片改为与表格共用 channel_display 的按通道小数位（温度 2 位）。
    assert card._value_label.text() == "26.40"
    # 展示取整不改动持有的值——卡片记住的仍是原始读数。
    assert card.current_value() == 26.4
    assert "temperature" in card._meta_label.text()
    assert "10:00:00" in card._meta_label.text()


def test_trend_arrow_reflects_increase_then_decrease(qtbot) -> None:
    card = MetricCardWidget("温度", "temperature", "°C")
    qtbot.addWidget(card)

    card.update_value(20.0, "10:00:00")
    assert card._trend_label.text() == "—"  # first reading: no prior value

    card.update_value(25.0, "10:00:01")
    assert card._trend_label.text() == "↑"

    card.update_value(22.0, "10:00:02")
    assert card._trend_label.text() == "↓"

    card.update_value(22.0, "10:00:03")
    assert card._trend_label.text() == "—"


def test_set_alarm_state_updates_frame_state_property(qtbot) -> None:
    card = MetricCardWidget("噪声", "noise", "dB")
    qtbot.addWidget(card)

    card.set_alarm_state(True)
    assert card.property("state") == "alarm"

    card.set_alarm_state(False)
    assert card.property("state") == "normal"


def test_humidity_card_shows_no_decimals(qtbot) -> None:
    """卡片与表格用同一套按通道约定，湿度两处都取整。"""
    card = MetricCardWidget("湿度", "humidity", "%")
    qtbot.addWidget(card)

    card.update_value(56.27, "10:00:00")

    assert card._value_label.text() == "56"
    assert card.current_value() == 56.27


def test_an_unlisted_channel_card_is_not_reformatted(qtbot) -> None:
    """未登记通道不重新格式化，卡片与表格在这一点上也一致。"""
    card = MetricCardWidget("压力", "pressure", "kPa")
    qtbot.addWidget(card)

    card.update_value(101.3, "10:00:00")

    assert card._value_label.text() == "101.3"
