"""Tests for ui.widgets.ventilation_panel.VentilationPanelWidget."""

from __future__ import annotations

from ui.widgets.ventilation_panel import (
    MODE_AUTO,
    MODE_MANUAL_OFF,
    MODE_MANUAL_ON,
    VentilationPanelWidget,
    mode_label,
)


def test_defaults_to_auto_mode(qtbot) -> None:
    panel = VentilationPanelWidget()
    qtbot.addWidget(panel)

    assert panel.current_mode() == MODE_AUTO


def test_mode_label_maps_names_to_chinese(qtbot) -> None:
    assert mode_label(MODE_AUTO) == "自动"
    assert mode_label(MODE_MANUAL_ON) == "常开"
    assert mode_label(MODE_MANUAL_OFF) == "常关"


def test_unknown_mode_label_falls_back_to_the_name(qtbot) -> None:
    assert mode_label("SOMETHING_ELSE") == "SOMETHING_ELSE"


def test_changing_temperature_emits_both_thresholds(qtbot) -> None:
    panel = VentilationPanelWidget()
    qtbot.addWidget(panel)
    panel.set_settings(30.0, 80.0, MODE_AUTO)
    seen: list[tuple[float, float]] = []
    panel.thresholds_changed.connect(lambda t, h: seen.append((t, h)))

    panel._temperature_input.setValue(25.0)

    assert seen == [(25.0, 80.0)]


def test_changing_humidity_emits_both_thresholds(qtbot) -> None:
    panel = VentilationPanelWidget()
    qtbot.addWidget(panel)
    panel.set_settings(30.0, 80.0, MODE_AUTO)
    seen: list[tuple[float, float]] = []
    panel.thresholds_changed.connect(lambda t, h: seen.append((t, h)))

    panel._humidity_input.setValue(65.0)

    assert seen == [(30.0, 65.0)]


def test_clicking_a_mode_button_emits_its_name(qtbot) -> None:
    panel = VentilationPanelWidget()
    qtbot.addWidget(panel)
    seen: list[str] = []
    panel.mode_changed.connect(seen.append)

    panel._on_button.click()

    assert seen == [MODE_MANUAL_ON]
    assert panel.current_mode() == MODE_MANUAL_ON


def test_set_settings_updates_inputs_and_mode(qtbot) -> None:
    panel = VentilationPanelWidget()
    qtbot.addWidget(panel)

    panel.set_settings(26.5, 70.0, MODE_MANUAL_OFF)

    assert panel.temperature_max() == 26.5
    assert panel.humidity_max() == 70.0
    assert panel.current_mode() == MODE_MANUAL_OFF


def test_set_settings_does_not_emit(qtbot) -> None:
    """Syncing the view from the platform must not look like user input --
    otherwise it would echo straight back and overwrite what was read."""
    panel = VentilationPanelWidget()
    qtbot.addWidget(panel)
    thresholds: list[tuple[float, float]] = []
    modes: list[str] = []
    panel.thresholds_changed.connect(lambda t, h: thresholds.append((t, h)))
    panel.mode_changed.connect(modes.append)

    panel.set_settings(26.5, 70.0, MODE_MANUAL_ON)

    assert thresholds == []
    assert modes == []


def test_panel_holds_no_controller_reference(qtbot) -> None:
    """Passive View: widgets never reach the api/controller themselves."""
    panel = VentilationPanelWidget()
    qtbot.addWidget(panel)

    assert not hasattr(panel, "_controller")
    assert not hasattr(panel, "_api")
