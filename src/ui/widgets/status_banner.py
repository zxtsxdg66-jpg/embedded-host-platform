"""StatusBannerWidget: a single "系统状态/报警" summary, distinct from the
detailed activity log.

Corresponds to the 2026-08-13 dashboard redesign's "报警视觉设计"
requirement: the existing activity log entries ("报警：mcu-1/noise 超过
上限...") work but read like a plain log, not a status indicator a user
can recognize in 1-2 seconds. This widget is that indicator -- the
detailed log (ControlPanelWidget.show_alarm) is kept as-is for anyone
who wants the full history/detail.

Three states, each mapped from signals MainController already emits --
no new business concept is invented:

- 正常 (normal, low-key green dot): no channel currently in alarm, and no
  pending warning.
- 警告 (warning, amber dot): the most recent ``error_occurred`` (e.g. a
  command/device-lookup error) has not yet been superseded by a
  subsequent successful action. Deliberately *not* red -- an API/command
  error is not the same severity as an environmental threshold breach.
- 报警 (alarm, red dot): at least one channel currently has
  ``ThresholdStatus.triggered=True`` (temperature/humidity/noise). Takes
  priority over a pending warning.

This widget is a "Passive View": it holds no reference to MainController
or ApiInterface. Its public entry points (:meth:`set_alarm`,
:meth:`show_warning`, :meth:`clear_warning`) are called by MainWindow in
response to MainController's existing signals -- no new signal is added
to MainController.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.theme import DANGER, SUCCESS, WARNING, set_class, set_state

_DOT_SIZE = 10


class StatusBannerWidget(QFrame):
    """One-line system status summary: 正常 / 警告 / 报警, each with a
    colored dot and a short message."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusBanner")
        self.setFrameShape(QFrame.Shape.NoFrame)

        self._active_alarms: dict[tuple[str, str], str] = {}
        self._warning_message: str | None = None

        self._dot = QLabel()
        self._dot.setFixedSize(_DOT_SIZE, _DOT_SIZE)

        self._title_label = QLabel("系统状态")
        set_class(self._title_label, "section-title")

        self._message_label = QLabel("系统正常")
        set_class(self._message_label, "metric-title")
        self._message_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        self._build_layout()
        self._refresh()

    def _build_layout(self) -> None:
        top_row = QHBoxLayout()
        top_row.addWidget(self._title_label)
        top_row.addStretch(1)

        status_row = QHBoxLayout()
        status_row.addWidget(self._dot)
        status_row.addWidget(self._message_label, stretch=1)

        layout = QVBoxLayout()
        layout.addLayout(top_row)
        layout.addLayout(status_row)
        layout.setSpacing(6)
        self.setLayout(layout)

    # -- public: driven by MainWindow from MainController's signals -----

    def set_alarm(
        self, device_id: str, channel: str, message: str, triggered: bool
    ) -> None:
        """Register (``triggered=True``) or clear (``triggered=False``)
        one (device_id, channel)'s alarm contribution to the overall
        banner state. Matches the shape of MainController's
        ``alarm_status_changed`` signal (plus a caller-formatted
        message) -- see MainWindow's handler for the adapter."""
        key = (device_id, channel)
        if triggered:
            self._active_alarms[key] = message
        else:
            self._active_alarms.pop(key, None)
        self._refresh()

    def show_warning(self, message: str) -> None:
        """Record a pending warning (e.g. from ``error_occurred``)."""
        self._warning_message = message
        self._refresh()

    def clear_warning(self) -> None:
        """Clear any pending warning (e.g. after a subsequent successful
        action)."""
        self._warning_message = None
        self._refresh()

    def current_state(self) -> str:
        """"normal" | "warning" | "alarm" -- exposed for tests."""
        if self._active_alarms:
            return "alarm"
        if self._warning_message:
            return "warning"
        return "normal"

    def message(self) -> str:
        return self._message_label.text()

    # -- internal ---------------------------------------------------------

    def _refresh(self) -> None:
        state = self.current_state()
        set_state(self, state)
        if state == "alarm":
            color = DANGER
            text = "报警：" + "；".join(self._active_alarms.values())
        elif state == "warning":
            color = WARNING
            text = f"警告：{self._warning_message}"
        else:
            color = SUCCESS
            text = "系统正常"
        self._dot.setStyleSheet(
            f"background-color: {color}; border-radius: {_DOT_SIZE // 2}px;"
        )
        self._message_label.setText(text)
