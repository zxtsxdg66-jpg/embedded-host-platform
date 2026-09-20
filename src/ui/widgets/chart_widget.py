"""ChartWidget: a self-contained rolling multi-series line chart with a
grid, axis labels, and a legend showing each series' current value.

Corresponds to the phase-2 task's "实时曲线" requirement, extended by the
2026-08-13 dashboard redesign's requirement that the chart become the
page's dominant visual element (grid/axes/legend/current value, not just
bare lines) while staying "业务解耦" (decoupled from any business
concept):

- Built entirely on PyQt6.QtGui.QPainter (a standard part of PyQt6
  itself) -- no charting library (pyqtgraph, QtCharts, matplotlib, ...)
  is added, so this introduces no new dependency.
- The only public entry point for data is still :meth:`add_point`, a
  plain ``(series_name: str, value: float)`` pair. This widget has no
  knowledge of DataPoint, ApiInterface, MainController, temperature/
  humidity/noise, or SimulatorDevice -- it imports nothing beyond PyQt6,
  the standard library, and sibling ``ui.theme`` color *constants*
  (plain strings, not the QSS/QPalette machinery) for its series
  palette, purely so the chart's line colors match the rest of the
  dashboard's design system. Any future data source (a real sensor, a
  different simulator, a replay of recorded data) can drive it
  identically, through whatever adapter code calls add_point -- see
  ui/main_window.py's ``_on_data_received_for_chart`` for the phase-1/2
  adapter.
- Grid lines, axis value labels, and the legend (series name + swatch +
  current value) are all derived purely from the already-tracked
  ``_series: dict[str, deque[float]]`` buffers -- no new state, no
  business-specific formatting (units, thresholds, channel display
  names) is embedded here; that stays the caller's job.
"""

from __future__ import annotations

from collections import deque

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import QWidget

from ui.theme import (
    ACCENT,
    CHART_PLOT_BACKGROUND_ALPHA,
    DANGER,
    SECONDARY_BLUE,
    SECONDARY_PURPLE,
    WARNING,
)

_SERIES_COLORS = [
    QColor(ACCENT),
    QColor(SECONDARY_BLUE),
    QColor(SECONDARY_PURPLE),
    QColor(WARNING),
    QColor(DANGER),
]
_GRID_ROWS = 4
_MARGIN_LEFT = 52.0
_MARGIN_RIGHT = 16.0
_MARGIN_TOP = 16.0
_MARGIN_BOTTOM = 8.0
_LEGEND_SWATCH_SIZE = 10.0
# 每格上方留给"序列名 + 当前值"的高度（取代了原先浮在图上的图例框）
_PANE_TITLE_HEIGHT = 20.0


