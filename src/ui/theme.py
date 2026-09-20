"""Application-wide dark theme: a single QSS stylesheet + matching QPalette.

Corresponds to .claude/skills/pyqt6-ui-development-rules' Iron Law 3
("ALWAYS apply QSS stylesheets at the QApplication level rather than
per-widget") -- this module is that one stylesheet, applied once by
whoever constructs the QApplication (scripts/run_gui.py), never scattered
across individual widgets.

Visual direction (2026-08-13 dashboard redesign): a dark, card-based
industrial-monitoring look -- deep charcoal background, one teal accent,
blue/purple as secondary data colors, red reserved exclusively for
alarms -- the same broad style used by comparable embedded/IoT telemetry
dashboards (e.g. Serial Studio, itself built on Qt) and SCADA/HMI panels,
without copying any specific product. This module is the *design system*
for that look: a small typography scale (``[cls=...]`` attribute
selectors) and a handful of card-style container rules
(``QFrame#metricCard`` etc.), plus the base widget theming carried over
from the previous flat dark theme.

Deliberately pure presentation, no behavior: this module imports nothing
beyond PyQt6, defines no signals/slots, and is never imported by
ui/controller.py -- widgets stay themable/testable without ever depending
on this module for their *logic* (tests construct widgets directly
without an application-level stylesheet applied, and behave identically
either way since QSS/QPalette only affect painting, never widget state
queried by tests like QTableWidgetItem.background()). Some presentation-
only widgets (ui/widgets/chart_widget.py, the dashboard cards) do import
the plain color constants from here for consistency -- that is a
same-layer (ui/ -> ui/) dependency, not a boundary violation; none of
those widgets import this module's QSS/QPalette machinery, only color
strings.

Deliberately does NOT touch:
- Per-item table cell colors (QTableWidgetItem.setBackground/
  setForeground, used by ui/widgets/data_panel.py for alarm highlighting)
  -- this stylesheet has no ``QTableWidget::item`` background rule, so
  those item-level overrides keep painting through unaffected.

Known QSS gotcha avoided here: styling ``QComboBox::drop-down`` without
also supplying a custom arrow image makes Qt draw no arrow at all (a
common, easy-to-miss regression) -- this stylesheet deliberately leaves
that subcontrol unstyled so Qt falls back to native (palette-colored)
rendering.

Background image (2026-08-13): all its configuration (``BACKGROUND_*``
constants below -- path, overlay color/opacity, scale mode, crop
position) lives here, in one place, per the same "theme is the single
source of styling truth" principle as everything else in this module.
The actual painting (``ui/widgets/background_widget.py``'s
``BackgroundWidget``) reads these constants but is a separate file,
since it is a QWidget subclass with a paintEvent, not pure
configuration/QSS -- this module still imports nothing beyond PyQt6 and
stays free of any QWidget subclassing of its own.

Panel translucency (2026-08-13 rework): the first background-image pass
kept every panel fully opaque and only let the image show through in
layout gaps -- visually that read as "a dark GUI with a wallpaper hidden
behind it", not the requested "background is the visual base, panels are
a translucent info layer on top of it". This rework replaces every
panel's solid hex ``background-color`` with an ``rgba(...)`` value (see
:func:`_rgba`), each panel tier picking its own alpha from
``BACKGROUND_OVERLAY_OPACITY`` (now much lighter, ~0.15) up through a
deliberate hierarchy -- general info panels stay most transparent, core
real-time data next, chart/top-card/control-panel chrome least
transparent (still never fully opaque) -- rather than one flat alpha
everywhere, so panels read as *layered*, not as a uniform frosted sheet.
Text colors/fonts are untouched by this pass; where a specific panel
still read as hard to read against the background, that panel's own
alpha was raised individually rather than compensating with heavier text
styling or a darker global overlay (see the per-selector comments
below).
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QWidget

# -- palette -------------------------------------------------------------
#
# Only the constants below (no leading underscore) are the module's public
# surface -- other ui/widgets/*.py files may import these plain color
# strings for small pieces of genuinely dynamic, per-instance styling that
# QSS alone cannot express (e.g. a status dot's color depends on runtime
# alarm state, not just widget type) -- see CARD_STYLE_NOTE in each
# widget that does this. Never import _STYLESHEET/_build_palette/private
# constants from outside this module.

BG_WINDOW = "#1a1d24"
BG_PANEL = "#20242c"
BG_CARD = "#232833"
BG_INPUT = "#262b35"
BG_INPUT_HOVER = "#2c313d"
BORDER = "#333a48"
BORDER_LIGHT = "#454d5f"
TEXT_PRIMARY = "#e6e8ee"
TEXT_SECONDARY = "#8b93a7"
TEXT_DISABLED = "#5a6070"
ACCENT = "#3fd0c9"
ACCENT_HOVER = "#5be0da"
ACCENT_PRESSED = "#2fb5af"
ACCENT_TEXT = "#0d1117"  # text painted on top of the accent color itself
SECONDARY_BLUE = "#5b8dee"
SECONDARY_PURPLE = "#a684e8"
WARNING = "#f5a623"
DANGER = "#ef4444"
SUCCESS = "#3ddc97"

# Plot-area fill alpha for ui/widgets/chart_widget.py's paintEvent -- that
# widget draws its own background manually (QPainter.fillRect), it is not
# reachable by QSS, so it needs this as a plain public constant rather
# than the private _PANEL_ALPHA_* tiers below (same "plain color
# constants only" contract as BG_INPUT/ACCENT/etc. above). Kept in the
# same light tier as _PANEL_ALPHA_CHART_PLOT (2026-08-13 rework) so the
# curve's plot area matches the rest of the tiered-transparency scheme.
CHART_PLOT_BACKGROUND_ALPHA = 0.30

# -- background image (2026-08-13) ---------------------------------------
#
# The one place every background-image parameter lives -- ui/widgets/
# background_widget.py reads these instead of any file hardcoding its own
# path/opacity/scale numbers. Bundled under src/ui/assets/ (not docs/,
# which is documentation, not an application asset) so the app stays
# portable -- no absolute, machine-specific path.
BACKGROUND_IMAGE = str(Path(__file__).resolve().parent / "assets" / "background.png")
BACKGROUND_SCALE_MODE = "cover"  # only mode implemented so far; named for
# future extensibility (e.g. "contain"/"stretch") without call sites
# needing to change once one is added.
BACKGROUND_POSITION = "center"  # crop anchor for "cover" mode; only
# "center" implemented so far, same forward-compatibility reasoning as
# BACKGROUND_SCALE_MODE above.
BACKGROUND_OVERLAY_COLOR = BG_WINDOW  # tinted to match the app's own
# palette rather than an unrelated color, so the overlay reads as "this
# theme, dimmed" rather than a foreign wash.
BACKGROUND_OVERLAY_OPACITY = 0.16  # 0 (no dimming) .. 1 (fully opaque
# overlay, image invisible). Deliberately light (2026-08-13 rework, down
# from an initial 0.62): this overlay's job is only to keep the *empty*
# areas of the window from looking like raw wallpaper, not to darken the
# image enough for panel text to read -- that job belongs to each
# panel's own background alpha (_PANEL_ALPHA_* below), adjusted per-panel
# instead of by darkening the whole background.

# -- panel translucency tiers (2026-08-13 rework) -------------------------
#
# One alpha per panel *tier*, not one flat value everywhere, so panels
# read as layered rather than as a uniform frosted sheet: general info
# stays most transparent, core real-time data next, chart/top-card/
# control-panel/log chrome least transparent (still never fully opaque).
# Values are alpha fractions (0..1) applied to each panel's existing hex
# color via :func:`_rgba`.
_PANEL_ALPHA_INFO = 0.38  # general info panels (e.g. 设备信息)
_PANEL_ALPHA_TABLE_BODY = 0.32  # 实时数据/历史记录 table body
_PANEL_ALPHA_TABLE_HEADER = 0.48  # table header row (needs more contrast)
_PANEL_ALPHA_GROUP_DATA = 0.36  # 实时数据/历史记录 group box chrome
_PANEL_ALPHA_STATS = 0.44  # 统计信息 group box + per-channel cards
_PANEL_ALPHA_CHART_CARD = 0.50  # 实时曲线 card chrome (title strip/border)
_PANEL_ALPHA_CHART_PLOT = 0.30  # 实时曲线绘图区 itself -- lighter than the
# card chrome around it, per the "绘图区再叠加一层非常轻的半透明背景" ask.
_PANEL_ALPHA_METRIC_CARD = 0.52  # 顶部关键数据卡片
_PANEL_ALPHA_TOP_BAR = 0.55  # persistent top bar chrome
_PANEL_ALPHA_CONTROL = 0.52  # 控制面板
_PANEL_ALPHA_LOG = 0.58  # 活动日志 list


def _rgba(hex_color: str, alpha: float) -> str:
    """``"#20242c"`` + ``0.35`` -> ``"rgba(32, 36, 44, 0.35)"``, for QSS
    ``background-color`` rules that must let the background image show
    through (Qt's QSS engine accepts ``rgba()`` directly; plain hex
    strings are always fully opaque)."""
    color = QColor(hex_color)
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"

# Aliases kept for readability inside the f-string below.
_BG_WINDOW, _BG_PANEL, _BG_CARD = BG_WINDOW, BG_PANEL, BG_CARD
_BG_INPUT, _BG_INPUT_HOVER = BG_INPUT, BG_INPUT_HOVER
_BORDER, _BORDER_LIGHT = BORDER, BORDER_LIGHT
_TEXT_PRIMARY, _TEXT_SECONDARY, _TEXT_DISABLED = (
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    TEXT_DISABLED,
)
_ACCENT, _ACCENT_HOVER, _ACCENT_PRESSED, _ACCENT_TEXT = (
    ACCENT,
    ACCENT_HOVER,
    ACCENT_PRESSED,
    ACCENT_TEXT,
)
_WARNING, _DANGER, _SUCCESS = WARNING, DANGER, SUCCESS

_STYLESHEET = f"""
/* 2026-08-13 background image: QWidget deliberately has no
   background-color here (only color/font-size) -- every widget that
   needs to stay visually opaque already has its own specific selector
   below (QGroupBox, QFrame#*, QPushButton, QLineEdit/QComboBox,
   QListWidget, QTableWidget, ...), so removing the generic fill only
   affects bare layout-container QWidgets (the invisible boxes
   ui/main_window.py builds purely to hold a QVBoxLayout/QHBoxLayout) --
   those become transparent, letting ui/widgets/background_widget.py's
   painted image+overlay show through in the gaps between panels, exactly
   where the app previously showed flat {_BG_WINDOW}. See
   background_widget.py's module docstring for the full picture. */
