"""Tests for ui.widgets.background_widget -- no api/controller involved.

cover_source_rect() is a pure function (no QPixmap/QWidget needed) --
tested directly for the actual crop-geometry math. BackgroundWidget
itself is tested for "constructs and paints without raising", not exact
pixel output (matching this codebase's existing precedent for
paintEvent-heavy widgets, e.g. tests/ui/test_chart_widget.py).
"""

from __future__ import annotations

from ui.widgets.background_widget import BackgroundWidget, cover_source_rect

# -- cover_source_rect(): pure geometry, no Qt objects needed ----------------


def test_wider_image_crops_left_and_right() -> None:
    # image is wider (relative to its height) than the target -> crop
    # left/right, keep full height
    x, y, w, h = cover_source_rect(
        image_width=2000, image_height=1000, target_width=800, target_height=800
    )

    assert h == 1000
    assert w == 1000  # 800/800 aspect * 1000 height
    assert y == 0
    assert x == (2000 - 1000) // 2  # centered


def test_taller_image_crops_top_and_bottom() -> None:
    x, y, w, h = cover_source_rect(
        image_width=800, image_height=2000, target_width=800, target_height=400
    )

    assert w == 800
    assert h == 400  # 800 width / (800/400) aspect
    assert x == 0
    assert y == (2000 - 400) // 2  # centered


def test_matching_aspect_ratio_uses_the_whole_image() -> None:
    x, y, w, h = cover_source_rect(
        image_width=1600, image_height=1000, target_width=1280, target_height=800
    )

    assert (x, y) == (0, 0)
    assert w == 1600
    assert h == 1000


def test_zero_target_size_returns_the_whole_image_without_crashing() -> None:
    x, y, w, h = cover_source_rect(
        image_width=1600, image_height=1000, target_width=0, target_height=0
    )

    assert (x, y, w, h) == (0, 0, 1600, 1000)


def test_zero_image_size_does_not_crash() -> None:
    result = cover_source_rect(
        image_width=0, image_height=0, target_width=800, target_height=600
    )

    assert result == (0, 0, 0, 0)


# -- BackgroundWidget: construction + paint smoke tests -----------------------


def test_loads_the_bundled_asset_by_default(qtbot) -> None:
    widget = BackgroundWidget()
    qtbot.addWidget(widget)

    assert widget.has_image() is True


def test_missing_image_path_degrades_gracefully(qtbot) -> None:
    widget = BackgroundWidget(image_path="no/such/file.png")
    qtbot.addWidget(widget)

    assert widget.has_image() is False


def test_paint_event_renders_without_error(qtbot) -> None:
    widget = BackgroundWidget()
    qtbot.addWidget(widget)
    widget.resize(400, 300)

    pixmap = widget.grab()

    assert not pixmap.isNull()


def test_paint_event_renders_without_error_when_image_missing(qtbot) -> None:
    widget = BackgroundWidget(image_path="no/such/file.png")
    qtbot.addWidget(widget)
    widget.resize(400, 300)

    pixmap = widget.grab()

    assert not pixmap.isNull()


def test_paint_event_renders_without_error_on_resize(qtbot) -> None:
    """Covers both wider-than-tall and taller-than-wide target rects,
    since cover_source_rect branches on that."""
    widget = BackgroundWidget()
    qtbot.addWidget(widget)

    widget.resize(900, 200)
    assert not widget.grab().isNull()

    widget.resize(200, 900)
    assert not widget.grab().isNull()
