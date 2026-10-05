"""DataPanelWidget: real-time multi-channel data table + a bounded,
table-based history log.

Corresponds to the phase-2 task's "数据展示" requirement: a real-time
display area (one row per device/channel, updated in place), a history
table (time/device/channel/value/status, bounded so a long demo session
does not grow memory unboundedly, and clearable on demand via
:meth:`clear_history`), and multi-channel support (rows are keyed by
(device_id, channel), so any number of channels display independently).

2026-08-13 dashboard redesign: the real-time table and the history table
now live in *different* dashboard tiers (see ui/main_window.py) --
:meth:`realtime_group`/:meth:`history_group` expose each as its own
QGroupBox for MainWindow to place independently. This widget's own
top-level layout (built in :meth:`_build_layout`) still contains both, so
it keeps behaving as one self-contained widget when constructed and used
standalone (e.g. in this widget's own unit tests) -- MainWindow simply
never adds ``self`` itself into its visible layout, only the two group
boxes it extracts, which Qt reparents automatically. Every existing
public method/attribute (``add_data_point``, ``set_alarm``,
``clear_history``, ``row_count``, ``history_count``, ``_latest_table``,
``_clear_history_button``) is unchanged, so nothing that already depended
on this widget's contract needed to change for the redesign.

2026-08-13 information-hierarchy pass: the real-time table gained a
"单位"/"状态" column (设备/通道/当前值/单位/状态) -- unit text comes from
``ui.channel_display.channel_unit`` (a UI-presentation-only mapping, see
that module's docstring for why it is not, and must never become, part
of protocol/communication), and status text mirrors the same
``_alarm_state`` bookkeeping the history table's "状态" column already
used. The table also gained a taller row height and larger font (see
``ui/theme.py``'s ``QTableWidget#realtimeDataTable`` rule) and the group
box got a minimum height, so temperature/humidity/noise can always be
seen at once without scrolling -- addressing "实时数据（多通道）太小" by
construction, not just by giving it more layout stretch in MainWindow.

The history table's "状态" column reflects each (device_id, channel)'s
*last known* alarm state, tracked purely at this UI layer from
:meth:`set_alarm` calls (already reachable via MainController's existing
``alarm_status_changed`` signal) -- no change to service/api was needed
to add it. Its "时间" column is the local wall-clock time this widget
received the point, not a device-reported timestamp (DataPoint carries
none over the data_received signal); this is disclosed as "接收时间" in
the column header, not claimed as device time.

This widget is a "Passive View": it holds no reference to MainController
or ApiInterface. Its main public entry point, :meth:`add_data_point`,
matches ``ui.controller.MainController.data_received``'s signature
exactly, so MainWindow can connect them directly -- the data still only
ever reaches this widget by MainWindow wiring MainController's signal
(itself sourced from ``ApiInterface.subscribe_data()``), never by calling
SimulatorDevice or any lower layer.
"""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.channel_display import channel_label, channel_unit, format_value

_DEFAULT_HISTORY_LIMIT = 500
_ALARM_BACKGROUND = QBrush(QColor("red"))
_ALARM_FOREGROUND = QBrush(QColor("white"))
_OVER_LIMIT_COLOR = QColor("#E8A33D")
"""History rows over the threshold but not (yet) a confirmed alarm (2026-09-29)."""
_NO_BRUSH = QBrush()

_Status = tuple[str, QColor | None]
"""A history row's 状态 cell: its text and, if not plain, its text colour."""
_NORMAL: _Status = ("正常", None)
_ALARM: _Status = ("报警", QColor("red"))
_OVER_LIMIT: _Status = ("超限", _OVER_LIMIT_COLOR)
_REALTIME_COLUMNS = ["设备", "通道", "当前值", "单位", "状态"]
_HISTORY_COLUMNS = ["接收时间", "数值", "状态"]

#: Channels that get a history column from the start, in display order.
#: Pre-creating them means the history page looks like itself before any
#: data arrives, instead of being blank until the first reading lands.
#: Any other channel still gets a column, created when it first reports
#: (see :meth:`_history_table_for`) -- the platform is channel-agnostic
#: and a reading with nowhere to go would be a silent loss.
_HISTORY_CHANNELS = ("temperature", "humidity", "noise")
_REALTIME_MIN_HEIGHT = 170  # header + 3 full-height rows, never scrolled to be seen