QWidget {{
    color: {_TEXT_PRIMARY};
    font-size: 10pt;
}}

QMainWindow {{
    background-color: {_BG_WINDOW};
}}

/* -- typography scale: set via widget.setProperty("cls", "...") -------- */
QLabel[cls="page-title"] {{
    font-size: 15pt;
    font-weight: 700;
    color: {_TEXT_PRIMARY};
}}
QLabel[cls="section-title"] {{
    font-size: 10pt;
    font-weight: 700;
    color: {_TEXT_SECONDARY};
}}
QLabel[cls="metric-value"] {{
    font-size: 28pt;
    font-weight: 700;
    color: {_TEXT_PRIMARY};
}}
QLabel[cls="metric-unit"] {{
    font-size: 12pt;
    font-weight: 600;
    color: {_TEXT_SECONDARY};
}}
QLabel[cls="metric-title"] {{
    font-size: 10pt;
    font-weight: 600;
    color: {_TEXT_SECONDARY};
}}
QLabel[cls="dim"] {{
    font-size: 9pt;
    color: {_TEXT_SECONDARY};
}}
/* 统计卡片的当前值。2026-08-13 定为 17pt 以突出"当前值是卡片的主角"；
   2026-08-18 统计卡改为三张横排后，单卡宽度降到面板的三分之一，17pt 一行就能
   占满整张卡，故下调到 14pt——仍明显大于同卡内其余文字，主次关系不变。 */
