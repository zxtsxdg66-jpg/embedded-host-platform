"""UI: PC-side presentation layer (PyQt6). Interaction and visualization only.

Currently implemented (phase 2): MainController (mediates between the View
and api.ApiInterface), MainWindow (demo-ready layout composing the
widgets below), and the passive display widgets in ui.widgets: a device
info panel, a real-time multi-channel data table + bounded history, a
rolling line chart, and a control panel with an activity log. No business
logic here -- see ui/controller.py's docstring for the API Layer boundary
this module observes. See src/ui/README.md for the full module scope.
"""

from ui.controller import MainController
from ui.main_window import MainWindow
from ui.widgets import (
    ChartWidget,
    ControlPanelWidget,
    DataPanelWidget,
    DevicePanelWidget,
)

__all__ = [
    "MainController",
    "MainWindow",
    "ChartWidget",
    "ControlPanelWidget",
    "DataPanelWidget",
    "DevicePanelWidget",
]
