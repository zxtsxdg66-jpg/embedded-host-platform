"""ControlPanelWidget: subscribe/acquire/release/send-command actions +
an activity log showing their outcomes.

Corresponds to the phase-2 task's "控制区域" requirement: acquire
control, release control, send a control command, and display command
execution results -- plus the channel-subscribe action, which is
naturally a user-initiated control action rather than passive data
display.

This widget is a "Passive View": it holds no reference to MainController
or ApiInterface and calls neither. User actions leave this widget only as
plain Qt signals (matching the skill's reference pattern -- "UI emits to
controller -- never calls model directly"); MainWindow is the only place
that connects these signals to MainController methods. Results reach this
widget only through its public ``show_*`` methods, called by MainWindow
in response to MainController's signals.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# 折叠开关的两种文案。调试控制默认收起，见 _build_layout 中的说明。
_COLLAPSED_TEXT = "▸ 展开调试控制"
_EXPANDED_TEXT = "▾ 收起调试控制"

# Display text -> actual command string sent over ApiInterface.submit_command().
# CUSTOM is special-cased: its own entry exists so it appears in the
# dropdown like any other option, but selecting it means "read the real
# command string from _custom_command_edit instead" (see
# _on_command_type_changed / _emit_send_command).
_COMMAND_TYPE_OPTIONS = (
    ("PING（设备心跳）", "PING"),
    ("RESET（重启设备）", "RESET"),
    ("CONFIG_GET（读取配置）", "CONFIG_GET"),
    ("CONFIG_SET（设置配置）", "CONFIG_SET"),
    ("FW_UPDATE（固件升级）", "FW_UPDATE"),
    ("CUSTOM（自定义命令）", "CUSTOM"),
)
_CUSTOM_COMMAND_DATA = "CUSTOM"

# Preset suggestions only -- the framework does not fix a channel-id enum
# (any device may expose arbitrary channel names), so the combo stays
# editable and these are just convenience entries for the channels the
# current sensor-simulation scenario happens to use.
_CHANNEL_ID_PRESETS = ("temperature", "humidity", "noise")


class ControlPanelWidget(QWidget):
    """Subscribe/acquire/release/send-command controls and an activity log."""

    subscribe_clicked = pyqtSignal(str)
    unsubscribe_clicked = pyqtSignal(str)
    acquire_clicked = pyqtSignal()
    release_clicked = pyqtSignal()
    send_command_clicked = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._channel_input = QComboBox()
        self._channel_input.setEditable(True)
        self._channel_input.addItems(_CHANNEL_ID_PRESETS)
        self._channel_input.setCurrentIndex(-1)
        line_edit = self._channel_input.lineEdit()
        if line_edit is not None:
            line_edit.setPlaceholderText(
                "通道 ID，例如 temperature（可直接输入自定义通道）"
            )
        self._subscribe_button = QPushButton("订阅")
        self._unsubscribe_button = QPushButton("暂停接收")

        self._acquire_button = QPushButton("获取控制权")
        self._release_button = QPushButton("释放控制权")

        self._cmd_type_combo = QComboBox()
        for display_text, command_data in _COMMAND_TYPE_OPTIONS:
            self._cmd_type_combo.addItem(display_text, command_data)
        self._cmd_type_combo.setCurrentIndex(0)  # PING（设备心跳）

        self._custom_command_edit = QLineEdit()
        self._custom_command_edit.setPlaceholderText("自定义命令")
        self._custom_command_edit.setEnabled(False)

        self._send_command_button = QPushButton("发送命令")

        self._activity_log = QListWidget()
        self._activity_log.setObjectName("activityLog")

        self._build_layout()
        self._wire_internal_signals()

    def _build_layout(self) -> None:
        """Build two independent group boxes: the operator controls, and the
        activity log.

        They used to share one box, which made this widget both tall and
        greedy: its stacked children's minimum heights inflated the whole
        bottom row past the 1/7 stretch it is assigned, squeezing the
        statistics panel next to it (that one sits in a QScrollArea and
        yields height instead of demanding it, so it lost every time and
        only 2 of 3 channel cards stayed visible).

        Splitting them lets MainWindow place each where it belongs -- the
        log next to the history table, the controls as a short strip -- the
        same accessor pattern DataPanelWidget already uses for its
        realtime/history groups. Every public method here
        (``append_activity``/``show_alarm``/``activity_count``/the signals)
        is unchanged, so nothing that already drove this widget had to move.
        """
        controls = QGroupBox("调试控制")
        controls.setObjectName("controlGroup")
        layout = QVBoxLayout()

        # 2026-09-07：这些是调试用操作（订阅通道、控制权、发送裸命令），在日常
        # 演示中处于边缘地位，却一直占着底部一整格。改为默认折叠——功能一个不删，
        # 只是收起来。演示相关的控制另有 VentilationPanelWidget 承担，两类控制按
        # 角色分开，而不是一起缩小。
        self._toggle_button = QToolButton()
        self._toggle_button.setObjectName("controlToggle")
        self._toggle_button.setCheckable(True)
        self._toggle_button.setChecked(False)
        self._toggle_button.setText(_COLLAPSED_TEXT)
        self._toggle_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        layout.addWidget(self._toggle_button)

        body_layout = QVBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)

        subscribe_row = QHBoxLayout()
        subscribe_row.addWidget(self._channel_input)
        subscribe_row.addWidget(self._subscribe_button)
        subscribe_row.addWidget(self._unsubscribe_button)
        body_layout.addLayout(subscribe_row)

        control_row = QHBoxLayout()
        control_row.addWidget(self._acquire_button)
        control_row.addWidget(self._release_button)
        body_layout.addLayout(control_row)

        command_row = QHBoxLayout()
        command_row.addWidget(self._cmd_type_combo)
        command_row.addWidget(self._custom_command_edit)
        command_row.addWidget(self._send_command_button)
        body_layout.addLayout(command_row)

        self._controls_body = QWidget()
        self._controls_body.setLayout(body_layout)
        self._controls_body.setVisible(False)
        layout.addWidget(self._controls_body)
        controls.setLayout(layout)
        # 只占内容所需的高度。此前这里有一句 addStretch(1)，本意是把按钮顶到上方，
        # 实际效果相反——它让整个分组主动向下伸展，底部空出约 78px（实测 223px 高
        # 而内容只需 145px），比拆分前还占地方。控制是辅助功能，不该争空间。
        controls.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )
        self._controls_group = controls

        log_box = QGroupBox("活动日志")
        log_box.setObjectName("activityGroup")
        log_layout = QVBoxLayout()
        log_layout.addWidget(self._activity_log)
        log_box.setLayout(log_layout)
        self._activity_group = log_box

        # 默认仍把两块竖着装在自己身上，这样单独使用本控件（含既有测试）
        # 的行为不变；MainWindow 会改用下面两个访问器分开摆放。
        outer = QVBoxLayout()
        outer.addWidget(controls)
        outer.addWidget(log_box, stretch=1)
        self.setLayout(outer)

    def controls_group(self) -> QGroupBox:
        """The debug-controls box, for placing independently.

        Collapsed by default -- see :meth:`set_controls_expanded`.
        """
        return self._controls_group

    def set_controls_expanded(self, expanded: bool) -> None:
        """Show or hide the debug controls, keeping the toggle in sync.

        Exposed so a caller (or a test) can drive the state directly
        rather than having to synthesize a click.
        """
        self._toggle_button.setChecked(expanded)
        self._apply_controls_expanded(expanded)

    def controls_expanded(self) -> bool:
        """Whether the debug controls are set to show.

        Uses ``isHidden()`` rather than ``isVisible()`` on purpose: a child
        widget reports ``isVisible() == False`` whenever its window has not
        been shown yet, which would make this answer "collapsed" for a
        panel that is merely off-screen (as in every widget test).
        ``isHidden()`` reflects only whether it was explicitly hidden.
        """
        return not self._controls_body.isHidden()

    def _apply_controls_expanded(self, expanded: bool) -> None:
        self._controls_body.setVisible(expanded)
        self._toggle_button.setText(_EXPANDED_TEXT if expanded else _COLLAPSED_TEXT)

    def activity_group(self) -> QGroupBox:
        """The activity-log box, for placing independently."""
        return self._activity_group

    def _wire_internal_signals(self) -> None:
        self._toggle_button.toggled.connect(self._apply_controls_expanded)
        self._subscribe_button.clicked.connect(self._emit_subscribe)
        self._unsubscribe_button.clicked.connect(self._emit_unsubscribe)
        self._acquire_button.clicked.connect(self._emit_acquire)
        self._release_button.clicked.connect(self._emit_release)
        self._send_command_button.clicked.connect(self._emit_send_command)
        self._cmd_type_combo.currentIndexChanged.connect(
            self._on_command_type_changed
        )

    def set_channel_options(self, channels: list[str]) -> None:
        """Replace the channel suggestions with the selected device's own.

        The combo stays editable -- the platform fixes no channel-id enum,
        and a device may report a channel it did not declare. But the
        *offered* list must come from the device, because offering a
        channel it does not have produces a subscription that succeeds and
        then delivers nothing forever (see DeviceStatusView.channels).

        An empty list leaves the generic presets in place rather than
        blanking the control, so a device that declares no capability is
        still operable.
        """
        current = self._channel_input.currentText().strip()
        options = channels or list(_CHANNEL_ID_PRESETS)
        self._channel_input.blockSignals(True)
        self._channel_input.clear()
        self._channel_input.addItems(options)
        if current in options:
            self._channel_input.setCurrentText(current)
        elif len(options) == 1:
            # One channel: preselect it. Making the only valid choice the
            # default is what turns Simulator mode's三设备一通道 layout from
            # a trap into the obvious thing.
            self._channel_input.setCurrentIndex(0)
        else:
            self._channel_input.setCurrentIndex(-1)
        self._channel_input.blockSignals(False)

    def channel_options(self) -> list[str]:
        """Channel ids currently offered in the combo."""
        return [self._channel_input.itemText(i)
                for i in range(self._channel_input.count())]

    def _emit_subscribe(self) -> None:
        channel_id = self._channel_input.currentText().strip()
        if channel_id:
            self.subscribe_clicked.emit(channel_id)

    def _emit_unsubscribe(self) -> None:
        """"暂停接收": a real unsubscribe (ApiInterface.unsubscribe_data),
        not just a UI display pause -- data for this channel stops
        flowing to this client entirely until "订阅" is clicked again for
        the same channel id (resubscribing is not a separate action)."""
        channel_id = self._channel_input.currentText().strip()
        if channel_id:
            self.unsubscribe_clicked.emit(channel_id)

    def _emit_acquire(self) -> None:
        self.acquire_clicked.emit()

    def _emit_release(self) -> None:
        self.release_clicked.emit()

    def _on_command_type_changed(self, _index: int) -> None:
        """Enable the custom-command input only while CUSTOM is selected;
        otherwise keep it disabled and empty, so a stale custom value from
        an earlier selection can never leak into a later, non-CUSTOM send.
        """
        is_custom = self._cmd_type_combo.currentData() == _CUSTOM_COMMAND_DATA
        self._custom_command_edit.setEnabled(is_custom)
        if not is_custom:
            self._custom_command_edit.clear()

    def _emit_send_command(self) -> None:
        if self._cmd_type_combo.currentData() == _CUSTOM_COMMAND_DATA:
            command_type = self._custom_command_edit.text().strip()
        else:
            command_type = self._cmd_type_combo.currentData()
        if command_type:
            self.send_command_clicked.emit(command_type)

    # -- results, driven by MainWindow in response to MainController signals --

    _STATUS_LABELS = {
        "SUCCESS": "成功",
        "FAILED": "失败",
        "PENDING": "处理中",
        "TIMEOUT": "超时",
    }

    def show_command_result(self, command_id: str, status: str, message: str) -> None:
        status_label = self._STATUS_LABELS.get(status, status)
        text = f"命令 {command_id}：{status_label}"
        if message:
            text += f"（{message}）"
        self._activity_log.addItem(text)

    def show_control_result(self, acquired: bool) -> None:
        text = "已获取控制权" if acquired else "获取控制权失败（已被占用）"
        self._activity_log.addItem(text)

    def show_error(self, message: str) -> None:
        self._activity_log.addItem(f"错误：{message}")

    def append_activity(self, message: str) -> None:
        """Append a plain informational line to the activity log.

        For outcomes that are neither an error nor a command result -- e.g.
        confirming which (device, channel) pair a subscription targeted.
        Kept a passive ``show_*``-style entry point: this widget still never
        calls the controller or the API itself.
        """
        self._activity_log.addItem(message)

    _ALARM_KIND_LABELS = {
        "ABOVE_MAX": "超过上限",
        "BELOW_MIN": "低于下限",
    }

    def show_alarm(
        self, device_id: str, channel: str, value: float, threshold: float, kind: str
    ) -> None:
        """Append a red activity-log entry for one threshold violation.

        Only called for ``triggered=True`` events (see MainWindow's
        ThresholdStatus handling) -- recovery (``triggered=False``) is not
        logged here, only reflected by DataPanelWidget's row color
        clearing, to avoid flooding the log with a line for every single
        normal reading.
        """
        comparison = self._ALARM_KIND_LABELS.get(kind, kind)
        text = (
            f"报警：{device_id}/{channel} {comparison}"
            f"（当前 {value:.2f}，阈值 {threshold:.2f}）"
        )
        item = QListWidgetItem(text)
        item.setForeground(QColor("red"))
        self._activity_log.addItem(item)

    def log_count(self) -> int:
        return self._activity_log.count()