QLabel[cls="stat-value"] {{
    font-size: 14pt;
    font-weight: 700;
    color: {_TEXT_PRIMARY};
}}
/* Trend arrows are direction, not judgement -- deliberately all the same
   muted color (not accent/danger) so "rising" never reads as "good" and
   "falling" never reads as "bad"; only the alarm border communicates
   severity. See MetricCardWidget's docstring. */
QLabel[cls="trend-up"], QLabel[cls="trend-down"], QLabel[cls="trend-flat"] {{
    color: {_TEXT_SECONDARY};
    font-weight: 600;
}}

/* -- card-style containers -----------------------------------------------
   2026-08-13 rework: every background-color below is an rgba() value (see
   _rgba() above) instead of a flat opaque hex, so the background image
   keeps showing through *inside* panels, not just in the gaps between
   them -- each panel's alpha comes from its own _PANEL_ALPHA_* tier
   constant, deliberately not all the same value (see module docstring).
   Borders stay 1px and the same hue as before -- distinguishing panels by
   layering/alpha, not by heavier borders or drop shadows. */
QFrame#topBar {{
    background-color: {_rgba(_BG_PANEL, _PANEL_ALPHA_TOP_BAR)};
    border-bottom: 1px solid {_BORDER};
}}

QFrame#metricCard {{
    background-color: {_rgba(_BG_CARD, _PANEL_ALPHA_METRIC_CARD)};
    border: 1px solid {_BORDER};
    border-radius: 8px;
}}
QFrame#metricCard[state="warning"] {{
    border: 1px solid {_WARNING};
}}
QFrame#metricCard[state="alarm"] {{
    border: 2px solid {_DANGER};
}}
/* 通风卡专用：风扇正在运行。刻意不复用 warning/alarm 两个状态——风扇转起来
   是系统在正常履行职责，不是异常，用告警色会误导读者。 */
