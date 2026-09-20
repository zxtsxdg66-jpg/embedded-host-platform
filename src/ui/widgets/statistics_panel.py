"""StatisticsPanelWidget: per-channel running statistics, one compact
card per (device_id, channel).

Corresponds to service.sensor_data_processor.SensorDataProcessor's
statistics capability (current/minimum/maximum/average/sample_count per
(device_id, channel)) finally being surfaced in the UI -- it was computed
all along but had no display until this widget (2026-08-12).

2026-08-13 information-hierarchy pass: replaced the original flat
7-column table (current/min/max/avg/sample_count all packed into one
row) with a scrollable list of per-channel cards -- the current value is
now the single most visually prominent number on each card, with
min/max/average as a compact secondary line and sample count as a small
caption, addressing "统计信息...可读性不足" without changing what data is
shown or how it is computed (SensorDataProcessor is untouched; this
widget only reformats numbers it is handed). Falls back gracefully for
channels outside the known temperature/humidity/noise set (no unit
suffix, raw channel id as the title) -- see ui/channel_display.py.

This widget is a "Passive View", the same pattern as DataPanelWidget: it
holds no reference to MainController or ApiInterface. Its only public
entry point, :meth:`update_statistics`, matches
``ui.controller.MainController.statistics_changed``'s signature exactly,
so MainWindow can connect them directly -- data only ever reaches this
widget by MainWindow wiring MainController's signal (itself sourced from
``ApiInterface.subscribe_statistics()``), never by calling
SensorDataProcessor or any lower layer. ``row_count()`` (kept from the
table-based implementation, same semantics -- number of distinct
(device_id, channel) entries tracked) is unchanged, so nothing that
already depended on this widget's public contract needed to change.

Deliberately a separate widget from DataPanelWidget's real-time table
rather than extra columns bolted onto it: statistics are a distinct
concept (aggregated over a channel's whole history) from the latest-value
table (one live reading), and keeping them apart keeps each widget's
responsibility single.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.channel_display import channel_label, channel_unit
from ui.theme import set_class

# 一张 _StatCard 是四行文字（标题/当前值/极值行/样本数）加上下内边距，
# 再加 QGroupBox 自己的标题与边距——留够这个高度，三通道横排就不会被压到
# 需要滚动才看得全（对应实时数据表 setMinimumHeight(170) 的同一处理）
_MIN_PANEL_HEIGHT = 150


class _StatCard(QFrame):
    """One (device_id, channel)'s statistics: current value (most
    prominent), min/max/average (compact secondary line), sample count
    (small caption)."""

    def __init__(
        self, device_id: str, channel: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("statCard")
        self._unit = channel_unit(channel)

        self._title_label = QLabel(f"{channel_label(channel)} · {device_id}")
        set_class(self._title_label, "metric-title")

        self._current_label = QLabel("--")
        set_class(self._current_label, "stat-value")

        # 极值与均值分成两行、且不带单位。原先是"最小 -- · 最大 -- · 平均 --"
        # 挤在一行并各带单位，单张卡片的最小宽度因此高达 440 px，三张横排需要
        # 1356 px 而面板只有 584 px，必然出现横向滚动条（2026-08-18 实测）。
        # 拆成两行并去掉重复的单位后，单卡最小宽度降到面板的三分之一以内。
        self._range_label = QLabel("最小 --   最大 --")
        set_class(self._range_label, "dim")
        self._range_label.setWordWrap(True)

        self._sample_label = QLabel("平均 --   样本 0")
        set_class(self._sample_label, "dim")
        self._sample_label.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addWidget(self._title_label)
        layout.addWidget(self._current_label)
        layout.addWidget(self._range_label)
        layout.addWidget(self._sample_label)
        layout.addStretch(1)
        layout.setSpacing(2)
        layout.setContentsMargins(10, 8, 10, 8)
        self.setLayout(layout)
        # 允许被压缩到与同排卡片均分宽度，而不是坚持自己的自然宽度
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def update_values(
        self,
        current: float,
        minimum: float,
        maximum: float,
        average: float,
        sample_count: int,
    ) -> None:
        unit = self._unit
        self._current_label.setText(f"当前 {current:.2f}{unit}")
        # 极值与均值不再重复单位——单位已在"当前"一行给出，重复会把卡片撑宽
        self._range_label.setText(f"最小 {minimum:.2f}   最大 {maximum:.2f}")
        self._sample_label.setText(f"平均 {average:.2f}   样本 {sample_count}")


class StatisticsPanelWidget(QWidget):
    """One compact card per (device_id, channel), updated in place as new
    statistics arrive; scrolls if the channel/device count grows."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cards: dict[tuple[str, str], _StatCard] = {}

        # 卡片改为**横向**排列（2026-08-18）。此前是竖排 + 滚动条：滚动区会主动
        # 让出高度，而同一行里的控制面板靠子控件的最小高度把行撑高，结果三通道
        # 里只有两张卡可见、噪声要滚动才看得到——为论文截图时发现。横排后三张卡
        # 一行装下，且与上方三张指标卡、实时曲线的三格对齐成同一套三栏结构。
        self._cards_layout = QHBoxLayout()
        self._cards_layout.setSpacing(6)

        cards_container = QWidget()
        cards_container.setLayout(self._cards_layout)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidget(cards_container)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        # 两个方向都不滚动：本项目只有三个通道，统计必须一屏完整可见。
        # 保留 QScrollArea 是为了通道数将来增多时仍有退路（届时改回按需显示即可）。
        self._scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        # QScrollArea's viewport is a separate child widget that Qt gives
        # an opaque palette-Base fill by default (autoFillBackground) --
        # QSS's "QScrollArea { background: transparent }" rule does not
        # reach it, so it would otherwise paint a solid rectangle over the
        # background image even though the surrounding group box is
        # translucent (2026-08-13 panel-transparency rework).
        viewport = self._scroll_area.viewport()
        if viewport is not None:
            viewport.setStyleSheet("background: transparent;")

        self._build_layout()

    def _build_layout(self) -> None:
        box = QGroupBox("统计信息")
        box.setObjectName("statisticsGroup")
        box_layout = QVBoxLayout()
        box_layout.addWidget(self._scroll_area)
        # 与实时数据表同样的做法：硬保证一行卡片（四行文字 + 边距）完整可见，
        # 不依赖布局挤压的运气。此前该面板会被同排的控制面板压到只剩两张卡。
        box.setMinimumHeight(_MIN_PANEL_HEIGHT)
        box.setLayout(box_layout)

        layout = QVBoxLayout()
        layout.addWidget(box)
        self.setLayout(layout)

    def update_statistics(
        self,
        device_id: str,
        channel: str,
        current: float,
        minimum: float,
        maximum: float,
        average: float,
        sample_count: int,
    ) -> None:
        """Create or update the (device_id, channel) card.

        Signature matches MainController.statistics_changed for direct
        signal/slot connection.
        """
        key = (device_id, channel)
        card = self._cards.get(key)
        if card is None:
            card = _StatCard(device_id, channel)
            # 等权加入：同排卡片均分可用宽度，不各自坚持自然宽度
            self._cards_layout.addWidget(card, stretch=1)
            self._cards[key] = card
        card.update_values(current, minimum, maximum, average, sample_count)

    def row_count(self) -> int:
        """Number of distinct (device, channel) cards currently tracked."""
        return len(self._cards)
