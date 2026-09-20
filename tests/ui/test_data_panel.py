"""Tests for ui.widgets.data_panel.DataPanelWidget -- no api/controller
involved."""

from __future__ import annotations

from ui.widgets.data_panel import DataPanelWidget


def test_new_panel_has_no_rows_or_history(qtbot) -> None:
    panel = DataPanelWidget()
    qtbot.addWidget(panel)

    assert panel.row_count() == 0
    assert panel.history_count() == 0


def test_add_data_point_creates_one_row(qtbot) -> None:
    panel = DataPanelWidget()
    qtbot.addWidget(panel)

    panel.add_data_point("sim-1", "ch1", "42")

    assert panel.row_count() == 1
    assert panel._latest_table.item(0, 0).text() == "sim-1"
    assert panel._latest_table.item(0, 1).text() == "ch1"
    assert panel._latest_table.item(0, 2).text() == "42"


def test_repeated_points_on_same_channel_update_row_in_place(qtbot) -> None:
    panel = DataPanelWidget()
    qtbot.addWidget(panel)

    panel.add_data_point("sim-1", "ch1", "1")
    panel.add_data_point("sim-1", "ch1", "2")
    panel.add_data_point("sim-1", "ch1", "3")

    assert panel.row_count() == 1
    assert panel._latest_table.item(0, 2).text() == "3"


def test_multi_channel_creates_independent_rows(qtbot) -> None:
    panel = DataPanelWidget()
    qtbot.addWidget(panel)

    panel.add_data_point("sim-1", "ch1", "1")
    panel.add_data_point("sim-1", "ch2", "2")

    assert panel.row_count() == 2


def test_same_channel_different_devices_creates_independent_rows(qtbot) -> None:
    panel = DataPanelWidget()
    qtbot.addWidget(panel)

    panel.add_data_point("sim-1", "ch1", "1")
    panel.add_data_point("sim-2", "ch1", "2")

    assert panel.row_count() == 2


def test_history_grows_with_every_point_even_repeats(qtbot) -> None:
    panel = DataPanelWidget()
    qtbot.addWidget(panel)

    panel.add_data_point("sim-1", "ch1", "1")
    panel.add_data_point("sim-1", "ch1", "2")

    assert panel.history_count() == 2


def test_history_is_capped_at_configured_limit(qtbot) -> None:
    panel = DataPanelWidget(history_limit=3)
    qtbot.addWidget(panel)

    for value in range(10):
        panel.add_data_point("sim-1", "ch1", str(value))

    assert panel.history_count() == 3
    # 2026-09-18: 上限现在是每条通道各算各的，这里只有 ch1 一条通道，
    # 所以总数仍是 3。设备与通道不再是列——通道是这一列本身，设备写在列标题上。
    assert panel.history_count_for("ch1") == 3
    table = panel._history_tables["ch1"]
    # oldest entries are dropped, newest survive
    assert table.item(2, 1).text() == "9"
    assert panel._history_titles["ch1"].title().endswith("sim-1")


def test_set_alarm_active_highlights_the_row_red(qtbot) -> None:
    from PyQt6.QtGui import QColor

    panel = DataPanelWidget()
    qtbot.addWidget(panel)
    panel.add_data_point("sim-1", "temperature", "36.5")

    panel.set_alarm("sim-1", "temperature", True)

    item = panel._latest_table.item(0, 2)
    assert item.background().color() == QColor("red")
    assert item.foreground().color() == QColor("white")


def test_set_alarm_inactive_clears_the_highlight(qtbot) -> None:
    from PyQt6.QtGui import QBrush

    panel = DataPanelWidget()
    qtbot.addWidget(panel)
    panel.add_data_point("sim-1", "temperature", "36.5")
    panel.set_alarm("sim-1", "temperature", True)

    panel.set_alarm("sim-1", "temperature", False)

    item = panel._latest_table.item(0, 2)
    assert item.background() == QBrush()
    assert item.foreground() == QBrush()


def _stored(second: int, value: float = 25.5, valid: bool = True):
    """一条已存的读数。用真实类型，避免与平台的字段名漂移。"""
    from datetime import datetime, timezone

    from service.history import HistoryPoint

    return HistoryPoint(
        device_id="sim-1",
        channel="ch1",
        value=value,
        timestamp=datetime(2026, 9, 17, 4, 0, second, tzinfo=timezone.utc),
        valid=valid,
    )


def test_prefill_history_fills_the_table(qtbot) -> None:
    panel = DataPanelWidget()
    qtbot.addWidget(panel)

    panel.prefill_history("sim-1", "ch1", [_stored(2), _stored(1)])

    assert panel.history_count() == 2


def test_prefill_history_puts_the_oldest_at_the_top(qtbot) -> None:
    """存储按"新的在前"返回，表格却要自上而下顺着时间读——
    与实时路径追加的方向一致，否则同一张表两半边的时序是反的。"""
    panel = DataPanelWidget()
    qtbot.addWidget(panel)

    panel.prefill_history("sim-1", "ch1", [_stored(2, 26.0), _stored(1, 25.0)])

    table = panel._history_tables["ch1"]
    assert table.item(0, 1).text() == "25.0"
    assert table.item(1, 1).text() == "26.0"