QFrame#metricCard[state="running"] {{
    border: 1px solid {_SUCCESS};
}}

QFrame#statusBanner {{
    background-color: {_rgba(_BG_CARD, _PANEL_ALPHA_INFO)};
    border: 1px solid {_BORDER};
    border-radius: 8px;
}}
QFrame#statusBanner[state="warning"] {{
    border: 1px solid {_WARNING};
}}
QFrame#statusBanner[state="alarm"] {{
    border: 1px solid {_DANGER};
}}

QFrame#chartCard {{
    background-color: {_rgba(_BG_PANEL, _PANEL_ALPHA_CHART_CARD)};
    border: 1px solid {_BORDER};
    border-radius: 8px;
}}

QFrame#deviceCard {{
    background-color: {_rgba(_BG_CARD, _PANEL_ALPHA_INFO)};
    border: 1px solid {_BORDER};
    border-radius: 6px;
}}
QFrame#deviceCard[selected="true"] {{
    border: 1.5px solid {_ACCENT};
}}

QFrame#statCard {{
    background-color: {_rgba(_BG_CARD, _PANEL_ALPHA_STATS)};
    border: 1px solid {_BORDER};
    border-radius: 6px;
}}

/* Generic fallback tier (普通信息 panels, e.g. 设备信息) -- specific
   group boxes below (data/statistics/control) override with their own
   tier's alpha. */
QGroupBox {{
    background-color: {_rgba(_BG_PANEL, _PANEL_ALPHA_INFO)};
    border: 1px solid {_BORDER};
    border-radius: 6px;
    margin-top: 14px;
    padding: 10px 8px 8px 8px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
    color: {_ACCENT};
}}
QGroupBox#realtimeGroup, QGroupBox#historyGroup {{
    background-color: {_rgba(_BG_PANEL, _PANEL_ALPHA_GROUP_DATA)};
}}
QGroupBox#statisticsGroup {{
    background-color: {_rgba(_BG_PANEL, _PANEL_ALPHA_STATS)};
}}
QGroupBox#controlGroup {{
    background-color: {_rgba(_BG_PANEL, _PANEL_ALPHA_CONTROL)};
}}

