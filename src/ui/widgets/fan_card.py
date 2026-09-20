"""FanCardWidget: the ventilation fan's state, shown as a fourth metric card.

Sits in the same top row as the three MetricCardWidgets (temperature /
humidity / noise) and deliberately borrows their ``metricCard`` object
name so it inherits the identical card styling from ui/theme.py.

Why a card in that row rather than a control down in the panel area: the
fan reacts to the very temperature and humidity shown beside it, and
putting cause and effect on one line is what makes that legible at a
glance -- "温度 31.2℃" next to "风扇 运行中 · 温度高于通风阈值 30℃" reads
as a single sentence. The *controls* for ventilation (thresholds, manual
override) live separately in VentilationPanelWidget; this card is
read-only.

Passive View, same as every other widget in this package: it holds no
reference to MainController or ApiInterface and knows nothing about
FanDecision -- :meth:`set_decision` takes plain primitives that
MainWindow adapts from the controller's signal.

Not a MetricCardWidget subclass: that widget's whole surface is numeric
(``update_value(value: float, ...)``, a locally computed trend arrow from
comparing successive numbers). A fan has a state and a reason, not a
magnitude, so inheriting would mean inheriting an API that cannot be
honestly implemented.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui.theme import SUCCESS, TEXT_DISABLED, set_class, set_state

_DOT_SIZE = 12

_RUNNING_TEXT = "运行中"
_STOPPED_TEXT = "已停止"


class FanCardWidget(QFrame):
    """Read-only card showing whether the ventilation fan is running, why,
    and under which mode."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("metricCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._running = False

        self._dot = QLabel()
        self._dot.setFixedSize(QSize(_DOT_SIZE, _DOT_SIZE))

        self._title_label = QLabel("通风")
        set_class(self._title_label, "metric-title")

        self._mode_label = QLabel("自动")
        set_class(self._mode_label, "dim")

        self._state_label = QLabel(_STOPPED_TEXT)
        set_class(self._state_label, "metric-value")

        self._reason_label = QLabel("尚无数据")
        set_class(self._reason_label, "dim")
        self._reason_label.setWordWrap(True)

        self._build_layout()
        self._paint_dot(running=False)

    def _build_layout(self) -> None:
        header_row = QHBoxLayout()
        header_row.addWidget(self._dot)
        header_row.addWidget(self._title_label)
        header_row.addStretch(1)
        header_row.addWidget(self._mode_label)

        state_row = QHBoxLayout()
        state_row.addWidget(self._state_label)
        state_row.addStretch(1)

        layout = QVBoxLayout()
        layout.addLayout(header_row)
        layout.addLayout(state_row)
        layout.addWidget(self._reason_label)
        layout.setSpacing(4)
        self.setLayout(layout)

    def _paint_dot(self, running: bool) -> None:
        color = SUCCESS if running else TEXT_DISABLED
        self._dot.setStyleSheet(
            f"background-color: {color}; border-radius: {_DOT_SIZE // 2}px;"
        )

    def set_decision(self, should_run: bool, reason: str, mode_label: str) -> None:
        """Show the fan state the platform currently wants, and why.

        ``reason`` and ``mode_label`` are display strings prepared by the
        caller -- this widget neither parses nor branches on them, so the
        wording can change without touching the view.
        """
        self._running = should_run
        self._state_label.setText(_RUNNING_TEXT if should_run else _STOPPED_TEXT)
        self._reason_label.setText(reason)
        self._mode_label.setText(mode_label)
        self._paint_dot(running=should_run)
        # "running" is a deliberate third state alongside normal/alarm: a
        # fan doing its job is not a fault condition (see ui/theme.py).
        set_state(self, "running" if should_run else "normal")

    def is_running(self) -> bool:
        """Last state this card was told to display."""
        return self._running

    def state_text(self) -> str:
        return self._state_label.text()

    def reason_text(self) -> str:
        return self._reason_label.text()

    def mode_text(self) -> str:
        return self._mode_label.text()