class ChartWidget(QWidget):
    """Rolling multi-series line chart, independent of any data source or
    business type -- grid/axis/legend are purely generic charting
    concerns, derived only from (series_name, float) pairs."""

    def __init__(self, max_points: int = 100, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._max_points = max_points
        self._series: dict[str, deque[float]] = {}
        self.setMinimumHeight(150)

    def add_point(self, series: str, value: float) -> None:
        """Append ``value`` to ``series``'s rolling buffer and repaint."""
        buffer = self._series.setdefault(series, deque(maxlen=self._max_points))
        buffer.append(float(value))
        self.update()

    def clear(self) -> None:
        """Remove all series and repaint."""
        self._series.clear()
        self.update()

    def series_names(self) -> list[str]:
        """Names of every series currently plotted."""
        return list(self._series.keys())

    def paintEvent(self, event: QPaintEvent | None) -> None:
        del event  # unused: this widget always repaints its full area
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            self._draw(painter)
        finally:
            painter.end()

    def pane_range(self, series: str) -> tuple[float, float] | None:
        """The (minimum, maximum) actually used for ``series``' own Y axis.

        Exposed so the layout choice can be asserted in tests: each series
        is scaled to its own data, never to the pooled range of all series.
        Returns None for an unknown or empty series.
        """
        buffer = self._series.get(series)
        if not buffer:
            return None
        return self._range_for(buffer)

    @staticmethod
    def _range_for(buffer: deque[float]) -> tuple[float, float]:
        minimum, maximum = min(buffer), max(buffer)
        if minimum == maximum:
            # 常量序列：给一个对称的小窗口，否则整条线会贴在格子边缘上
            minimum -= 1.0
            maximum += 1.0
        return minimum, maximum

    def _draw(self, painter: QPainter) -> None:
        # 2026-08-13 panel-transparency rework: the plot area used to be
        # filled fully opaque (self.palette().base(), no alpha) -- now a
        # light translucent fill so the background image still reads
        # through the chart's own card (ui/theme.py's QFrame#chartCard is
        # already translucent; this keeps the inner plot consistent with
        # it rather than punching an opaque hole back into it).
        plot_background = self.palette().base().color()
        plot_background.setAlphaF(CHART_PLOT_BACKGROUND_ALPHA)
        painter.fillRect(self.rect(), plot_background)

        series = [(name, buf) for name, buf in self._series.items() if buf]
        if not series:
            empty = QRectF(self.rect()).adjusted(
                _MARGIN_LEFT, _MARGIN_TOP, -_MARGIN_RIGHT, -_MARGIN_BOTTOM
            )
            painter.setPen(QPen(self.palette().mid().color()))
            painter.drawRect(empty)
            return

        for index, (name, buffer) in enumerate(series):
            pane = self._pane_rect(index, len(series))
            minimum, maximum = self._range_for(buffer)
            self._draw_pane_title(painter, pane, name, buffer[-1], index)
            self._draw_grid(painter, pane, minimum, maximum)
            self._draw_series(painter, pane, buffer, minimum, maximum, index)

    def _pane_rect(self, index: int, total: int) -> QRectF:
        """Plot rectangle of the ``index``-th pane in a side-by-side row.

        Panes are laid out **horizontally**, not stacked: the chart card is
        a wide, short strip (measured ~5.8:1 on the 2026-08-13 dashboard),
        so splitting it vertically would leave each pane near 17:1 -- a
        sliver in which every curve reads as a flat line no matter how it
        is scaled. Split horizontally each pane is close to 2:1, and each
        one lands directly under its own metric card, giving the dashboard
        one consistent three-column rhythm.
        """
        outer = QRectF(self.rect()).adjusted(0, _MARGIN_TOP, 0, -_MARGIN_BOTTOM)
        width = outer.width() / total
        left = outer.left() + index * width
        return QRectF(
            left + _MARGIN_LEFT,
            outer.top() + _PANE_TITLE_HEIGHT,
            width - _MARGIN_LEFT - _MARGIN_RIGHT,
            outer.height() - _PANE_TITLE_HEIGHT,
        )

    def _draw_pane_title(
        self,
        painter: QPainter,
        rect: QRectF,
        name: str,
        current: float,
        color_index: int,
    ) -> None:
        """Series name + its current value above the pane.

        Replaces the former shared top-right legend box: with one pane per
        series the legend's job (which colour is which series, what is each
        series' latest value) is better done in place, and the floating box
        no longer covers part of the plot.
        """
        font = QFont(painter.font())
        font.setPointSizeF(max(7.5, font.pointSizeF() - 1))
        painter.setFont(font)

        swatch = QRectF(
            rect.left(),
            rect.top() - _PANE_TITLE_HEIGHT + 5,
            _LEGEND_SWATCH_SIZE,
            _LEGEND_SWATCH_SIZE,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_SERIES_COLORS[color_index % len(_SERIES_COLORS)])
        painter.drawRoundedRect(swatch, 2, 2)
        # 画刷必须复位：本方法现在跑在 _draw_grid **之前**（旧版图例是最后画的，
        # 所以没暴露这个问题），不复位的话网格那句 drawRect 会带着色块画刷
        # 把整个绘图区填成实心色块。
        painter.setBrush(Qt.BrushStyle.NoBrush)

        text_rect = QRectF(
            swatch.right() + 5,
            rect.top() - _PANE_TITLE_HEIGHT,
            rect.width() - _LEGEND_SWATCH_SIZE - 5,
            _PANE_TITLE_HEIGHT,
        )
        painter.setPen(QPen(self.palette().text().color()))
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            f"{name}  {current:.2f}",
        )

    def _draw_grid(
        self, painter: QPainter, rect: QRectF, minimum: float, maximum: float
    ) -> None:
        """Horizontal gridlines with value labels, plus the plot border --
        purely a generic axis rendering, no knowledge of what the values
        mean."""
        grid_pen = QPen(self.palette().mid().color())
        grid_pen.setStyle(Qt.PenStyle.DotLine)
        text_color = self.palette().mid().color().lighter(160)
        font = QFont(painter.font())
        font.setPointSizeF(max(7.5, font.pointSizeF() - 1.5))
        metrics = QFontMetricsF(font)

        for row in range(_GRID_ROWS + 1):
            fraction = row / _GRID_ROWS
            y = rect.bottom() - fraction * rect.height()
            value = minimum + fraction * (maximum - minimum)

            painter.setPen(grid_pen)
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

            painter.setPen(QPen(text_color))
            painter.setFont(font)
            label = f"{value:.1f}"
            label_rect = QRectF(
                rect.left() - _MARGIN_LEFT,
                y - metrics.height() / 2,
                _MARGIN_LEFT - 6,
                metrics.height(),
            )
            painter.drawText(
                label_rect,
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                label,
            )

        border_pen = QPen(self.palette().mid().color())
        painter.setPen(border_pen)
        painter.drawRect(rect)

    def _draw_series(
        self,
        painter: QPainter,
        rect: QRectF,
        buffer: deque[float],
        minimum: float,
        maximum: float,
        color_index: int,
    ) -> None:
        count = len(buffer)
        if count < 2:
            return

        color = _SERIES_COLORS[color_index % len(_SERIES_COLORS)]
        painter.setPen(QPen(color, 2))

        span = maximum - minimum
        points = []
        for i, value in enumerate(buffer):
            x = rect.left() + (i / (count - 1)) * rect.width()
            normalized = (value - minimum) / span
            y = rect.bottom() - normalized * rect.height()
            points.append(QPointF(x, y))

        for start, end in zip(points, points[1:], strict=False):
            painter.drawLine(start, end)