QLabel {{
    background-color: transparent;
    color: {_TEXT_PRIMARY};
}}

QPushButton {{
    background-color: {_BG_INPUT};
    border: 1px solid {_BORDER_LIGHT};
    border-radius: 4px;
    padding: 6px 14px;
    color: {_TEXT_PRIMARY};
}}
QPushButton:hover {{
    background-color: {_BG_INPUT_HOVER};
    border-color: {_ACCENT};
}}
QPushButton:pressed {{
    background-color: {_ACCENT_PRESSED};
    color: {_ACCENT_TEXT};
    border-color: {_ACCENT_PRESSED};
}}
QPushButton:disabled {{
    color: {_TEXT_DISABLED};
    border-color: {_BORDER};
}}
/* Page tabs in the top bar (2026-09-18, 仪表盘分两页). Styled as tabs
   rather than buttons: no fill and no border when idle so the header
   still reads as one strip, and the selected page is marked by an accent
   underline plus brighter text. The underline is what carries the state
   -- color alone would be the only cue, and the same dark ground makes a
   subtle color shift easy to miss on a projector. */
QPushButton#pageTab {{
    background-color: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    padding: 5px 12px;
    color: {_TEXT_SECONDARY};
}}
QPushButton#pageTab:hover {{
    color: {_TEXT_PRIMARY};
    border-bottom-color: {_BORDER_LIGHT};
}}
QPushButton#pageTab:checked {{
    color: {_ACCENT};
    border-bottom-color: {_ACCENT};
}}
QPushButton#pageTab:pressed {{
    background-color: transparent;
    color: {_ACCENT_HOVER};
}}

QPushButton[cls="ghost"] {{
    background-color: transparent;
    border: 1px solid {_BORDER};
    color: {_TEXT_SECONDARY};
    padding: 3px 10px;
}}
QPushButton[cls="ghost"]:hover {{
    border-color: {_ACCENT};
    color: {_ACCENT};
}}

QLineEdit, QComboBox {{
    background-color: {_BG_INPUT};
    border: 1px solid {_BORDER_LIGHT};
    border-radius: 4px;
    padding: 4px 6px;
    color: {_TEXT_PRIMARY};
    selection-background-color: {_ACCENT};
    selection-color: {_ACCENT_TEXT};
}}
QLineEdit:focus, QComboBox:focus {{
    border-color: {_ACCENT};
}}
QLineEdit:disabled, QComboBox:disabled {{
    color: {_TEXT_DISABLED};
    background-color: {_BG_PANEL};
}}
QComboBox QAbstractItemView {{
    background-color: {_BG_INPUT};
    border: 1px solid {_BORDER_LIGHT};
    selection-background-color: {_ACCENT};
    selection-color: {_ACCENT_TEXT};
    outline: none;
}}

/* Device list (普通信息 tier) vs 活动日志 (least transparent, needs to
   stay legible against a scrolling log of short lines) -- differentiated
   via objectName since both are QListWidget. */
QListWidget {{
    background-color: {_rgba(_BG_INPUT, _PANEL_ALPHA_INFO)};
    border: 1px solid {_BORDER};
    border-radius: 4px;
    outline: none;
}}
QListWidget#activityLog {{
    background-color: {_rgba(_BG_INPUT, _PANEL_ALPHA_LOG)};
}}
QListWidget::item {{
    padding: 3px 4px;
}}
QListWidget::item:selected {{
    background-color: {_ACCENT};
    color: {_ACCENT_TEXT};
}}

QScrollArea {{
    background: transparent;
    border: none;
}}

