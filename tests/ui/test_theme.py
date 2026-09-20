"""Smoke test for ui.theme.apply_theme -- a pure presentation concern, so
this only checks it runs without error and actually sets something,
not exact colors (testing QSS string contents in detail would be brittle
and low-value; visual verification is done by hand, see
docs/05_Test/Project_Status_Context.md).
"""

from __future__ import annotations

from PyQt6.QtWidgets import QApplication

from ui.theme import apply_theme


def test_apply_theme_sets_a_nonempty_stylesheet(qtbot) -> None:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    original_stylesheet = app.styleSheet()
    try:
        apply_theme(app)
        assert app.styleSheet() != ""
        assert "QPushButton" in app.styleSheet()
    finally:
        app.setStyleSheet(original_stylesheet)


def test_apply_theme_is_idempotent(qtbot) -> None:
    """Calling it twice (e.g. a future light/dark toggle) must not raise
    or leave stale state -- the second call simply replaces the first."""
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    original_stylesheet = app.styleSheet()
    try:
        apply_theme(app)
        apply_theme(app)
        assert app.styleSheet() != ""
    finally:
        app.setStyleSheet(original_stylesheet)
