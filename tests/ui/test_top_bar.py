"""Tests for ui.widgets.top_bar.TopBarWidget -- no api/controller involved."""

from __future__ import annotations

from ui.widgets.top_bar import TopBarWidget


def test_new_top_bar_shows_placeholder_device(qtbot) -> None:
    bar = TopBarWidget()
    qtbot.addWidget(bar)

    assert bar._device_label.text() == "设备：-"
    assert bar._connection_label.text() == "未连接"


def test_set_device_updates_labels(qtbot) -> None:
    bar = TopBarWidget()
    qtbot.addWidget(bar)

    bar.set_device("mcu-1", True)

    assert bar._device_label.text() == "设备：mcu-1"
    assert bar._connection_label.text() == "已连接"


def test_set_mode_updates_label(qtbot) -> None:
    bar = TopBarWidget()
    qtbot.addWidget(bar)

    bar.set_mode("硬件模式")

    assert bar._mode_label.text() == "硬件模式"


def test_clock_label_is_populated_on_construction(qtbot) -> None:
    bar = TopBarWidget()
    qtbot.addWidget(bar)

    assert bar._clock_label.text() != ""


# -- page switcher (2026-09-18, 仪表盘分两页) --------------------------------


def test_the_first_page_starts_selected(qtbot) -> None:
    """Something must be marked, or the header disagrees with the stack,
    which starts on index 0."""
    bar = TopBarWidget()
    qtbot.addWidget(bar)

    assert bar.page_count() == 2
    assert bar._page_buttons[0].isChecked()
    assert not bar._page_buttons[1].isChecked()


def test_clicking_a_tab_emits_its_index(qtbot) -> None:
    bar = TopBarWidget()
    qtbot.addWidget(bar)

    with qtbot.waitSignal(bar.page_selected) as blocker:
        bar._page_buttons[1].click()

    assert blocker.args == [1]


def test_set_current_page_moves_the_mark(qtbot) -> None:
    """The switch may come from a keyboard shortcut, so the buttons have to
    be drivable from outside rather than only marking themselves."""
    bar = TopBarWidget()
    qtbot.addWidget(bar)

    bar.set_current_page(1)

    assert not bar._page_buttons[0].isChecked()
    assert bar._page_buttons[1].isChecked()


def test_clicking_the_selected_tab_again_leaves_it_selected(qtbot) -> None:
    """A checkable button un-checks itself on a second click. If that were
    left alone the header would show no page while the stack still shows
    one -- MainWindow.show_page pushes the state back, so re-clicking is
    a no-op rather than a way to end up with nothing marked."""
    bar = TopBarWidget()
    qtbot.addWidget(bar)
    bar.set_current_page(1)

    bar._page_buttons[1].click()
    bar.set_current_page(1)  # what MainWindow.show_page does

    assert bar._page_buttons[1].isChecked()


def test_an_out_of_range_page_does_not_raise(qtbot) -> None:
    """A wrong index is the caller's bug; taking the window down over a
    header display is not the right answer."""
    bar = TopBarWidget()
    qtbot.addWidget(bar)

    bar.set_current_page(7)

    assert not any(button.isChecked() for button in bar._page_buttons)
