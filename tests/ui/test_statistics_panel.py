"""Tests for ui.widgets.statistics_panel.StatisticsPanelWidget -- no
api/controller involved."""

from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout

from ui.widgets.statistics_panel import StatisticsPanelWidget


def test_new_panel_has_no_cards(qtbot) -> None:
    panel = StatisticsPanelWidget()
    qtbot.addWidget(panel)

    assert panel.row_count() == 0


def test_update_statistics_creates_one_card(qtbot) -> None:
    panel = StatisticsPanelWidget()
    qtbot.addWidget(panel)

    panel.update_statistics("mcu-1", "temperature", 25.5, 20.0, 30.0, 25.0, 4)

    assert panel.row_count() == 1
    card = panel._cards[("mcu-1", "temperature")]
    assert "温度" in card._title_label.text()
    assert "mcu-1" in card._title_label.text()
    assert "25.50" in card._current_label.text()
    # 2026-08-18：极值与均值拆成两行且不再重复单位——单卡自然宽度原为 440 px，
    # 三张横排需 1356 px 而面板仅 584 px，必然横向滚动。拆行后可一屏装下。
    assert "20.00" in card._range_label.text()   # 最小
    assert "30.00" in card._range_label.text()   # 最大
    assert "25.00" in card._sample_label.text()  # 平均
    assert "4" in card._sample_label.text()      # 样本数


def test_repeated_updates_on_same_channel_update_the_same_card(qtbot) -> None:
    panel = StatisticsPanelWidget()
    qtbot.addWidget(panel)

    panel.update_statistics("mcu-1", "temperature", 20.0, 20.0, 20.0, 20.0, 1)
    panel.update_statistics("mcu-1", "temperature", 30.0, 20.0, 30.0, 25.0, 2)

    assert panel.row_count() == 1
    card = panel._cards[("mcu-1", "temperature")]
    assert "30.00" in card._current_label.text()
    assert "2" in card._sample_label.text()


def test_multi_channel_creates_independent_cards(qtbot) -> None:
    panel = StatisticsPanelWidget()
    qtbot.addWidget(panel)

    panel.update_statistics("mcu-1", "temperature", 25.0, 25.0, 25.0, 25.0, 1)
    panel.update_statistics("mcu-1", "humidity", 55.0, 55.0, 55.0, 55.0, 1)

    assert panel.row_count() == 2


def test_same_channel_different_devices_creates_independent_cards(qtbot) -> None:
    panel = StatisticsPanelWidget()
    qtbot.addWidget(panel)

    panel.update_statistics("mcu-1", "temperature", 25.0, 25.0, 25.0, 25.0, 1)
    panel.update_statistics("mcu-2", "temperature", 26.0, 26.0, 26.0, 26.0, 1)

    assert panel.row_count() == 2


def test_known_channel_shows_its_unit(qtbot) -> None:
    panel = StatisticsPanelWidget()
    qtbot.addWidget(panel)

    panel.update_statistics("mcu-1", "noise", 59.61, 40.23, 93.38, 55.66, 34)

    card = panel._cards[("mcu-1", "noise")]
    assert "dB" in card._current_label.text()


def test_unknown_channel_has_no_unit_suffix(qtbot) -> None:
    panel = StatisticsPanelWidget()
    qtbot.addWidget(panel)

    panel.update_statistics("mcu-1", "pressure", 1013.0, 1000.0, 1020.0, 1010.0, 2)

    card = panel._cards[("mcu-1", "pressure")]
    assert "1013.00" in card._current_label.text()


def test_cards_are_laid_out_side_by_side(qtbot) -> None:
    """2026-08-18: cards were stacked vertically inside a scroll area, so
    with three channels only two stayed visible -- the scroll area yields
    height while the control panel beside it demanded height. Laying them
    out horizontally makes all three fit in one row, matching the metric
    cards and chart panes above."""
    panel = StatisticsPanelWidget()
    qtbot.addWidget(panel)
    for channel in ("temperature", "humidity", "noise"):
        panel.update_statistics("mcu-1", channel, 1.0, 0.0, 2.0, 1.0, 3)

    assert isinstance(panel._cards_layout, QHBoxLayout)
    order = [
        panel._cards_layout.itemAt(i).widget()
        for i in range(panel._cards_layout.count())
    ]
    for channel in ("temperature", "humidity", "noise"):
        assert panel._cards[("mcu-1", channel)] in order
    assert panel.row_count() == 3


def test_panel_reserves_enough_height_for_a_full_row_of_cards(qtbot) -> None:
    """Same guarantee the realtime table already had: three channels must be
    fully visible without scrolling, not left to layout luck."""
    panel = StatisticsPanelWidget()
    qtbot.addWidget(panel)

    assert panel.minimumSizeHint().height() >= 150