QTableWidget {{
    background-color: {_rgba(_BG_INPUT, _PANEL_ALPHA_TABLE_BODY)};
    alternate-background-color: {_rgba(_BG_PANEL, _PANEL_ALPHA_TABLE_BODY)};
    gridline-color: {_BORDER};
    border: 1px solid {_BORDER};
    border-radius: 4px;
    outline: none;
}}
QTableWidget::item:selected {{
    background-color: {_ACCENT};
    color: {_ACCENT_TEXT};
}}
QHeaderView::section {{
    background-color: {_rgba(_BG_PANEL, _PANEL_ALPHA_TABLE_HEADER)};
    color: {_TEXT_SECONDARY};
    border: none;
    border-bottom: 1px solid {_BORDER_LIGHT};
    padding: 4px 6px;
    font-weight: 600;
}}

/* -- 实时数据（多通道）表格：字号/行高比其余表格更大，保证 3 通道无需滚动即可
   看清 -- 见 ui/widgets/data_panel.py 的信息层级说明 */
QTableWidget#realtimeDataTable {{
    font-size: 12pt;
}}
QTableWidget#realtimeDataTable::item {{
    padding: 6px 6px;
}}
QTableWidget#realtimeDataTable QHeaderView::section {{
    font-size: 10pt;
}}

QSplitter::handle {{
    background-color: {_BORDER};
}}
QSplitter::handle:hover {{
    background-color: {_ACCENT};
}}

QScrollBar:vertical {{
    background-color: {_BG_WINDOW};
    width: 12px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background-color: {_BORDER_LIGHT};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {_ACCENT};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background-color: {_BG_WINDOW};
    height: 12px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background-color: {_BORDER_LIGHT};
    border-radius: 5px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{
    background-color: {_ACCENT};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

QToolTip {{
    background-color: {_BG_PANEL};
    color: {_TEXT_PRIMARY};
    border: 1px solid {_BORDER_LIGHT};
    padding: 4px;
}}
"""


def _build_palette() -> QPalette:
    """A QPalette matching the stylesheet's colors.

    Needed because not everything reads color from QSS: ui/widgets/
    chart_widget.py's paintEvent deliberately queries ``self.palette()``
    (Base/Mid roles) rather than hardcoding colors, precisely so it
    inherits whatever theme the application sets -- QSS alone does not
    update QWidget.palette()'s return value, only a real QPalette does.
    """
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(_BG_WINDOW))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(_TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Base, QColor(_BG_INPUT))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(_BG_PANEL))
    palette.setColor(QPalette.ColorRole.Text, QColor(_TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Button, QColor(_BG_INPUT))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(_TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(_BG_PANEL))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(_TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(_ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(_ACCENT_TEXT))
    palette.setColor(QPalette.ColorRole.Mid, QColor(_BORDER_LIGHT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(_TEXT_SECONDARY))
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor(_TEXT_DISABLED),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.WindowText,
        QColor(_TEXT_DISABLED),
    )
    return palette


def apply_theme(app: QApplication) -> None:
    """Apply the dark theme to ``app``: QPalette first, then QSS on top.

    Call once, right after constructing the QApplication (see
    scripts/run_gui.py) -- both calls are idempotent (each simply
    replaces the previous palette/stylesheet), so calling this again
    later (e.g. a future light/dark toggle) would also be safe.
    """
    app.setPalette(_build_palette())
    app.setStyleSheet(_STYLESHEET)


def set_class(widget: QWidget, cls: str) -> None:
    """Assign ``widget`` the QSS attribute-selector class ``cls`` (e.g.
    ``QLabel[cls="metric-value"]`` rules above) and force a repolish.

    Plain ``widget.setProperty("cls", cls)`` is not always enough once a
    widget has already been shown/polished once -- Qt's style caches the
    match, so this also calls unpolish()/polish() to force it to
    re-evaluate. Safe to call before or after the widget is shown.
    """
    widget.setProperty("cls", cls)
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)


def set_state(widget: QWidget, state: str) -> None:
    """Assign ``widget`` the QSS attribute-selector state (e.g.
    ``QFrame#metricCard[state="alarm"]`` rules above) and force a
    repolish. See :func:`set_class` for why the repolish call matters."""
    widget.setProperty("state", state)
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
