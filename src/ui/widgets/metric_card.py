"""MetricCardWidget: one at-a-glance "指标卡" for a single channel's
current value, unit, and threshold state.

Corresponds to the 2026-08-13 dashboard redesign's "第一层" requirement:
the three core environmental metrics (temperature/humidity/noise) should
be the first thing a user sees, each showing its current value, unit,
channel id, a simple visual marker, and normal/warning/alarm state.

This widget is a "Passive View" (same pattern as every other widget in
this package): it holds no reference to MainController or ApiInterface.
Its only public entry points are :meth:`update_value` (fed by
MainController.data_received, via a small MainWindow adapter -- this
widget has no idea what a DataPoint is) and :meth:`set_alarm_state` (fed
by MainController.alarm_status_changed). Trend arrows (up/down/flat) are
computed locally from the previous value this widget itself was told
about -- a purely presentational comparison, not a business rule.

2026-08-13 information-hierarchy pass: these cards are meant to be a
"当前状态摘要" (current-state summary), distinct from ChartWidget's
"变化趋势" (trend-over-time) role -- so the trend arrow is deliberately
understated (a single muted color for up/down/flat, see
``ui/theme.py``'s ``[cls="trend-*"]`` rules) rather than colored
green/red, which would visually compete with the card's alarm border
(the only element on this card meant to demand attention) and would
wrongly imply "rising is bad" for channels where it is not.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.channel_display import format_value
from ui.theme import ACCENT, set_class, set_state

_DOT_SIZE = 12


class MetricCardWidget(QFrame):
    """A single-channel metric card: value, unit, title, trend, state."""

    def __init__(
        self,
        title: str,
        channel_id: str,
        unit: str,
        accent_color: str = ACCENT,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._channel_id = channel_id
        self._last_value: float | None = None
        self.setObjectName("metricCard")
        self.setFrameShape(QFrame.Shape.NoFrame)

        self._dot = QLabel()
        self._dot.setFixedSize(QSize(_DOT_SIZE, _DOT_SIZE))
        self._dot.setStyleSheet(
            f"background-color: {accent_color}; border-radius: {_DOT_SIZE // 2}px;"
        )

        self._title_label = QLabel(title)
        set_class(self._title_label, "metric-title")

        self._trend_label = QLabel("—")
        set_class(self._trend_label, "trend-flat")

        self._value_label = QLabel("--")
        set_class(self._value_label, "metric-value")
        self._value_label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )

        self._unit_label = QLabel(unit)
        set_class(self._unit_label, "metric-unit")

        self._meta_label = QLabel(f"channel: {channel_id} · 尚未订阅")
        set_class(self._meta_label, "dim")

        self._build_layout()

    def _build_layout(self) -> None:
        header_row = QHBoxLayout()
        header_row.addWidget(self._dot)
        header_row.addWidget(self._title_label)
        header_row.addStretch(1)
        header_row.addWidget(self._trend_label)

        value_row = QHBoxLayout()
        value_row.addWidget(self._value_label)
        value_row.addWidget(self._unit_label, alignment=Qt.AlignmentFlag.AlignBottom)
        value_row.addStretch(1)

        layout = QVBoxLayout()
        layout.addLayout(header_row)
        layout.addLayout(value_row)
        layout.addWidget(self._meta_label)
        layout.setSpacing(4)
        self.setLayout(layout)

    def update_value(self, value: float, received_at: str) -> None:
        """Update the displayed value, trend arrow, and "最近更新" meta
        line. ``received_at`` is a caller-supplied display string (e.g.
        ``datetime.now().strftime('%H:%M:%S')``) -- this widget has no
        clock of its own and does not assume anything about timestamps
        beyond "a string to show"."""
        if self._last_value is not None:
            if value > self._last_value:
                self._trend_label.setText("↑")
                set_class(self._trend_label, "trend-up")
            elif value < self._last_value:
                self._trend_label.setText("↓")
                set_class(self._trend_label, "trend-down")
            else:
                self._trend_label.setText("—")
                set_class(self._trend_label, "trend-flat")
        self._last_value = value
        # 2026-09-18: 由写死的 .1f 改为与表格共用 channel_display 的按通道
        # 约定。这张卡片本可以少一位小数——它是"一眼看个大概"那一档，
        # 而数字越长，9.9→10.0 这类进位造成的横向跳动越频繁。但一个窗口里
        # 同一条读数出现两种写法（卡片 25.0、表格 25.03）比跳动更难解释，
        # 手机端同日也统一到了两位（android/.../ui/ChannelFormat.kt）。
        self._value_label.setText(format_value(value, self._channel_id))
        self._meta_label.setText(f"channel: {self._channel_id} · 更新于 {received_at}")

    def set_alarm_state(self, triggered: bool) -> None:
        """Reflect an alarm's triggered/cleared state via the card's
        border (see ui/theme.py's ``QFrame#metricCard[state=...]``
        rules)."""
        set_state(self, "alarm" if triggered else "normal")

    def channel_id(self) -> str:
        return self._channel_id

    def current_value(self) -> float | None:
        return self._last_value
