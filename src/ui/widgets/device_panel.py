"""DevicePanelWidget: passive device-info display -- device id, connection
state, control-occupancy state, and (if available) capability info.

Corresponds to the phase-2 task's "设备管理" requirement. This widget is
a "Passive View" (per the PyQt6 UI guidelines' "keep
widgets independent of business logic"): it holds no reference to
MainController or ApiInterface, and is only ever updated through
:meth:`set_status`, whose signature intentionally matches
``ui.controller.MainController.device_status_changed`` exactly so
MainWindow can connect them directly.

Capability info: ``application.runtime.DeviceStatusView`` (the type
``ApiInterface.get_device_status`` returns) does not carry a capability
field -- extending it would mean modifying `src/api`/`src/application`,
which is out of scope for this widget. This panel therefore shows
"能力信息：未获取" rather than fabricated data -- honest about the gap
without exposing internal type/API names (``DeviceStatusView``,
``ApiInterface``, ...) that a real end user has no reason to see; see
docs/verification.md's 2026-08-13 note for why this
text was changed from an earlier, more debug-flavored wording.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui.theme import SUCCESS, TEXT_DISABLED

_DOT_SIZE = 10


def _labeled_row(caption: str, value_widget: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.addWidget(QLabel(caption))
    row.addWidget(value_widget, stretch=1)
    return row


class DevicePanelWidget(QWidget):
    """Displays the currently selected device's id, connection, and occupancy."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._device_id_label = QLabel("-")
        self._connection_dot = QLabel()
        self._connection_dot.setFixedSize(_DOT_SIZE, _DOT_SIZE)
        self._set_connection_dot(False)
        self._connection_label = QLabel("-")
        self._occupancy_label = QLabel("-")
        self._capability_label = QLabel("未获取")
        self._capability_label.setWordWrap(True)

        self._build_layout()

    def _build_layout(self) -> None:
        connection_row = QHBoxLayout()
        connection_row.addWidget(self._connection_dot)
        connection_row.addWidget(self._connection_label, stretch=1)
        connection_container = QWidget()
        connection_container.setLayout(connection_row)

        box = QGroupBox("设备信息")
        layout = QVBoxLayout()
        layout.addLayout(_labeled_row("设备 ID：", self._device_id_label))
        layout.addLayout(_labeled_row("连接状态：", connection_container))
        layout.addLayout(_labeled_row("控制状态：", self._occupancy_label))
        layout.addLayout(_labeled_row("设备能力：", self._capability_label))
        box.setLayout(layout)

        outer = QVBoxLayout()
        outer.addWidget(box)
        self.setLayout(outer)

    def set_status(
        self, device_id: str, is_connected: bool, is_occupied: bool, occupant: str
    ) -> None:
        """Update the panel. Signature matches
        MainController.device_status_changed for direct signal/slot connection."""
        self._device_id_label.setText(device_id)
        self._connection_label.setText("已连接" if is_connected else "未连接")
        self._set_connection_dot(is_connected)
        self._occupancy_label.setText(
            f"被 {occupant} 占用" if is_occupied else "空闲"
        )

    def clear(self) -> None:
        """Reset all fields to their placeholder state."""
        self._device_id_label.setText("-")
        self._connection_label.setText("-")
        self._set_connection_dot(False)
        self._occupancy_label.setText("-")

    def _set_connection_dot(self, connected: bool) -> None:
        color = SUCCESS if connected else TEXT_DISABLED
        self._connection_dot.setStyleSheet(
            f"background-color: {color}; border-radius: {_DOT_SIZE // 2}px;"
        )
