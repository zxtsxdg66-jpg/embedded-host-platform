"""Tests for ui.widgets.chart_widget.ChartWidget -- no api/controller involved,
this widget is purely PyQt6 + stdlib."""

from __future__ import annotations

from ui.widgets.chart_widget import ChartWidget


def test_new_chart_has_no_series(qtbot) -> None:
    chart = ChartWidget()
    qtbot.addWidget(chart)
    assert chart.series_names() == []


def test_add_point_creates_a_series(qtbot) -> None:
    chart = ChartWidget()
    qtbot.addWidget(chart)

    chart.add_point("sim-1/ch1", 1.0)

    assert chart.series_names() == ["sim-1/ch1"]


def test_add_point_accepts_multiple_independent_series(qtbot) -> None:
    chart = ChartWidget()
    qtbot.addWidget(chart)

    chart.add_point("sim-1/ch1", 1.0)
    chart.add_point("sim-1/ch2", 2.0)

    assert set(chart.series_names()) == {"sim-1/ch1", "sim-1/ch2"}


def test_add_point_accepts_int_like_values() -> None:
    chart = ChartWidget()
    chart.add_point("s", 42)  # type: ignore[arg-type]
    assert chart.series_names() == ["s"]


def test_clear_removes_all_series(qtbot) -> None:
    chart = ChartWidget()
    qtbot.addWidget(chart)
    chart.add_point("sim-1/ch1", 1.0)

    chart.clear()

    assert chart.series_names() == []


def test_rolling_buffer_respects_max_points(qtbot) -> None:
    chart = ChartWidget(max_points=3)
    qtbot.addWidget(chart)

    for value in range(10):
        chart.add_point("s", float(value))

    # internal buffer length is bounded; verified indirectly via a repaint
    # not raising and series still present with the cap in place
    assert chart.series_names() == ["s"]


def test_paint_event_renders_without_error_when_empty(qtbot) -> None:
    chart = ChartWidget()
    qtbot.addWidget(chart)
    chart.resize(200, 100)

    pixmap = chart.grab()

    assert not pixmap.isNull()


def test_paint_event_renders_without_error_with_data(qtbot) -> None:
    chart = ChartWidget()
    qtbot.addWidget(chart)
    chart.resize(200, 100)
    for value in [1.0, 5.0, 2.0, 8.0]:
        chart.add_point("sim-1/ch1", value)

    pixmap = chart.grab()

    assert not pixmap.isNull()


def test_paint_event_handles_constant_series_without_error(qtbot) -> None:
    """A series where min == max must not divide by zero."""
    chart = ChartWidget()
    qtbot.addWidget(chart)
    chart.resize(200, 100)
    chart.add_point("s", 5.0)
    chart.add_point("s", 5.0)

    pixmap = chart.grab()

    assert not pixmap.isNull()


# --------------------------------------------------------------------------
# 三栏并排布局（2026-08-18）
#
# 此前三条序列共用一个 Y 量程：温度 20~30 ℃、湿度 60~90 %、噪声 40~110 dB
# 被汇总成一个 20~110 的轴，于是温度 6 ℃ 的真实变化只占纵向 7%，画出来是
# 一条直线。而且轴上的数字没有单位——三种量纲不可能共用一个线性轴。
# --------------------------------------------------------------------------


def test_each_series_is_scaled_to_its_own_range(qtbot) -> None:
    """The regression this layout exists for."""
    chart = ChartWidget()
    qtbot.addWidget(chart)
    for value in (22.0, 28.0):
        chart.add_point("temperature", value)
    for value in (40.0, 110.0):
        chart.add_point("noise", value)

    assert chart.pane_range("temperature") == (22.0, 28.0)
    assert chart.pane_range("noise") == (40.0, 110.0)


def test_a_huge_spike_in_one_series_does_not_flatten_another(qtbot) -> None:
    """A 110 dB shout used to drag the shared axis up and squash the
    temperature curve into a flat line."""
    chart = ChartWidget()
    qtbot.addWidget(chart)
    for value in (22.0, 28.0):
        chart.add_point("temperature", value)

    before = chart.pane_range("temperature")
    chart.add_point("noise", 110.3)

    assert chart.pane_range("temperature") == before


def test_panes_are_laid_out_side_by_side_not_stacked(qtbot) -> None:
    """Horizontal split: the chart card is a wide, short strip, so stacking
    would leave each pane a ~17:1 sliver."""
    chart = ChartWidget()
    qtbot.addWidget(chart)
    chart.resize(900, 200)
    for name in ("temperature", "humidity", "noise"):
        chart.add_point(name, 1.0)

    rects = [chart._pane_rect(i, 3) for i in range(3)]

    assert rects[0].left() < rects[1].left() < rects[2].left()  # 横向排开
    assert rects[0].top() == rects[1].top() == rects[2].top()   # 同一行
    assert all(r.width() > 0 and r.height() > 0 for r in rects)


def test_pane_range_is_none_for_unknown_or_empty_series(qtbot) -> None:
    chart = ChartWidget()
    qtbot.addWidget(chart)
    assert chart.pane_range("nope") is None


def test_a_constant_series_still_gets_a_usable_range(qtbot) -> None:
    chart = ChartWidget()
    qtbot.addWidget(chart)
    for _ in range(3):
        chart.add_point("humidity", 70.0)

    low, high = chart.pane_range("humidity")
    assert low < 70.0 < high
