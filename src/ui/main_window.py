"""MainWindow: PC Presentation Layer -- 2026-08-13 dashboard redesign.

Corresponds to .claude/skills/pyqt6-ui-development-rules: MVC separation,
signal/slot communication, layout managers instead of absolute pixel
coordinates (Iron Laws 1 and 4). Composes the dashboard widgets
(ui.widgets.TopBarWidget / MetricCardWidget / ChartWidget /
DataPanelWidget / StatisticsPanelWidget / StatusBannerWidget /
DevicePanelWidget / DeviceListItemWidget / ControlPanelWidget) into an
industrial-monitoring-style layout, replacing the previous
"several GroupBoxes side by side" arrangement:

    背景: BackgroundWidget（*is* the central widget itself -- see
          _build_layout; paints the background image + dark overlay,
          everything below is laid out on top of it)
    顶部: TopBarWidget (title / selected device / connection / mode / clock)
    第一层: 3 个 MetricCardWidget（temperature/humidity/noise 核心指标）
    第二层: ChartWidget，页面最大的区域
    第三层: DataPanelWidget.realtime_group() + StatisticsPanelWidget
    第四层: StatusBannerWidget + DataPanelWidget.history_group()，
            旁边是视觉上被弱化（不占主要空间）的 ControlPanelWidget

This redesign is **purely visual/structural**: every signal MainController
already emits (devices_changed/device_status_changed/data_received/
control_acquired/command_result_ready/error_occurred/
alarm_status_changed/statistics_changed) and every signal the view emits
back to it (subscribe_clicked/unsubscribe_clicked/acquire_clicked/
release_clicked/send_command_clicked, plus this window's own plain method
calls to MainController) are wired exactly as before -- MainController's
public interface was not touched to build this.

The device list keeps being a plain ``QListWidget`` internally (selection,
``currentTextChanged``, ``item(i).text()``, row count all still behave
exactly as before) -- ``DeviceListItemWidget`` instances are attached via
``setItemWidget()`` purely for card-style *rendering*, never replacing
the underlying list/selection model.

MainWindow imports ``ui.controller.MainController``, ``ui.widgets``,
``ui.theme`` (only its plain presentation helpers -- ``set_class``, a
same-layer ui/ -> ui/ dependency, not a boundary violation), and PyQt6 --
it never imports `api`, `application`, `service`, `device`,
`communication`, or `protocol`. All data reaches this class through
MainController's Qt signals (itself the only file allowed to import
`api`); every user action leaves this class as a plain call to one of
MainController's methods, or is emitted by a child widget as a plain Qt
signal that MainWindow relays to MainController.

Run mode display ("模拟模式"/"硬件模式"): ``ui/`` is architecturally
never supposed to know *how* Hardware mode is wired (SerialChannel/
HardwareDeviceReceiver never appear here) -- ``mode_label`` is an inert,
caller-supplied display string (scripts/run_gui.py already knows
``--mode`` from its own CLI args) with a default, so every existing
``MainWindow(controller)`` call site keeps working unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui.controller import MainController
from ui.theme import ACCENT, SECONDARY_BLUE, SECONDARY_PURPLE, set_class
from ui.widgets import (
    AssistantPanelWidget,
    BackgroundWidget,
    ChartWidget,
    ControlPanelWidget,
    DataPanelWidget,
    DeviceListItemWidget,
    DevicePanelWidget,
    FanCardWidget,
    MetricCardWidget,
    StatisticsPanelWidget,
    StatusBannerWidget,
    TopBarWidget,
    VentilationPanelWidget,
)
from ui.widgets.ventilation_panel import mode_label as fan_mode_label

# Convenience presets only, matching the precedent already established by
# ui/widgets/control_panel.py's _CHANNEL_ID_PRESETS: these three channel
# ids are not bound to any channel enum, and ui/ still does not import
# device/sensors/channels.py -- this is the current sensor-simulation
# scenario's known set, used purely to build the three metric cards and
# to render a friendly label in alarm messages.
_METRIC_CHANNELS = (
    ("temperature", "温度", "°C", ACCENT),
    ("humidity", "湿度", "%", SECONDARY_BLUE),
    ("noise", "噪声", "dB", SECONDARY_PURPLE),
)
_CHANNEL_LABELS = {channel_id: label for channel_id, label, _, _ in _METRIC_CHANNELS}


class MainWindow(QMainWindow):
    """Dashboard main window: top bar, metric cards, chart, data,
    statistics, status banner, history, device list, and controls."""

    def __init__(
        self, controller: MainController, mode_label: str = "模拟模式"
    ) -> None:
        super().__init__()
        self._controller = controller
        self._selected_device_id: str | None = None
        self._device_list_items: dict[str, DeviceListItemWidget] = {}

        self.setWindowTitle("嵌入式设备上位机平台")

        self._top_bar = TopBarWidget()
        self._top_bar.set_mode(mode_label)
        self._page_stack = QStackedWidget()
        self._page_shortcuts: list[QShortcut] = []

        self._device_list = QListWidget()
        self._refresh_button = QPushButton("刷新设备")
        self._device_panel = DevicePanelWidget()
        self._control_panel = ControlPanelWidget()
        self._ventilation_panel = VentilationPanelWidget()
        self._fan_card = FanCardWidget()
        self._assistant_panel = AssistantPanelWidget()
        self._chart = ChartWidget()
        self._data_panel = DataPanelWidget()
        self._statistics_panel = StatisticsPanelWidget()
        self._status_banner = StatusBannerWidget()
        self._metric_cards: dict[str, MetricCardWidget] = {
            channel_id: MetricCardWidget(label, channel_id, unit, color)
            for channel_id, label, unit, color in _METRIC_CHANNELS
        }

        self._build_layout()
        self._wire_signals()

        self._controller.refresh_devices()
        # Show the platform's real ventilation settings rather than the
        # panel's own widget defaults, which would otherwise silently
        # disagree with what the service layer actually holds.
        self._controller.refresh_ventilation_settings()

    # -- layout (Iron Law 4: layout managers, never absolute coordinates) -

    def _build_layout(self) -> None:
        # BackgroundWidget (not a plain QWidget) *is* the central widget:
        # it paints the background image + dark overlay itself in its own
        # paintEvent, then every widget placed into root_layout below
        # paints on top of that automatically (normal Qt child-painting
        # order) -- see ui/widgets/background_widget.py's module
        # docstring for the full explanation of why this alone is enough
        # to make the image show only through panel gaps, never behind
        # panel content.
        central = BackgroundWidget()
        root_layout = QVBoxLayout()
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._top_bar)

        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(12, 12, 12, 12)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_device_column())
        splitter.addWidget(self._build_dashboard_column())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        body_layout.addWidget(splitter)

        root_layout.addLayout(body_layout, stretch=1)

        central.setLayout(root_layout)
        self.setCentralWidget(central)

    def _build_device_column(self) -> QWidget:
        title = QLabel("设备列表")
        set_class(title, "section-title")

        layout = QVBoxLayout()
        layout.addWidget(title)
        layout.addWidget(self._device_list, stretch=1)
        layout.addWidget(self._refresh_button)
        layout.addWidget(self._device_panel)

        widget = QWidget()
        widget.setLayout(layout)
        widget.setMinimumWidth(220)
        widget.setMaximumWidth(320)
        return widget

    def _build_dashboard_column(self) -> QWidget:
        """The dashboard: a always-visible status banner over two pages.

        2026-09-18: 历史记录 moved onto a page of its own. It used to sit
        in the bottom row's left column, which multiplied out to roughly
        **9% of the dashboard's area for a five-column table** (vertical
        3/8 for that row, then horizontal 3/10 within it, minus the
        banner's height). Re-balancing stretch cannot fix that, and had
        already been tried twice: the 2026-08-18 pass gave the row its
        height back, and 2026-09-08 raised it again for the Q&A panel --
        both notes below. The row's other three occupants all genuinely
        want that space, so widening the table is zero-sum. Paging is the
        way out, and it is the same move the on-board LCD made for the
        same reason (命令码 0x16, 两页) -- except here it costs nothing
        below the view: no protocol change, no firmware, no api/service
        method. :meth:`_build_history_page` explains why the table needs
        no re-fetch when the page comes forward.

        The status banner stays **outside** the stack, above both pages.
        Its whole point is being recognisable in 1-2 seconds (see
        StatusBannerWidget's module docstring); a system-state indicator
        that disappears when you page away from it would not be one.

        Vertical space priority within the realtime page is unchanged
        (2026-08-13 information-hierarchy pass): chart and 实时数据+统计信息
        are both ★★★★★/★★★★☆ -- given near-equal stretch (3:3) so
        neither dominates the other; the alarm/control row is lower
        priority (★★★☆☆ and below) and gets proportionally less.
        """
        self._page_stack.addWidget(self._build_realtime_page())
        self._page_stack.addWidget(self._build_history_page())
        # One count, asserted rather than assumed: the switcher's labels
        # live in top_bar._PAGES and the pages are built here, so a page
        # added in one place without the other is caught at startup
        # instead of showing as a button that switches to nothing.
        assert self._page_stack.count() == self._top_bar.page_count(), (
            "页签数与页面数不一致：top_bar._PAGES 与 _build_dashboard_column "
            "必须同步"
        )

        layout = QVBoxLayout()
        layout.addWidget(self._status_banner)
        layout.addWidget(self._page_stack, stretch=1)

        widget = QWidget()
        widget.setLayout(layout)
        return widget

    def _build_realtime_page(self) -> QWidget:
        """Page 1: metric cards, chart, live data, statistics, Q&A,
        activity log and controls -- the dashboard as it was, less the
        history table and the status banner that both moved out."""
        layout = QVBoxLayout()
        # 2026-08-18 重新分配。原为 3:3:1，但那是在统计卡片竖排、控制面板带
        # 活动日志的形态下定的：数据+统计一行拿了 3/7 却装不满（表格 3 行、
        # 统计 3 张横排卡片都很矮），底部一行只有 1/7 又把历史记录压到只剩一行。
        # 统计卡改横排、控制面板收缩之后，把多余的高度还给曲线与历史记录。
        layout.addLayout(self._build_metric_row())
        layout.addWidget(self._build_chart_card(), stretch=3)
        layout.addLayout(self._build_data_and_stats_row(), stretch=2)
        # 2026-09-08: 底部一行由 2 提到 3。环境问答面板加进这一行之后，
        # 原来的高度只够显示两三条消息——问答要能读一段对话才有意义，
        # 而这一行里其余三块（历史表、活动日志、通风控制）本来就都是
        # 可滚动或短控件，多出来的高度它们能用上、不用也不浪费。
        # 2026-09-18: 历史表已移到第二页，这一行的高度不再改动——腾出的
        # 是*宽度*，由留下的三块按原比例分掉，见 _build_alarm_and_control_row。
        layout.addLayout(self._build_alarm_and_control_row(), stretch=3)

        widget = QWidget()
        widget.setLayout(layout)
        return widget

    def _build_history_page(self) -> QWidget:
        """Page 2: the history table, alone, filling the page.

        **No re-fetch when this page comes forward, on purpose.** The
        table is kept current by the live path: ``data_received`` ->
        ``DataPanelWidget.add_data_point`` appends to it whether or not
        it is the visible page, and the stored readings were already
        pulled in once per subscription (see
        :meth:`_prefill_channel_history`). Calling ``load_history`` again
        here would *append* a second copy of every stored row --
        ``prefill_history`` appends, it does not replace -- so a user
        paging back and forth would silently grow duplicates. If a
        deliberate refresh is ever wanted, it needs a replace-mode fill
        in the widget first; that is a separate change, not a free one.
        """
        layout = QVBoxLayout()
        layout.addWidget(self._data_panel.history_group(), stretch=1)

        widget = QWidget()
        widget.setLayout(layout)
        return widget

    def _build_metric_row(self) -> QHBoxLayout:
        """Top row: the three sensor metric cards plus the fan state card.

        The fan card sits here rather than with the ventilation controls
        because it reacts to the temperature and humidity beside it --
        putting cause and effect on one line is what makes the behaviour
        legible at a glance. Its controls stay in the panel row below (see
        :meth:`_build_alarm_and_control_row`).
        """
        row = QHBoxLayout()
        for card in self._metric_cards.values():
            row.addWidget(card)
        row.addWidget(self._fan_card)
        return row

    def _build_chart_card(self) -> QFrame:
        title = QLabel("实时曲线")
        set_class(title, "section-title")

        layout = QVBoxLayout()
        layout.addWidget(title)
        layout.addWidget(self._chart, stretch=1)

        card = QFrame()
        card.setObjectName("chartCard")
        card.setLayout(layout)
        return card

    def _build_data_and_stats_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(self._data_panel.realtime_group(), stretch=3)
        row.addWidget(self._statistics_panel, stretch=2)
        return row

    def _build_alarm_and_control_row(self) -> QHBoxLayout:
        """Bottom row: activity log | Q&A | ventilation + controls.

        2026-08-18 rebalance. The control panel used to occupy this row's
        whole right third as one tall block, and because its stacked
        children each carry a minimum height it inflated the row well past
        its 1/7 stretch -- at the cost of the statistics panel above, which
        scrolls and therefore yields height instead of demanding it (only
        2 of 3 channel cards stayed visible).

        The two halves of that block have very different value: the
        activity log is where threshold alarms appear in red and is watched
        constantly, while acquire/release control and command dispatch are
        occasional operations. So the log moves out beside the history
        table, and only the short controls strip stays on the right. The
        controls are kept -- they are the sole UI evidence for functional
        requirements F8 (占用状态) and F9 (控制指令下发); shrinking them is
        the point, removing them would leave those requirements
        unsupported.

        2026-09-07 follow-up. Ventilation added a second kind of control,
        and the two are not equal: adjusting a ventilation threshold is a
        demonstration step performed in front of an audience, while
        acquire/release and raw command dispatch are debugging aids. So
        they are separated by role rather than shrunk together -- the
        debug controls collapse (see
        ControlPanelWidget.set_controls_expanded, default collapsed) and
        the space goes to VentilationPanelWidget. The fan's resulting
        *state* is not here at all: it sits in the metric row beside the
        temperature and humidity that drive it, see
        :meth:`_build_metric_row`.

        2026-09-18 paging. Two of this row's four occupants left: the
        history table moved to its own page and the status banner moved
        above the stack (both explained in
        :meth:`_build_dashboard_column`). The three that stay keep their
        old stretch values rather than being re-tuned, so the freed width
        is divided in the proportion already decided -- the activity log
        goes 2/10 -> 2/7 of the row and the Q&A panel 3/10 -> 3/7, which
        is the same ordering as before, just larger. Re-picking numbers
        here would have thrown away two earlier passes' worth of
        reasoning for no stated reason.
        """
        right_column = QVBoxLayout()
        right_column.addWidget(self._ventilation_panel.group())
        right_column.addWidget(self._control_panel.controls_group())
        right_column.addStretch(1)
        right_widget = QWidget()
        right_widget.setLayout(right_column)

        row = QHBoxLayout()
        row.addWidget(self._control_panel.activity_group(), stretch=2)
        row.addWidget(self._assistant_panel, stretch=3)
        row.addWidget(right_widget, stretch=2)
        return row

    def show_page(self, index: int) -> None:
        """Switch the dashboard to page ``index`` and sync the switcher.

        The single place a page change happens, whichever way it was
        asked for (header button or Ctrl+1/Ctrl+2) -- otherwise a
        shortcut would move the stack while the buttons still showed the
        old page. Out-of-range indexes are ignored rather than raising:
        the stack would refuse them anyway, and a header that has stopped
        matching the stack is worse than a click that did nothing.
        """
        if not 0 <= index < self._page_stack.count():
            return
        self._page_stack.setCurrentIndex(index)
        self._top_bar.set_current_page(index)

    def current_page(self) -> int:
        """Which dashboard page is showing (0 = 实时监控, 1 = 历史记录)."""
        return self._page_stack.currentIndex()

    def append_activity(self, message: str) -> None:
        """Put one line in the activity log.

        Exposed so the composition root can report what a button it
        installed actually did, without reaching into ``_control_panel``
        from outside the view. Same role the alarm and remote-command
        lines already play: the log is where "something happened" is
        visible next to everything else that happened.
        """
        self._control_panel.append_activity(message)

    def set_cloud_view_runner(self, runner: Callable[[], None]) -> None:
        """Install what the 「查看云端归档」 button does (2026-09-19).

        Same shape as :meth:`set_cloud_sync_runner`, and installed the
        same way for the same reason: the work behind it is a subprocess,
        which ``ui`` must not create or name. That this one only *reads*
        does not change where it belongs -- the line is "who starts a
        subprocess", not "how dangerous is it".
        """
        self._assistant_panel.set_action_handler("cloud_view", runner)

    def set_cloud_sync_runner(self, runner: Callable[[], None]) -> None:
        """Install what the 「导出并上传」 button does (2026-09-18).

        Pushed in by the composition root, the same way
        :meth:`set_assistant_model_status` is, and for a stronger version
        of the same reason: uploading launches ``scripts/cloud_sync.py``
        as a subprocess, and ``ui`` must not create -- or even name -- a
        thing like that (``CLAUDE.md`` 架构原则). What arrives here is a
        plain callable; this window knows only that clicking calls it.

        Not installing one is a normal state: the button then never
        appears, and the assistant's answer still says how many time
        slots are waiting. Launchers with no desktop never reach this
        method at all.
        """
        self._assistant_panel.set_action_handler("cloud_sync", runner)

    def set_assistant_model_status(self, available: bool, detail: str = "") -> None:
        """Tell the Q&A panel whether a language model was attached.

        Called once by the composition root, which is the only place that
        knows -- probing a model server is not something a view can or
        should do.
        """
        self._assistant_panel.set_model_status(available, detail)

    # -- signal/slot wiring (Iron Law 1) -------------------------------

    def _wire_signals(self) -> None:
        # Page switching is view-internal: the header asks, this window
        # switches. No controller call, because which page is showing is
        # not something the application layer has an opinion about.
        self._top_bar.page_selected.connect(self.show_page)
        for index in range(self._page_stack.count()):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self)
            shortcut.activated.connect(lambda i=index: self.show_page(i))
            # Parented to self so the shortcut dies with the window; kept
            # in a list as well because QShortcut objects that only the C++
            # parent holds have been an easy thing to lose track of.
            self._page_shortcuts.append(shortcut)

        # Environment assistant: view -> controller (question), then
        # controller -> view (answer). The answer signal may fire twice
        # for one question -- once with the template answer, once more
        # if a language model finishes a rephrasing -- and the panel
        # replaces rather than appends on the second (see
        # AssistantPanelWidget.append_answer).
        self._assistant_panel.question_submitted.connect(self._controller.ask)
        self._controller.assistant_answered.connect(
            self._assistant_panel.append_answer
        )

        # controller -> view (direct connections where signal/slot signatures match)
        self._controller.devices_changed.connect(self._on_devices_changed)
        self._controller.device_channels_changed.connect(
            self._on_device_channels_changed
        )
        self._controller.device_status_changed.connect(
            self._on_device_status_changed
        )
        self._controller.data_received.connect(self._data_panel.add_data_point)
        self._controller.history_loaded.connect(self._data_panel.prefill_history)
        self._controller.data_received.connect(self._on_data_received_for_chart)
        self._controller.data_received.connect(
            self._on_data_received_for_metric_card
        )
        self._controller.control_acquired.connect(self._on_control_acquired)
        self._controller.command_result_ready.connect(
            self._control_panel.show_command_result
        )
        self._controller.error_occurred.connect(self._control_panel.show_error)
        self._controller.error_occurred.connect(self._status_banner.show_warning)
        self._controller.alarm_status_changed.connect(self._on_alarm_status_changed)
        self._controller.statistics_changed.connect(
            self._statistics_panel.update_statistics
        )
        self._controller.fan_decision_changed.connect(self._on_fan_decision_changed)
        self._controller.ventilation_settings_changed.connect(
            self._ventilation_panel.set_settings
        )
        self._controller.remote_activity.connect(
            self._control_panel.append_activity
        )

        # view -> controller
        self._device_list.currentTextChanged.connect(self._on_device_selected)
        self._refresh_button.clicked.connect(self._controller.refresh_devices)
        self._control_panel.subscribe_clicked.connect(self._on_subscribe_clicked)
        self._control_panel.unsubscribe_clicked.connect(self._on_unsubscribe_clicked)
        self._control_panel.acquire_clicked.connect(self._on_acquire_clicked)
        self._control_panel.release_clicked.connect(self._on_release_clicked)
        self._control_panel.send_command_clicked.connect(self._on_send_command_clicked)
        self._ventilation_panel.thresholds_changed.connect(
            self._controller.set_ventilation_thresholds
        )
        self._ventilation_panel.mode_changed.connect(self._controller.set_fan_mode)

    # -- slots: controller -> view ----------------------------------

    def _on_devices_changed(self, device_ids: list[str]) -> None:
        self._device_list.clear()
        self._device_list_items.clear()
        for device_id in device_ids:
            item = QListWidgetItem(device_id)
            # 文字必须留在 item 上——`currentTextChanged` 与测试里的
            # `item(i).text()` 都依赖它；但它同时会被列表自己的 delegate 画出来，
            # 与叠加在上面的 DeviceListItemWidget 里的同一个 device_id 重叠。
            # 卡片背景不透明时被盖住看不出来，2026-08-13 面板半透明化之后就透了出来
            # （在为论文截图时发现）。这里让 delegate 用透明色绘制：文字仍在，
            # 只是不可见，选择行为与公开契约都不受影响。
            item.setForeground(QBrush(Qt.GlobalColor.transparent))
            self._device_list.addItem(item)
            card = DeviceListItemWidget(device_id)
            item.setSizeHint(card.sizeHint())
            self._device_list.setItemWidget(item, card)
            self._device_list_items[device_id] = card

    def _on_device_status_changed(
        self, device_id: str, is_connected: bool, is_occupied: bool, occupant: str
    ) -> None:
        self._device_panel.set_status(device_id, is_connected, is_occupied, occupant)
        card = self._device_list_items.get(device_id)
        if card is not None:
            card.set_status(is_connected, is_occupied, occupant)
        self._top_bar.set_device(device_id, is_connected)
        self._status_banner.clear_warning()

    def _on_control_acquired(self, device_id: str, acquired: bool) -> None:
        del device_id  # device_panel is refreshed separately via device_status_changed
        self._control_panel.show_control_result(acquired)

    def _on_data_received_for_chart(
        self, device_id: str, channel: str, value: str
    ) -> None:
        """Adapter: parse the value as a float and feed the chart, or skip it.

        ChartWidget only understands plain (series, float) pairs (see its
        module docstring) -- this is the one place that bridges a
        DataPoint-shaped signal to that generic interface. Non-numeric
        values (e.g. a status string) are simply not charted; they still
        appear in the data panel's table and history.
        """
        try:
            numeric_value = float(value)
        except ValueError:
            return
        self._chart.add_point(f"{device_id}/{channel}", numeric_value)

    def _on_data_received_for_metric_card(
        self, device_id: str, channel: str, value: str
    ) -> None:
        """Adapter: feed the matching metric card (temperature/humidity/
        noise only -- see _METRIC_CHANNELS), same non-numeric-skip
        behavior as the chart adapter."""
        del device_id
        card = self._metric_cards.get(channel)
        if card is None:
            return
        try:
            numeric_value = float(value)
        except ValueError:
            return
        card.update_value(numeric_value, datetime.now().strftime("%H:%M:%S"))

    def _on_alarm_status_changed(
        self,
        device_id: str,
        channel: str,
        value: float,
        threshold: float,
        kind: str,
        triggered: bool,
    ) -> None:
        """Reflect one ThresholdStatus across every view that cares:
        highlight (or clear) the data panel's row, the matching metric
        card's border, and the status banner's overall state; log every
        violation in the activity log (not recoveries -- see
        ControlPanelWidget.show_alarm's docstring)."""
        self._data_panel.set_alarm(device_id, channel, triggered)
        if triggered:
            self._control_panel.show_alarm(device_id, channel, value, threshold, kind)

        card = self._metric_cards.get(channel)
        if card is not None:
            card.set_alarm_state(triggered)

        label = _CHANNEL_LABELS.get(channel, channel)
        comparison = "超过上限" if kind == "ABOVE_MAX" else "低于下限"
        self._status_banner.set_alarm(
            device_id, channel, f"{label}{comparison}", triggered
        )

    def _on_fan_decision_changed(
        self, should_run: bool, reason: str, mode_name: str
    ) -> None:
        """Render the ventilation decision on the fan card.

        Only the card is updated, not the activity log: this signal fires
        for every reading (about once per acquisition cycle), so logging
        it would drown the log that alarms are supposed to stand out in.
        """
        self._fan_card.set_decision(should_run, reason, fan_mode_label(mode_name))

    # -- slots: view -> controller (UI emits to controller, never calls
    # a lower layer directly) ------------------------------------------

    def _on_device_selected(self, device_id: str) -> None:
        if not device_id:
            return
        self._selected_device_id = device_id
        for card in self._device_list_items.values():
            card.set_selected(card.device_id() == device_id)
        self._controller.refresh_device_status(device_id)

    def _on_device_channels_changed(self, device_id: str, channels: list) -> None:
        """Offer only the channels the newly selected device declares."""
        if device_id != self._selected_device_id:
            return
        self._control_panel.set_channel_options([str(c) for c in channels])

    def _prefill_channel_history(self, device_id: str, channel_id: str) -> None:
        """订阅前先把这条通道已存的读数补进历史表。

        放在订阅动作里而不是窗口启动时：启动那一刻还没选设备、也没选通道，
        而"要看哪条通道的历史"恰好与"订阅哪条通道"是同一个决定。
        没有存储或查不到时，`load_history` 走 error_occurred 或发出空列表，
        两种情况都只是历史表空着，不影响订阅本身。
        """
        self._controller.load_history(device_id, channel_id)

    def _on_subscribe_clicked(self, channel_id: str) -> None:
        """Subscribe the *currently selected device*'s ``channel_id``.

        The activity-log line matters more than it looks: a subscription is
        registered as a plain (device_id, channel) pair and nothing
        validates that the channel actually belongs to that device, so
        asking for a channel the selected device does not expose is a
        **silent no-op** -- no error, no data, no feedback. That is easy to
        hit whenever one device does not carry every channel (the simulator
        composes three single-channel devices), and it looks exactly like
        "subscribing is broken". Echoing the pair back makes the mismatch
        visible immediately.
        """
        if not self._selected_device_id:
            self._control_panel.show_error("请先在左侧选择一个设备，再订阅通道")
            return
        self._prefill_channel_history(self._selected_device_id, channel_id)
        self._controller.subscribe(self._selected_device_id, channel_id)
        # 只回显这一对，不再附加说明文字：面板很窄，长句会被截断并逼出一条横向
        # 滚动条（2026-08-18 截图时发现）。把设备与通道显示出来本身就够了——
        # 订错设备时一眼就能看出来，这正是加这行日志的目的。
        self._control_panel.append_activity(
            f"已订阅 {self._selected_device_id} / {channel_id}"
        )

    def _on_unsubscribe_clicked(self, channel_id: str) -> None:
        if self._selected_device_id:
            self._controller.unsubscribe(self._selected_device_id, channel_id)
            self._control_panel.append_activity(
                f"已暂停接收 {self._selected_device_id} / {channel_id}"
            )

    def _on_acquire_clicked(self) -> None:
        if self._selected_device_id:
            self._controller.acquire_control(self._selected_device_id)

    def _on_release_clicked(self) -> None:
        if self._selected_device_id:
            self._controller.release_control(self._selected_device_id)

    def _on_send_command_clicked(self, command_type: str) -> None:
        if self._selected_device_id:
            self._controller.submit_command(self._selected_device_id, command_type)
