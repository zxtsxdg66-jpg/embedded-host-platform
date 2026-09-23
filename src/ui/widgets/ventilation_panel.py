"""VentilationPanelWidget: the ventilation fan's *controls*.

The companion to FanCardWidget, which shows the resulting state. Controls
and state are split across the window on purpose (2026-09-07 layout
decision): the fan's state belongs beside the temperature and humidity it
reacts to, up in the metric row, while the knobs belong down with the
other panels so they do not compete with the data for attention.

Two things live here:

- **Ventilation thresholds**, adjustable at runtime. These are *not* the
  threshold-alarm limits -- those are argued from GB 37488-2019 and
  stay fixed. See service/ventilation_controller.py for why
  the two sets are deliberately separate. Being adjustable is what makes
  the feature demonstrable: dropping the temperature limit below the
  current reading starts the fan immediately, instead of waiting for the
  room to actually get hot.
- **Manual override**: automatic / always-on / always-off.

Passive View, like every widget in this package: it holds no reference to
MainController or ApiInterface, and it deliberately does **not** import
``service`` -- the fan mode crosses this boundary as a plain string, so
this widget stays free of business types (matching the constraint
recorded in ui/README.md that widgets depend only on PyQt6, the standard
library, and same-layer ui.theme / ui.channel_display).

Spin boxes use ``setKeyboardTracking(False)`` so typing "25" emits once
when editing finishes rather than once per keystroke, while the stepper
arrows still emit immediately -- which is the interaction a live
demonstration actually uses.
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ui.theme import set_class

MODE_AUTO = "AUTO"
MODE_MANUAL_ON = "MANUAL_ON"
MODE_MANUAL_OFF = "MANUAL_OFF"

_MODE_LABELS: dict[str, str] = {
    MODE_AUTO: "自动",
    MODE_MANUAL_ON: "常开",
    MODE_MANUAL_OFF: "常关",
}


def mode_label(mode: str) -> str:
    """Display text for a fan mode name, for callers that need to render
    the mode outside this panel (FanCardWidget's header, activity log)."""
    return _MODE_LABELS.get(mode, mode)


class VentilationPanelWidget(QWidget):
    """Ventilation thresholds and manual fan override."""

    thresholds_changed = pyqtSignal(float, float)
    """temperature_max (°C), humidity_max (%RH)."""

    mode_changed = pyqtSignal(str)
    """One of MODE_AUTO / MODE_MANUAL_ON / MODE_MANUAL_OFF."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._temperature_input = QDoubleSpinBox()
        self._temperature_input.setRange(0.0, 60.0)
        self._temperature_input.setDecimals(1)
        self._temperature_input.setSingleStep(0.5)
        self._temperature_input.setSuffix(" ℃")
        self._temperature_input.setKeyboardTracking(False)

        self._humidity_input = QDoubleSpinBox()
        self._humidity_input.setRange(0.0, 100.0)
        self._humidity_input.setDecimals(1)
        self._humidity_input.setSingleStep(1.0)
        self._humidity_input.setSuffix(" %RH")
        self._humidity_input.setKeyboardTracking(False)

        self._auto_button = QRadioButton(_MODE_LABELS[MODE_AUTO])
        self._on_button = QRadioButton(_MODE_LABELS[MODE_MANUAL_ON])
        self._off_button = QRadioButton(_MODE_LABELS[MODE_MANUAL_OFF])
        self._auto_button.setChecked(True)

        self._mode_group = QButtonGroup(self)
        for button, mode in (
            (self._auto_button, MODE_AUTO),
            (self._on_button, MODE_MANUAL_ON),
            (self._off_button, MODE_MANUAL_OFF),
        ):
            self._mode_group.addButton(button)
            button.setProperty("fan_mode", mode)

        self._group = QGroupBox("通风控制")
        self._build_layout()
        self._wire_internal_signals()

    def _build_layout(self) -> None:
        hint = QLabel("超过阈值自动送风（与报警阈值相互独立）")
        set_class(hint, "dim")
        hint.setWordWrap(True)

        temperature_row = QHBoxLayout()
        temperature_row.addWidget(QLabel("温度上限"))
        temperature_row.addWidget(self._temperature_input, stretch=1)

        humidity_row = QHBoxLayout()
        humidity_row.addWidget(QLabel("湿度上限"))
        humidity_row.addWidget(self._humidity_input, stretch=1)

        mode_row = QHBoxLayout()
        mode_row.addWidget(self._auto_button)
        mode_row.addWidget(self._on_button)
        mode_row.addWidget(self._off_button)
        mode_row.addStretch(1)

        group_layout = QVBoxLayout()
        group_layout.addWidget(hint)
        group_layout.addLayout(temperature_row)
        group_layout.addLayout(humidity_row)
        group_layout.addLayout(mode_row)
        group_layout.addStretch(1)
        self._group.setLayout(group_layout)

        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._group)
        self.setLayout(outer)

    def _wire_internal_signals(self) -> None:
        self._temperature_input.valueChanged.connect(self._emit_thresholds)
        self._humidity_input.valueChanged.connect(self._emit_thresholds)
        self._mode_group.buttonClicked.connect(self._emit_mode)

    def _emit_thresholds(self) -> None:
        self.thresholds_changed.emit(
            self._temperature_input.value(), self._humidity_input.value()
        )

    def _emit_mode(self) -> None:
        self.mode_changed.emit(self.current_mode())

    # -- public API -------------------------------------------------------

    def group(self) -> QGroupBox:
        """The framed group box, for placing directly in a parent layout."""
        return self._group

    def set_settings(
        self, temperature_max: float, humidity_max: float, mode: str
    ) -> None:
        """Display settings that came from elsewhere, without emitting.

        Signals are blocked while updating so that syncing the view from
        the platform's current state cannot be mistaken for the user
        having changed something -- which would echo straight back and
        overwrite what was just read.
        """
        for widget, value in (
            (self._temperature_input, temperature_max),
            (self._humidity_input, humidity_max),
        ):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)

        for button, button_mode in (
            (self._auto_button, MODE_AUTO),
            (self._on_button, MODE_MANUAL_ON),
            (self._off_button, MODE_MANUAL_OFF),
        ):
            button.blockSignals(True)
            button.setChecked(button_mode == mode)
            button.blockSignals(False)

    def current_mode(self) -> str:
        checked = self._mode_group.checkedButton()
        if checked is None:
            return MODE_AUTO
        return str(checked.property("fan_mode"))

    def temperature_max(self) -> float:
        return self._temperature_input.value()

    def humidity_max(self) -> float:
        return self._humidity_input.value()