def test_prefill_history_does_not_touch_the_real_time_table(qtbot) -> None:
    """预填的是已经过去的读数，不代表当前值。"""
    panel = DataPanelWidget()
    qtbot.addWidget(panel)

    panel.prefill_history("sim-1", "ch1", [_stored(1)])

    assert panel.row_count() == 0


def test_prefill_history_respects_the_display_cap(qtbot) -> None:
    panel = DataPanelWidget(history_limit=3)
    qtbot.addWidget(panel)

    panel.prefill_history("sim-1", "ch1", [_stored(s) for s in range(10)])

    assert panel.history_count() == 3


def test_clear_history_only_clears_the_display(qtbot) -> None:
    """按钮的语义 2026-09-17 收窄为"清掉我正在看的"。

    读数现在是持久化的，删库是另一回事、且是破坏性的，不该藏在一个
    写着"清空历史记录"的按钮后面。这条用例守的是这个决定：清空之后
    重新预填，数据照样回来——因为它从来没被删过。
    """
    panel = DataPanelWidget()
    qtbot.addWidget(panel)
    panel.prefill_history("sim-1", "ch1", [_stored(1)])

    panel.clear_history()
    assert panel.history_count() == 0

    panel.prefill_history("sim-1", "ch1", [_stored(1)])
    assert panel.history_count() == 1


def test_clear_history_empties_the_history_list(qtbot) -> None:
    panel = DataPanelWidget()
    qtbot.addWidget(panel)
    panel.add_data_point("sim-1", "ch1", "1")
    panel.add_data_point("sim-1", "ch1", "2")

    panel.clear_history()

    assert panel.history_count() == 0


def test_clear_history_does_not_touch_the_real_time_table(qtbot) -> None:
    panel = DataPanelWidget()
    qtbot.addWidget(panel)
    panel.add_data_point("sim-1", "ch1", "42")

    panel.clear_history()

    assert panel.row_count() == 1
    assert panel._latest_table.item(0, 2).text() == "42"


def test_clear_history_button_click_clears_history(qtbot) -> None:
    panel = DataPanelWidget()
    qtbot.addWidget(panel)
    panel.add_data_point("sim-1", "ch1", "1")

    panel._clear_history_button.click()

    assert panel.history_count() == 0


def test_add_data_point_fills_unit_and_normal_status(qtbot) -> None:
    panel = DataPanelWidget()
    qtbot.addWidget(panel)

    panel.add_data_point("mcu-1", "temperature", "29.58")

    assert panel._latest_table.item(0, 3).text() == "°C"
    assert panel._latest_table.item(0, 4).text() == "正常"


def test_unknown_channel_has_empty_unit(qtbot) -> None:
    panel = DataPanelWidget()
    qtbot.addWidget(panel)

    panel.add_data_point("mcu-1", "pressure", "1013")

    assert panel._latest_table.item(0, 3).text() == ""


def test_set_alarm_updates_the_status_column_text(qtbot) -> None:
    panel = DataPanelWidget()
    qtbot.addWidget(panel)
    panel.add_data_point("mcu-1", "noise", "85.0")

    panel.set_alarm("mcu-1", "noise", True)
    assert panel._latest_table.item(0, 4).text() == "报警"

    panel.set_alarm("mcu-1", "noise", False)
    assert panel._latest_table.item(0, 4).text() == "正常"


def test_realtime_and_history_groups_are_independently_placeable(qtbot) -> None:
    """2026-08-13 dashboard redesign: MainWindow places these two group
    boxes in different dashboard tiers -- both must be real, distinct
    widgets containing the corresponding tables."""
    panel = DataPanelWidget()
    qtbot.addWidget(panel)

    realtime = panel.realtime_group()
    history = panel.history_group()

    assert realtime is not history
    assert panel._latest_table.parent() is realtime
    # 2026-09-18: 历史区现在是每通道一列，各列的 group box 挂在 history 下面
    for channel_id in ("temperature", "humidity", "noise"):
        assert panel._history_titles[channel_id].parent() is history
        assert (
            panel._history_tables[channel_id].parent()
            is panel._history_titles[channel_id]
        )


def test_history_status_column_reflects_last_known_alarm_state(qtbot) -> None:
    panel = DataPanelWidget()
    qtbot.addWidget(panel)
    panel.add_data_point("sim-1", "temperature", "36.5")  # normal, no alarm yet

    panel.set_alarm("sim-1", "temperature", True)
    panel.add_data_point("sim-1", "temperature", "40.0")  # now alarming

    table = panel._history_tables["temperature"]
    assert table.item(0, 2).text() == "正常"
    assert table.item(1, 2).text() == "报警"


def test_set_alarm_is_a_no_op_for_an_unknown_row(qtbot) -> None:
    """No exception, no row created -- e.g. an alarm on a channel the
    user never subscribed to display."""
    panel = DataPanelWidget()
    qtbot.addWidget(panel)

    panel.set_alarm("sim-1", "temperature", True)

    assert panel.row_count() == 0


# -- 每通道一列的历史区 + 按通道定小数位（2026-09-18） ----------------------


