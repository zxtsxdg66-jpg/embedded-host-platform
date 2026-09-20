"""TopBarWidget: the dashboard's header strip -- title, page switcher,
selected device, connection state, run mode, and a live clock.

Corresponds to the 2026-08-13 dashboard redesign's "顶部" requirement.

This widget is a "Passive View": it holds no reference to MainController
or ApiInterface. Its public entry points (:meth:`set_title`,
:meth:`set_device`, :meth:`set_mode`) are called by MainWindow, driven by
data MainController's existing signals already carry (device id/
connection state) or by a plain string the composition script already
has (run mode -- see below). The clock is the one piece of self-contained
state: a QTimer ticking once a second, purely a display concern, not
business logic.

Page switcher (2026-09-18): the dashboard is now two pages (实时监控 /
历史记录, see MainWindow._build_dashboard_column) and the buttons that
switch between them live here, because the header is the one strip that
stays put on both pages. The widget still knows nothing about what the
pages contain: it emits :attr:`page_selected` with a plain index and
offers :meth:`set_current_page` so a switch made some other way (the
Ctrl+1/Ctrl+2 shortcuts MainWindow installs) can push the button state
back in. Paging is a view concern end to end -- no controller signal and
no api method is involved, which is why none was added.

Run mode: ``ui/`` is architecturally never supposed to know *how*
Hardware mode is wired (SerialChannel/HardwareDeviceReceiver never appear
here, per docs/05_Test/Hardware_Simulation_Mode.md) -- but scripts/
run_gui.py, which already knows ``--mode simulator|hardware`` from its
own CLI args, can pass a plain display label ("模拟模式"/"硬件模式")
into MainWindow's constructor without this widget or ui/main_window.py
ever importing anything about what that mode *means* underneath.
"""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from ui.theme import SUCCESS, TEXT_DISABLED, set_class

_DOT_SIZE = 10

#: Page order, and the button labels for each. The index a button emits is
#: its position here, which is also the QStackedWidget index MainWindow
#: builds -- keeping the two in one place is what stops them drifting.
_PAGES: tuple[str, ...] = ("实时监控", "历史记录")


class TopBarWidget(QFrame):
    """Header strip: title, page switcher, device, connection, mode, clock."""

    #: Emitted with the index of the page the user asked for. MainWindow
    #: connects it straight to the stack; nothing else listens.
    page_selected = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("topBar")
        self.setFrameShape(QFrame.Shape.NoFrame)

        self._title_label = QLabel("嵌入式设备上位机平台")
        set_class(self._title_label, "page-title")

        self._page_buttons: list[QPushButton] = []
        for index, label in enumerate(_PAGES):
            button = QPushButton(label)
            button.setObjectName("pageTab")
            button.setCheckable(True)
            button.setChecked(index == 0)
            # Not a QButtonGroup: exclusivity there would let a checked
            # button be un-checked by clicking it again, leaving no page
            # marked while the stack still shows one. set_current_page
            # drives all the states from one place instead.
            button.clicked.connect(
                lambda _checked, i=index: self.page_selected.emit(i)
            )
            self._page_buttons.append(button)

        self._device_label = QLabel("设备：-")
        set_class(self._device_label, "dim")

        self._connection_dot = QLabel()
        self._connection_dot.setFixedSize(_DOT_SIZE, _DOT_SIZE)
        self._set_connected(False)

        self._connection_label = QLabel("未连接")
        set_class(self._connection_label, "dim")

        self._mode_label = QLabel("")
        set_class(self._mode_label, "dim")

        self._clock_label = QLabel("")
        set_class(self._clock_label, "dim")

        self._build_layout()

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start()
        self._tick_clock()

    def _build_layout(self) -> None:
        layout = QHBoxLayout()
        layout.addWidget(self._title_label)
        layout.addSpacing(20)
        for button in self._page_buttons:
            layout.addWidget(button)
        layout.addSpacing(24)
        layout.addWidget(self._device_label)
        layout.addSpacing(12)
        layout.addWidget(self._connection_dot)
        layout.addWidget(self._connection_label)
        layout.addStretch(1)
        layout.addWidget(self._mode_label)
        layout.addSpacing(16)
        layout.addWidget(self._clock_label)
        layout.setContentsMargins(14, 8, 14, 8)
        self.setLayout(layout)

    def set_device(self, device_id: str, connected: bool) -> None:
        """Reflect the currently-selected device's id and connection
        state. Matches the (device_id, is_connected, ...) shape of
        MainController.device_status_changed -- MainWindow's handler
        passes only the two fields this widget cares about."""
        self._device_label.setText(f"设备：{device_id}")
        self._connection_label.setText("已连接" if connected else "未连接")
        self._set_connected(connected)

    def set_current_page(self, index: int) -> None:
        """Mark ``index`` as the visible page.

        Called by MainWindow after it switches the stack -- including for
        a switch the buttons did not start (Ctrl+1/Ctrl+2), which is the
        reason this is a method rather than something the buttons do to
        themselves. An out-of-range index leaves every button unchecked
        rather than raising: the header is a display, and a wrong index is
        MainWindow's bug to fix, not a reason to take the window down.
        """
        for position, button in enumerate(self._page_buttons):
            button.setChecked(position == index)

    def page_count(self) -> int:
        """How many pages the switcher offers, so MainWindow can assert
        its stack matches instead of two counts drifting apart."""
        return len(self._page_buttons)

    def set_mode(self, mode_label: str) -> None:
        """Set the run-mode display text (e.g. "模拟模式"/"硬件模式") --
        a plain caller-supplied string; this widget assigns no meaning
        to it."""
        self._mode_label.setText(mode_label)

    def _set_connected(self, connected: bool) -> None:
        color = SUCCESS if connected else TEXT_DISABLED
        self._connection_dot.setStyleSheet(
            f"background-color: {color}; border-radius: {_DOT_SIZE // 2}px;"
        )

    def _tick_clock(self) -> None:
        self._clock_label.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
