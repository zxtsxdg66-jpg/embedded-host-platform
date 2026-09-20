"""Tests for ui.widgets.fan_card.FanCardWidget -- no api/controller involved."""

from __future__ import annotations

from ui.widgets.fan_card import FanCardWidget


def test_new_card_shows_stopped_placeholder(qtbot) -> None:
    card = FanCardWidget()
    qtbot.addWidget(card)

    assert card.is_running() is False
    assert card.state_text() == "已停止"
    assert card.reason_text() == "尚无数据"


def test_set_decision_running_updates_all_three_fields(qtbot) -> None:
    card = FanCardWidget()
    qtbot.addWidget(card)

    card.set_decision(True, "温度 31.2℃ 高于通风阈值 30℃", "自动")

    assert card.is_running() is True
    assert card.state_text() == "运行中"
    assert card.reason_text() == "温度 31.2℃ 高于通风阈值 30℃"
    assert card.mode_text() == "自动"


def test_set_decision_stopped_returns_to_stopped_text(qtbot) -> None:
    card = FanCardWidget()
    qtbot.addWidget(card)

    card.set_decision(True, "运行原因", "自动")
    card.set_decision(False, "温湿度均在通风阈值以内", "自动")

    assert card.is_running() is False
    assert card.state_text() == "已停止"


def test_running_uses_its_own_state_not_the_alarm_state(qtbot) -> None:
    """A fan doing its job is not a fault; reusing the alarm state would
    paint it in the danger colour and mislead (see ui/theme.py)."""
    card = FanCardWidget()
    qtbot.addWidget(card)

    card.set_decision(True, "原因", "自动")
    assert card.property("state") == "running"

    card.set_decision(False, "原因", "自动")
    assert card.property("state") == "normal"


def test_card_styles_as_a_metric_card(qtbot) -> None:
    """Shares the metric row with the three sensor cards, so it must pick
    up the same QSS rules."""
    card = FanCardWidget()
    qtbot.addWidget(card)

    assert card.objectName() == "metricCard"


def test_manual_mode_label_is_displayed_verbatim(qtbot) -> None:
    card = FanCardWidget()
    qtbot.addWidget(card)

    card.set_decision(True, "手动开启", "常开")

    assert card.mode_text() == "常开"
