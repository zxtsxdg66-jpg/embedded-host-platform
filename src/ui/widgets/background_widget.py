"""BackgroundWidget: the main window's background-image layer --
"氛围层" beneath the dashboard's opaque panels ("信息层").

Corresponds to the 2026-08-13 background-image task. This is
``ui/main_window.py``'s central widget itself (see that module's
``_build_layout``): it paints a cover-fit, non-distorted background image
plus a semi-transparent dark overlay in its own :meth:`paintEvent`, then
Qt's normal widget painting order takes over -- every child widget in the
dashboard's layout (which this widget also holds, via ``setLayout``)
paints itself *after* this, on top. This is the entire mechanism; no
QStackedLayout or extra window is needed.

Why this shows through every panel, not just the gaps between them
(2026-08-13 rework): every panel (QGroupBox, the QFrame-based cards,
QListWidget/QTableWidget, ...) now has an ``rgba(...)`` -- not opaque hex
-- ``background-color`` QSS rule in ui/theme.py, each panel tier picking
its own alpha (see that module's ``_PANEL_ALPHA_*`` constants); Qt
composites a translucent child's paint over whatever this widget already
painted beneath it, so this widget's image+overlay reads through panel
interiors too, not only through the *bare layout-container* QWidgets
ui/main_window.py builds purely to hold a layout (those stay fully
transparent, via the generic ``QWidget`` QSS rule having no
background-color at all). Interactive input controls (QPushButton/
QLineEdit/QComboBox) are deliberately left fully opaque -- unlike the
data/display panels, click affordance and typed-text legibility there
benefit from a solid backing, and they were not part of what the
2026-08-13 rework asked to change.

Scaling: "cover" only (the sole mode ui/theme.py's ``BACKGROUND_SCALE_MODE``
currently supports) -- the image is scaled preserving aspect ratio so it
fully fills the widget's rect, with overflow cropped (never stretched
non-uniformly). :func:`cover_source_rect` is the pure, Qt-independent
crop-rectangle calculation, kept separate from :meth:`paintEvent` so it
is unit-testable without constructing a QPixmap/QWidget.

Purely presentational: this widget receives no data from MainController,
emits no signals, and contains no business logic -- it does not know or
care whether the application is in Simulator or Hardware mode.
"""

from __future__ import annotations

from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor, QPainter, QPaintEvent, QPixmap
from PyQt6.QtWidgets import QWidget

from ui.theme import (
    BACKGROUND_IMAGE,
    BACKGROUND_OVERLAY_COLOR,
    BACKGROUND_OVERLAY_OPACITY,
)


def cover_source_rect(
    image_width: int, image_height: int, target_width: int, target_height: int
) -> tuple[int, int, int, int]:
    """The (x, y, width, height) region to sample from an
    ``image_width`` x ``image_height`` image so that drawing that region
    into a ``target_width`` x ``target_height`` rect produces a "cover"
    fit: the target is fully filled, the image's aspect ratio is
    preserved (never stretched), and any overflow is cropped, centered on
    both axes ("center" crop -- ui/theme.py's ``BACKGROUND_POSITION``).

    Returns the whole image unchanged if any dimension is non-positive
    (degenerate input -- e.g. no image loaded, or a not-yet-laid-out
    widget with zero size), rather than raising, since paintEvent can be
    called in such transient states and should just skip drawing instead
    of crashing.
    """
    if image_width <= 0 or image_height <= 0 or target_width <= 0 or target_height <= 0:
        return (0, 0, max(image_width, 0), max(image_height, 0))

    image_aspect = image_width / image_height
    target_aspect = target_width / target_height

    if image_aspect > target_aspect:
        # Image is relatively wider than the target: crop left/right.
        crop_height = image_height
        crop_width = max(1, round(image_height * target_aspect))
        x = (image_width - crop_width) // 2
        y = 0
    else:
        # Image is relatively taller than (or equal to) the target: crop
        # top/bottom.
        crop_width = image_width
        crop_height = max(1, round(image_width / target_aspect))
        x = 0
        y = (image_height - crop_height) // 2

    return (x, y, crop_width, crop_height)


class BackgroundWidget(QWidget):
    """Paints a cover-fit background image + dark overlay behind whatever
    layout is set on it via :meth:`setLayout` (see module docstring)."""

    def __init__(
        self,
        image_path: str = BACKGROUND_IMAGE,
        overlay_color: str = BACKGROUND_OVERLAY_COLOR,
        overlay_opacity: float = BACKGROUND_OVERLAY_OPACITY,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._pixmap = QPixmap(image_path)  # a null QPixmap if the path
        # does not exist or is not a valid image -- paintEvent below
        # checks isNull() and simply skips drawing it rather than
        # crashing, so a missing/renamed asset degrades to "just the
        # overlay color" instead of taking the whole app down.
        self._overlay_color = overlay_color
        self._overlay_opacity = overlay_opacity

    def has_image(self) -> bool:
        """Whether a valid background image was loaded (exposed mainly
        for tests -- paintEvent already handles the False case)."""
        return not self._pixmap.isNull()

    def paintEvent(self, event: QPaintEvent | None) -> None:
        del event  # unused: this widget always repaints its full rect
        try:
            painter = QPainter(self)
        except RuntimeError:
            # 底层 C++ 对象已被销毁，但 Python 包装器还在，且收到了一个排队中的
            # 重绘事件。生产环境走不到这里（本控件是主窗口的 central widget，
            # 与进程同寿命）；但测试中控件被反复创建/销毁时会发生。
            #
            # 必须吞掉而不是让它抛出：paintEvent 抛出的异常会被 Qt 当作致命
            # 错误，直接 abort 整个进程——2026-09-07 实测到的现象是全部 571 个
            # 用例明明都已通过，pytest 却以 "Fatal Python error: Aborted" 退出，
            # 且是否触发取决于测试文件的字母顺序（新增一个排在最后的测试文件
            # 就会暴露）。这种"绿了却崩"的失败方式会让整条质量基线不可信。
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        try:
            self._draw(painter)
        finally:
            painter.end()

    def _draw(self, painter: QPainter) -> None:
        if not self._pixmap.isNull():
            src_x, src_y, src_w, src_h = cover_source_rect(
                self._pixmap.width(), self._pixmap.height(), self.width(), self.height()
            )
            painter.drawPixmap(
                self.rect(), self._pixmap, QRect(src_x, src_y, src_w, src_h)
            )

        overlay = QColor(self._overlay_color)
        overlay.setAlphaF(max(0.0, min(1.0, self._overlay_opacity)))
        painter.fillRect(self.rect(), overlay)
