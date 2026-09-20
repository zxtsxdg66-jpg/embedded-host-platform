"""DeviceListItemWidget: a small card-style row shown inside the device
list via ``QListWidget.setItemWidget`` -- the visual upgrade from a bare
device-id text row, without changing the device list's underlying
QListWidget behavior (selection, ``currentTextChanged``, ``item(i).text()``,
row count) at all, so nothing that already depends on that contract
(tests, MainWindow's own selection wiring) needs to change.

Deliberately does *not* fabricate a "device type" (e.g. "STM32"): the
data this platform's API surface provides
(application.runtime.DeviceStatusView) has no capability/type field (see
ui/widgets/device_panel.py's own docstring for why) -- this widget only
ever shows what it is actually told: device id, connection state, and
control-occupancy state.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui.theme import SUCCESS, TEXT_DISABLED, set_class

_DOT_SIZE = 9


class DeviceListItemWidget(QFrame):
    """One device's card: id, connection dot, occupancy line."""

    def __init__(self, device_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._device_id = device_id
        self.setObjectName("deviceCard")
        self.setFrameShape(QFrame.Shape.NoFrame)

        self._id_label = QLabel(device_id)
        set_class(self._id_label, "metric-title")

        self._dot = QLabel()
        self._dot.setFixedSize(_DOT_SIZE, _DOT_SIZE)
        self._set_dot_color(TEXT_DISABLED)

        self._connection_label = QLabel("状态未知")
        set_class(self._connection_label, "dim")

        self._occupancy_label = QLabel("")
        set_class(self._occupancy_label, "dim")

        self._build_layout()

    def _build_layout(self) -> None:
        status_row = QHBoxLayout()
        status_row.addWidget(self._dot)
        status_row.addWidget(self._connection_label)
        status_row.addStretch(1)

        layout = QVBoxLayout()
        layout.addWidget(self._id_label)
        layout.addLayout(status_row)
        layout.addWidget(self._occupancy_label)
        layout.setSpacing(2)
        layout.setContentsMargins(8, 6, 8, 6)
        self.setLayout(layout)

    def device_id(self) -> str:
        return self._device_id

    def set_status(self, is_connected: bool, is_occupied: bool, occupant: str) -> None:
        self._connection_label.setText("已连接" if is_connected else "未连接")
        self._set_dot_color(SUCCESS if is_connected else TEXT_DISABLED)
        self._occupancy_label.setText(f"被 {occupant} 占用" if is_occupied else "空闲")

    def set_selected(self, selected: bool) -> None:
        """Reflect selection via the ``QFrame#deviceCard[selected=...]``
        QSS rule in ui/theme.py."""
        self.setProperty("selected", "true" if selected else "false")
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)

    def _set_dot_color(self, color: str) -> None:
        self._dot.setStyleSheet(f"background-color: {color}; border-radius: 4px;")