class DataPanelWidget(QWidget):
    """Real-time multi-channel table plus a bounded, table-based history log."""

    def __init__(
        self, history_limit: int = _DEFAULT_HISTORY_LIMIT, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._history_limit = history_limit
        self._row_index: dict[tuple[str, str], int] = {}
        self._alarm_state: dict[tuple[str, str], bool] = {}

        self._latest_table = QTableWidget(0, len(_REALTIME_COLUMNS))
        self._latest_table.setObjectName("realtimeDataTable")
        self._latest_table.setHorizontalHeaderLabels(_REALTIME_COLUMNS)
        horizontal_header = self._latest_table.horizontalHeader()
        if horizontal_header is not None:
            horizontal_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        vertical_header = self._latest_table.verticalHeader()
        if vertical_header is not None:
            vertical_header.setVisible(False)
            vertical_header.setDefaultSectionSize(34)

        # One table per channel, each scrolling on its own. Keyed by
        # channel id; ``_history_titles`` holds each column's group box so
        # the device that feeds it can be named in the title.
        self._history_tables: dict[str, QTableWidget] = {}
        self._last_history_device: dict[str, str] = {}
        """Which device the newest row of each channel's column came from, so a
        reading's threshold verdict is only written onto its own row."""
        self._awaiting_verdict: dict[str, bool] = {}
        """Whether the newest live row of each channel was written before its
        verdict arrived, and so may still be rewritten by it."""
        self._alarm_bands: dict[str, tuple[float | None, float | None]] = {}
        """Nominal (minimum, maximum) per channel, for prefilled rows only."""
        self._pending_verdict: dict[tuple[str, str], tuple[str, _Status]] = {}
        """A verdict that arrived before its reading, keyed by (device,
        channel) and holding (formatted value, status) until the row exists."""
        self._history_titles: dict[str, QGroupBox] = {}
        self._history_devices: dict[str, list[str]] = {}

        self._clear_history_button = QPushButton("清空历史记录")
        self._clear_history_button.clicked.connect(self.clear_history)

        self._build_layout()

    def _build_layout(self) -> None:
        self._realtime_group = QGroupBox("实时数据（多通道）")
        self._realtime_group.setObjectName("realtimeGroup")
        self._realtime_group.setMinimumHeight(_REALTIME_MIN_HEIGHT)
        realtime_layout = QVBoxLayout()
        realtime_layout.addWidget(self._latest_table)
        self._realtime_group.setLayout(realtime_layout)

        history_header = QHBoxLayout()
        history_header.addWidget(
            QLabel(f"（每条通道各自保留最近 {self._history_limit} 条）")
        )
        history_header.addStretch(1)
        history_header.addWidget(self._clear_history_button)

        # 2026-09-18: one column per channel instead of one interleaved
        # table. The old table listed every channel's readings in arrival
        # order, so reading "温度这半小时怎么走的" meant skipping two rows
        # out of every three. Columns are independent on purpose -- they
        # are NOT aligned row-by-row into one timestamped row, because the
        # three channels do not arrive together (about 3.09 s per round,
        # and the three readings within a round are milliseconds apart).
        # Aligning them would mean that one dropped frame silently pairs
        # round N's temperature with round N+1's humidity: every number
        # still true, but the instant it belongs to quietly wrong, and
        # nothing on screen would show it. That is the same failure the
        # 2026-09-09 跨时间问题 was about, and it is not worth the
        # convenience of reading across a row.
        self._history_columns_row = QHBoxLayout()
        for channel_id in _HISTORY_CHANNELS:
            self._history_columns_row.addWidget(self._build_history_column(channel_id))

        self._history_group = QGroupBox("历史记录")
        self._history_group.setObjectName("historyGroup")
        history_layout = QVBoxLayout()
        history_layout.addLayout(history_header)
        history_layout.addLayout(self._history_columns_row, stretch=1)
        self._history_group.setLayout(history_layout)

        layout = QVBoxLayout()
        layout.addWidget(self._realtime_group)
        layout.addWidget(self._history_group, stretch=1)
        self.setLayout(layout)

    def _build_history_column(self, channel_id: str) -> QGroupBox:
        """Build one channel's history column: a titled, scrolling table."""
        table = QTableWidget(0, len(_HISTORY_COLUMNS))
        table.setObjectName("historyTable")
        table.setHorizontalHeaderLabels(_HISTORY_COLUMNS)
        header_view = table.horizontalHeader()
        if header_view is not None:
            header_view.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        vertical_header = table.verticalHeader()
        if vertical_header is not None:
            vertical_header.setVisible(False)

        group = QGroupBox(self._history_column_title(channel_id))
        group.setObjectName("historyColumn")
        layout = QVBoxLayout()
        layout.addWidget(table)
        group.setLayout(layout)

        self._history_tables[channel_id] = table
        self._history_titles[channel_id] = group
        self._history_devices[channel_id] = []
        return group

    def _history_column_title(self, channel_id: str) -> str:
        """"温度 °C", plus the device feeding it once one is known.

        The device goes in the title rather than in a fourth column: with
        three columns sharing the width, "sim-env-1-noise" in a cell is
        elided to nothing useful, while in the title it has the whole
        column to itself. Both modes realistically feed one device per
        channel (hardware: one board reporting all three; simulator:
        three single-channel devices), but if a second one ever shows up
        it is appended rather than hidden -- two devices' readings
        interleaved under one heading with no way to tell them apart
        would be worse than a long title.
        """
        unit = channel_unit(channel_id)
        heading = f"{channel_label(channel_id)} {unit}".strip()
        devices = self._history_devices.get(channel_id) or []
        if not devices:
            return heading
        return f"{heading} · {'、'.join(devices)}"

    def _history_table_for(self, channel_id: str) -> QTableWidget:
        """This channel's history table, creating its column if new."""
        table = self._history_tables.get(channel_id)
        if table is None:
            self._history_columns_row.addWidget(
                self._build_history_column(channel_id)
            )
            table = self._history_tables[channel_id]
        return table

    def _note_history_device(self, channel_id: str, device_id: str) -> None:
        devices = self._history_devices.setdefault(channel_id, [])
        if device_id in devices:
            return
        devices.append(device_id)
        group = self._history_titles.get(channel_id)
        if group is not None:
            group.setTitle(self._history_column_title(channel_id))

    def realtime_group(self) -> QGroupBox:
        """The "实时数据" group box, for MainWindow to place independently
        of :meth:`history_group` in the dashboard layout."""
        return self._realtime_group

    def history_group(self) -> QGroupBox:
        """The "历史记录" group box, for MainWindow to place independently
        of :meth:`realtime_group` in the dashboard layout."""
        return self._history_group

    def add_data_point(self, device_id: str, channel: str, value: str) -> None:
        """Update the real-time row and append a history entry for one data point.

        Signature matches MainController.data_received for direct
        signal/slot connection.
        """
        self._update_latest(device_id, channel, value)
        self._append_history(device_id, channel, value)

    def set_alarm_bands(
        self, bands: dict[str, tuple[float | None, float | None]]
    ) -> None:
        """Remember each channel's nominal alarm bounds for :meth:`prefill_history`."""
        self._alarm_bands = dict(bands)

    def prefill_history(self, device_id: str, channel: str, points: list) -> None:
        """Fill the history table with stored readings, newest on top.

        Separate from :meth:`add_data_point` on purpose: that one is the
        live path and also updates the real-time row, whereas these
        readings are already over. Takes whatever objects carry
        ``value``/``timestamp``/``valid`` rather than importing the
        platform's type -- a widget should not need to know where its
        values came from.

        ``points`` arrives newest-first (the store's contract). Each row is
        inserted at the top, so they are fed oldest-first: the newest one
        goes in last and ends up on top, the same place the live path
        puts every new reading.

        Stored readings carry no verdict, so each row is judged here
        against :meth:`set_alarm_bands` (2026-09-29; before, every one read
        正常, and an 81.50 dB reading from an earlier run showed as normal).
        A row can read "超限" but never "报警": whether it was ever
        confirmed by consecutive readings is not recorded.

        **Replaces the channel's column** (2026-09-29, it used to append).
        The store already holds every reading the column showed, so
        replacing loses nothing; appending on a second fill -- "暂停接收"
        then "订阅" again -- duplicated each row, and with the newest row on
        top it also put the stored older readings above the live newer ones.
        """
        table = self._history_tables.get(channel)
        if table is not None:
            table.setRowCount(0)
        self._awaiting_verdict.pop(channel, None)
        for point in reversed(points):
            moment = point.timestamp.astimezone()
            self._insert_history_row(
                moment.strftime("%H:%M:%S"),
                device_id,
                channel,
                point.value,
                status=self._stored_status(channel, point.value),
            )

    def _stored_status(self, channel: str, value: object) -> _Status:
        band = self._alarm_bands.get(channel)
        if band is None or isinstance(value, bool):
            return _NORMAL
        if not isinstance(value, int | float):
            return _NORMAL
        minimum, maximum = band
        if (maximum is not None and value > maximum) or (
            minimum is not None and value < minimum
        ):
            return _OVER_LIMIT
        return _NORMAL

    def set_reading_status(
        self,
        device_id: str,
        channel: str,
        value: float,
        threshold: float,
        kind: str,
        triggered: bool,
    ) -> None:
        """Put one reading's threshold verdict on that reading's history row.

        Added 2026-09-29, after a screenshot showed
        "87.60 正常" in the noise column: **a lone spike is not an alarm by
        design** -- the processor wants ``DEFAULT_CONFIRM_CYCLES`` readings
        in a row -- but the column said only 正常 or 报警, so the reader
        could not tell "below the limit" from "over it once, not
        confirmed". Such rows now read "超限" in amber; "报警" stays for a
        confirmed alarm.

        **Neither arrival order is assumed.** The first version of this
        method (same day) believed the reading always reached this widget
        before its verdict and rewrote the newest row; its unit tests
        called the two in that order and passed. In the real stack it is
        the other way round -- ``SensorDataProcessor`` subscribes to the
        data when the runtime is built, before the UI does, so
        ``alarm_status_changed`` fires first -- and on hardware "超限" never
        appeared (104.90 dB read 正常 at 15:10:08). Now:

        - the newest row is still waiting for its verdict (reading came
          first): rewrite it, if it is from the same device and shows the
          same value;
        - otherwise (verdict came first): hold it until the reading arrives,
          and :meth:`_append_history` writes the row with it.

        Holding instead of matching the newest row by value matters: two
        equal readings in a row (humidity "63", "63") would otherwise let
        the second reading's verdict overwrite the first one's row.
        """
        status = _verdict_status(value, threshold, kind, triggered)
        formatted = format_value(value, channel)
        table = self._history_tables.get(channel)
        if (
            table is not None
            and table.rowCount() > 0
            and self._awaiting_verdict.get(channel, False)
            and self._last_history_device.get(channel) == device_id
        ):
            row = 0  # the newest row is on top
            value_item = table.item(row, 1)
            if value_item is not None and value_item.text() == formatted:
                table.setItem(row, 2, _status_item(status))
                self._awaiting_verdict[channel] = False
                return
        self._pending_verdict[(device_id, channel)] = (formatted, status)

    def set_alarm(self, device_id: str, channel: str, active: bool) -> None:
        """Highlight (``active=True``) or clear (``active=False``) the
        (device, channel) row's alarm styling, and remember the state for
        future history rows' "状态" column.

        Highlighting is a no-op if that row isn't currently tracked (e.g.
        an alarm fired for a channel the user hasn't subscribed to
        display -- see MainWindow's alarm handling): there is no row to
        highlight, and the activity log (ControlPanelWidget.show_alarm)
        is the authoritative notification regardless. The remembered
        state is kept either way, so a channel that starts alarming
        before it is ever displayed still shows "报警" in its history
        once it is.
        """
        self._alarm_state[(device_id, channel)] = active
        row = self._row_index.get((device_id, channel))
        if row is None:
            return
        status_item = self._latest_table.item(row, 4)
        if status_item is not None:
            status_item.setText("报警" if active else "正常")
        background = _ALARM_BACKGROUND if active else _NO_BRUSH
        foreground = _ALARM_FOREGROUND if active else _NO_BRUSH
        for col in range(self._latest_table.columnCount()):
            item = self._latest_table.item(row, col)
            if item is not None:
                item.setBackground(background)
                item.setForeground(foreground)

    def clear_history(self) -> None:
        """Clear the displayed history only -- **the database is untouched**.

        The real-time table (current values per channel) is left alone
        too, since that reflects live state rather than history.

        Until 2026-09-17 this docstring said there was "nothing for a
        backend to persist or forget here", which was true while history
        existed only inside this widget. It is no longer: readings are
        persisted (see docs/decisions/06-history.md).
        The button's meaning is therefore deliberately narrowed to "clear
        what I am looking at" -- deleting stored data is a separate,
        destructive action and must not hide behind a button labelled
        清空历史记录. Re-opening the window shows the readings again.
        """
        for table in self._history_tables.values():
            table.setRowCount(0)
        self._awaiting_verdict.clear()

    def row_count(self) -> int:
        """Number of distinct (device, channel) rows currently tracked."""
        return self._latest_table.rowCount()

    def history_count(self) -> int:
        """Total displayed history entries across every channel column."""
        return sum(table.rowCount() for table in self._history_tables.values())

    def history_count_for(self, channel_id: str) -> int:
        """Displayed history entries in one channel's column."""
        table = self._history_tables.get(channel_id)
        return 0 if table is None else table.rowCount()

    def _update_latest(self, device_id: str, channel: str, value: str) -> None:
        key = (device_id, channel)
        row = self._row_index.get(key)
        if row is None:
            is_alarm = self._alarm_state.get(key, False)
            row = self._latest_table.rowCount()
            self._latest_table.insertRow(row)
            self._latest_table.setItem(row, 0, QTableWidgetItem(device_id))
            self._latest_table.setItem(row, 1, QTableWidgetItem(channel))
            self._latest_table.setItem(
                row, 2, QTableWidgetItem(format_value(value, channel))
            )
            self._latest_table.setItem(row, 3, QTableWidgetItem(channel_unit(channel)))
            self._latest_table.setItem(
                row, 4, QTableWidgetItem("报警" if is_alarm else "正常")
            )
            self._row_index[key] = row
        else:
            item = self._latest_table.item(row, 2)
            if item is not None:  # always set when the row was created, above
                item.setText(format_value(value, channel))

    def _append_history(self, device_id: str, channel: str, value: str) -> None:
        key = (device_id, channel)
        pending = self._pending_verdict.pop(key, None)
        if pending is not None and pending[0] == format_value(value, channel):
            status = pending[1]
            awaiting = False
        else:
            # No verdict for this reading yet: write the last known state and
            # let set_reading_status() correct it when the verdict comes.
            status = _ALARM if self._alarm_state.get(key, False) else _NORMAL
            awaiting = True
        self._insert_history_row(
            datetime.now().strftime("%H:%M:%S"),
            device_id,
            channel,
            value,
            status=status,
        )
        self._awaiting_verdict[channel] = awaiting

    def _insert_history_row(
        self,
        received_at: str,
        device_id: str,
        channel: str,
        value: object,
        *,
        status: _Status,
    ) -> None:
        """Add one row at the top of ``channel``'s column and enforce its cap.

        Shared by the live path and :meth:`prefill_history` so the two
        cannot drift in column order or in how the cap is applied.

        The cap is **per column** (2026-09-18, was per table): each
        channel keeps its own most recent ``history_limit`` readings.
        Under one shared cap the three channels competed for it, so
        looking back over one channel meant seeing only a third as far.

        **Newest on top** (2026-09-29, was appended at the bottom): the
        reading one wants most is the latest, and at the bottom it sat
        under a scrollbar that had to be dragged down on every visit. The
        cap therefore drops the bottom (oldest) row.
        """
        table = self._history_table_for(channel)
        self._note_history_device(channel, device_id)
        self._last_history_device[channel] = device_id

        table.insertRow(0)
        table.setItem(0, 0, QTableWidgetItem(received_at))
        table.setItem(0, 1, QTableWidgetItem(format_value(value, channel)))
        table.setItem(0, 2, _status_item(status))

        while table.rowCount() > self._history_limit:
            table.removeRow(table.rowCount() - 1)


def _verdict_status(
    value: float, threshold: float, kind: str, triggered: bool
) -> _Status:
    """正常 / 超限 (over the limit, not confirmed) / 报警 (confirmed)."""
    if triggered:
        return _ALARM
    over = value > threshold if kind == "ABOVE_MAX" else value < threshold
    return _OVER_LIMIT if over else _NORMAL


def _status_item(status: _Status) -> QTableWidgetItem:
    text, color = status
    item = QTableWidgetItem(text)
    if color is not None:
        item.setForeground(color)
    return item