def test_each_channel_gets_its_own_history_column(qtbot) -> None:
    panel = DataPanelWidget()
    qtbot.addWidget(panel)

    panel.add_data_point("mcu-1", "temperature", "25.0")
    panel.add_data_point("mcu-1", "humidity", "56.0")
    panel.add_data_point("mcu-1", "noise", "48.0")

    assert panel.history_count() == 3
    for channel_id in ("temperature", "humidity", "noise"):
        assert panel.history_count_for(channel_id) == 1


def test_the_three_columns_exist_before_any_data_arrives(qtbot) -> None:
    """否则历史页在收到第一条读数前是一片空白，看起来像坏了。"""
    panel = DataPanelWidget()
    qtbot.addWidget(panel)

    assert set(panel._history_tables) == {"temperature", "humidity", "noise"}


def test_an_unknown_channel_still_gets_a_column(qtbot) -> None:
    """平台不枚举通道，读数不能因为"没有它的列"而被悄悄丢掉。"""
    panel = DataPanelWidget()
    qtbot.addWidget(panel)

    panel.add_data_point("mcu-1", "pressure", "101.3")

    assert panel.history_count_for("pressure") == 1
    assert panel.history_count() == 1


def test_the_cap_is_per_column_not_shared(qtbot) -> None:
    """共用一个上限时，三条通道互相挤占，看一条通道只能回溯三分之一。"""
    panel = DataPanelWidget(history_limit=3)
    qtbot.addWidget(panel)

    for value in range(10):
        panel.add_data_point("mcu-1", "temperature", str(value))
        panel.add_data_point("mcu-1", "noise", str(value))

    assert panel.history_count_for("temperature") == 3
    assert panel.history_count_for("noise") == 3
    assert panel.history_count() == 6


def test_clear_history_empties_every_column(qtbot) -> None:
    panel = DataPanelWidget()
    qtbot.addWidget(panel)
    panel.add_data_point("mcu-1", "temperature", "25.0")
    panel.add_data_point("mcu-1", "noise", "48.0")

    panel.clear_history()

    assert panel.history_count() == 0
    assert panel.history_count_for("temperature") == 0
    assert panel.history_count_for("noise") == 0


def test_the_column_title_names_the_device_feeding_it(qtbot) -> None:
    """设备写在列标题而不是第四列：三列分宽度之后，
    "sim-env-1-noise" 放进单元格只会被省略号截掉。"""
    panel = DataPanelWidget()
    qtbot.addWidget(panel)
    assert panel._history_titles["temperature"].title() == "温度 °C"

    panel.add_data_point("sim-env-1-temp", "temperature", "25.0")

    assert panel._history_titles["temperature"].title() == "温度 °C · sim-env-1-temp"


def test_a_second_device_on_one_channel_is_named_too_not_hidden(qtbot) -> None:
    """两台设备的读数混在一个标题下又分不出谁是谁，比标题长更糟。"""
    panel = DataPanelWidget()
    qtbot.addWidget(panel)

    panel.add_data_point("mcu-1", "noise", "48.0")
    panel.add_data_point("mcu-2", "noise", "49.0")

    assert panel._history_titles["noise"].title() == "噪声 dB · mcu-1、mcu-2"


def test_temperature_and_noise_show_two_decimals(qtbot) -> None:
    panel = DataPanelWidget()
    qtbot.addWidget(panel)

    panel.add_data_point("mcu-1", "temperature", "25.029390713306746")
    panel.add_data_point("mcu-1", "noise", "48.9")

    assert panel._history_tables["temperature"].item(0, 1).text() == "25.03"
    assert panel._history_tables["noise"].item(0, 1).text() == "48.90"


def test_humidity_shows_no_decimals(qtbot) -> None:
    """AHT20 湿度精度 ±2 %RH，"56.27 %" 是虚假精度。"""
    panel = DataPanelWidget()
    qtbot.addWidget(panel)

    panel.add_data_point("mcu-1", "humidity", "56.27332669523828")

    assert panel._history_tables["humidity"].item(0, 1).text() == "56"


def test_the_real_time_table_uses_the_same_rounding(qtbot) -> None:
    """同一个读数在同一个窗口里不该出现两种写法。"""
    panel = DataPanelWidget()
    qtbot.addWidget(panel)

    panel.add_data_point("mcu-1", "temperature", "25.029390713306746")
    panel.add_data_point("mcu-1", "humidity", "56.27332669523828")

    assert panel._latest_table.item(0, 2).text() == "25.03"
    assert panel._latest_table.item(1, 2).text() == "56"


def test_prefill_history_rounds_the_same_way_as_the_live_path(qtbot) -> None:
    """补进来的历史与实时追加的行必须是同一种写法，否则一张表两半边不一样。"""
    panel = DataPanelWidget()
    qtbot.addWidget(panel)

    panel.prefill_history("mcu-1", "temperature", [_stored(1, 25.029390713306746)])
    panel.add_data_point("mcu-1", "temperature", "25.029390713306746")

    table = panel._history_tables["temperature"]
    assert table.item(0, 1).text() == table.item(1, 1).text() == "25.03"
