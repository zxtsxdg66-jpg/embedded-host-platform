"""ui.widgets: passive, business-logic-free PyQt6 display/input components.

Every widget here holds no reference to MainController or ApiInterface --
each is updated only through plain setter methods and only emits plain Qt
signals for user actions. MainWindow is the sole place that wires these
widgets to ui.controller.MainController.
"""

from ui.widgets.assistant_panel import AssistantPanelWidget
from ui.widgets.background_widget import BackgroundWidget
from ui.widgets.chart_widget import ChartWidget
from ui.widgets.control_panel import ControlPanelWidget
from ui.widgets.data_panel import DataPanelWidget
from ui.widgets.device_list_item import DeviceListItemWidget
from ui.widgets.device_panel import DevicePanelWidget
from ui.widgets.fan_card import FanCardWidget
from ui.widgets.metric_card import MetricCardWidget
from ui.widgets.statistics_panel import StatisticsPanelWidget
from ui.widgets.status_banner import StatusBannerWidget
from ui.widgets.top_bar import TopBarWidget
from ui.widgets.ventilation_panel import VentilationPanelWidget

__all__ = [
    "AssistantPanelWidget",
    "BackgroundWidget",
    "ChartWidget",
    "ControlPanelWidget",
    "DataPanelWidget",
    "DeviceListItemWidget",
    "DevicePanelWidget",
    "FanCardWidget",
    "MetricCardWidget",
    "StatisticsPanelWidget",
    "StatusBannerWidget",
    "TopBarWidget",
    "VentilationPanelWidget",
]
