from service.data_models import DataPoint
from service.data_service_impl import InMemoryDataService
from service.ventilation_controller import (
    DEFAULT_HUMIDITY_VENTILATION_MAX,
    DEFAULT_TEMPERATURE_VENTILATION_MAX,
    FanDecision,
    FanMode,
    VentilationController,
)

# -- defaults -----------------------------------------------------------------


def test_defaults_match_documented_ventilation_thresholds() -> None:
    controller = VentilationController()

    settings = controller.settings
    assert settings.temperature_max == DEFAULT_TEMPERATURE_VENTILATION_MAX
    assert settings.humidity_max == DEFAULT_HUMIDITY_VENTILATION_MAX
    assert settings.mode is FanMode.AUTO


def test_ventilation_thresholds_are_separate_from_alarm_thresholds() -> None:
    """The ventilation thresholds must not be the alarm thresholds.

    Guards the decision recorded in docs/verification.md
    : the GB 37488-2019-argued alarm thresholds stay fixed, and
    ventilation gets its own (lower temperature, and an *upper* humidity
    limit where the alarm rule has a lower one).
    """
    from service.sensor_data_processor import (
        HUMIDITY_ALARM_MIN,
        TEMPERATURE_ALARM_MAX,
    )

    assert DEFAULT_TEMPERATURE_VENTILATION_MAX < TEMPERATURE_ALARM_MAX
    assert DEFAULT_HUMIDITY_VENTILATION_MAX > HUMIDITY_ALARM_MIN


def test_no_readings_yet_means_fan_stays_off() -> None:
    controller = VentilationController()

    decision = controller.evaluate()
    assert decision.should_run is False
    assert decision.mode is FanMode.AUTO


# -- automatic decisions ------------------------------------------------------


def test_temperature_above_threshold_starts_fan() -> None:
    controller = VentilationController(temperature_max=30.0)
    controller.handle_data_point(
        DataPoint(device_id="dev-1", channel="temperature", value=31.0)
    )

    decision = controller.evaluate()
    assert decision.should_run is True
    assert "温度" in decision.reason


def test_humidity_above_threshold_starts_fan() -> None:
    controller = VentilationController(humidity_max=80.0)
    controller.handle_data_point(
        DataPoint(device_id="dev-1", channel="humidity", value=85.0)
    )

    decision = controller.evaluate()
    assert decision.should_run is True
    assert "湿度" in decision.reason


def test_value_exactly_at_threshold_does_not_start_fan() -> None:
    controller = VentilationController(temperature_max=30.0)
    controller.handle_data_point(
        DataPoint(device_id="dev-1", channel="temperature", value=30.0)
    )

    assert controller.evaluate().should_run is False


def test_both_channels_exceeded_are_both_reported() -> None:
    controller = VentilationController(temperature_max=30.0, humidity_max=80.0)
    controller.handle_data_point(
        DataPoint(device_id="dev-1", channel="temperature", value=33.0)
    )
    controller.handle_data_point(
        DataPoint(device_id="dev-1", channel="humidity", value=90.0)
    )

    decision = controller.evaluate()
    assert decision.should_run is True
    assert "温度" in decision.reason
    assert "湿度" in decision.reason


def test_fan_stops_once_value_returns_below_threshold() -> None:
    controller = VentilationController(temperature_max=30.0)
    controller.handle_data_point(
        DataPoint(device_id="dev-1", channel="temperature", value=33.0)
    )
    assert controller.evaluate().should_run is True

    controller.handle_data_point(
        DataPoint(device_id="dev-1", channel="temperature", value=28.0)
    )
    assert controller.evaluate().should_run is False


def test_noise_channel_never_requests_ventilation() -> None:
    """A fan cannot reduce sound -- running one would only add to it."""
    controller = VentilationController()
    controller.handle_data_point(
        DataPoint(device_id="dev-1", channel="noise", value=120.0)
    )

    assert controller.evaluate().should_run is False


def test_any_device_over_threshold_starts_fan() -> None:
    """Simulator mode reports temperature and humidity from *different*
    devices; Hardware mode from one. Aggregating across devices is what
    lets one controller serve both modes unchanged."""
    controller = VentilationController(temperature_max=30.0)
    controller.handle_data_point(
        DataPoint(device_id="sim-env-1-temp", channel="temperature", value=33.0)
    )
    controller.handle_data_point(
        DataPoint(device_id="mcu-1", channel="temperature", value=20.0)
    )

    assert controller.evaluate().should_run is True


# -- readings that must not influence the decision ----------------------------


def test_invalid_reading_is_ignored() -> None:
    """Hardware mode flags a channel invalid when its sensor read failed;
    acting on that is worse than keeping the previous value."""
    controller = VentilationController(temperature_max=30.0)
    controller.handle_data_point(
        DataPoint(device_id="dev-1", channel="temperature", value=33.0, valid=False)
    )

    assert controller.evaluate().should_run is False


def test_non_numeric_reading_is_ignored() -> None:
    controller = VentilationController(temperature_max=30.0)
    controller.handle_data_point(
        DataPoint(device_id="dev-1", channel="temperature", value="hot")
    )

    assert controller.evaluate().should_run is False


def test_bool_reading_is_ignored() -> None:
    """bool is an int subclass but never a meaningful sensor reading."""
    controller = VentilationController(temperature_max=0.5)
    controller.handle_data_point(
        DataPoint(device_id="dev-1", channel="temperature", value=True)
    )

    assert controller.evaluate().should_run is False


# -- manual override ----------------------------------------------------------


def test_manual_on_overrides_thresholds() -> None:
    controller = VentilationController(temperature_max=30.0)
    controller.handle_data_point(
        DataPoint(device_id="dev-1", channel="temperature", value=20.0)
    )
    controller.set_mode(FanMode.MANUAL_ON)

    decision = controller.evaluate()
    assert decision.should_run is True
    assert decision.mode is FanMode.MANUAL_ON


def test_manual_off_overrides_thresholds() -> None:
    controller = VentilationController(temperature_max=30.0)
    controller.handle_data_point(
        DataPoint(device_id="dev-1", channel="temperature", value=40.0)
    )
    controller.set_mode(FanMode.MANUAL_OFF)

    decision = controller.evaluate()
    assert decision.should_run is False
    assert decision.mode is FanMode.MANUAL_OFF


def test_returning_to_auto_restores_threshold_behaviour() -> None:
    controller = VentilationController(temperature_max=30.0)
    controller.handle_data_point(
        DataPoint(device_id="dev-1", channel="temperature", value=40.0)
    )
    controller.set_mode(FanMode.MANUAL_OFF)
    assert controller.evaluate().should_run is False

    controller.set_mode(FanMode.AUTO)
    assert controller.evaluate().should_run is True


def test_readings_are_still_tracked_while_manually_overridden() -> None:
    """A manual override must not blind the controller: switching back to
    AUTO has to reflect what arrived meanwhile, not a stale value."""
    controller = VentilationController(temperature_max=30.0)
    controller.set_mode(FanMode.MANUAL_OFF)
    controller.handle_data_point(
        DataPoint(device_id="dev-1", channel="temperature", value=40.0)
    )

    controller.set_mode(FanMode.AUTO)
    assert controller.evaluate().should_run is True


# -- runtime-adjustable thresholds --------------------------------------------


def test_lowering_threshold_starts_fan_without_a_new_reading() -> None:
    """The demonstration case: drop the threshold below the current
    reading and the fan must react at once, not on the next sample."""
    controller = VentilationController(temperature_max=30.0)
    controller.handle_data_point(
        DataPoint(device_id="dev-1", channel="temperature", value=25.0)
    )
    assert controller.evaluate().should_run is False

    controller.set_thresholds(temperature_max=20.0)
    assert controller.evaluate().should_run is True


def test_set_thresholds_updates_only_what_is_given() -> None:
    controller = VentilationController(temperature_max=30.0, humidity_max=80.0)

    controller.set_thresholds(humidity_max=60.0)
    assert controller.settings.temperature_max == 30.0
    assert controller.settings.humidity_max == 60.0


def test_set_thresholds_with_no_arguments_changes_nothing() -> None:
    controller = VentilationController(temperature_max=30.0, humidity_max=80.0)

    controller.set_thresholds()
    assert controller.settings.temperature_max == 30.0
    assert controller.settings.humidity_max == 80.0


# -- decision callbacks -------------------------------------------------------


def test_decision_callback_fires_for_every_reading_not_only_transitions() -> None:
    """Mirrors SensorDataProcessor.on_status: a consumer that only wants
    changes can dedupe, but one that renders current state needs every
    evaluation."""
    controller = VentilationController(temperature_max=30.0)
    seen: list[FanDecision] = []
    controller.on_decision(seen.append)

    for value in (20.0, 21.0, 22.0):
        controller.handle_data_point(
            DataPoint(device_id="dev-1", channel="temperature", value=value)
        )

    assert len(seen) == 3
    assert all(decision.should_run is False for decision in seen)


def test_decision_callback_fires_on_mode_change() -> None:
    controller = VentilationController()
    seen: list[FanDecision] = []
    controller.on_decision(seen.append)

    controller.set_mode(FanMode.MANUAL_ON)

    assert len(seen) == 1
    assert seen[0].should_run is True


def test_decision_callback_fires_on_threshold_change() -> None:
    controller = VentilationController(temperature_max=30.0)
    controller.handle_data_point(
        DataPoint(device_id="dev-1", channel="temperature", value=25.0)
    )
    seen: list[FanDecision] = []
    controller.on_decision(seen.append)

    controller.set_thresholds(temperature_max=20.0)

    assert len(seen) == 1
    assert seen[0].should_run is True


def test_ignored_readings_do_not_fire_the_callback() -> None:
    controller = VentilationController()
    seen: list[FanDecision] = []
    controller.on_decision(seen.append)

    controller.handle_data_point(
        DataPoint(device_id="dev-1", channel="noise", value=120.0)
    )
    controller.handle_data_point(
        DataPoint(device_id="dev-1", channel="temperature", value=40.0, valid=False)
    )

    assert seen == []


def test_multiple_callbacks_all_receive_the_decision() -> None:
    controller = VentilationController()
    first: list[FanDecision] = []
    second: list[FanDecision] = []
    controller.on_decision(first.append)
    controller.on_decision(second.append)

    controller.set_mode(FanMode.MANUAL_ON)

    assert len(first) == 1
    assert len(second) == 1


# -- DataService integration --------------------------------------------------


def test_subscribe_to_receives_published_points() -> None:
    data_service = InMemoryDataService()
    controller = VentilationController(temperature_max=30.0)
    controller.subscribe_to(data_service, "dev-1", "temperature")

    data_service.publish(
        DataPoint(device_id="dev-1", channel="temperature", value=35.0)
    )

    assert controller.evaluate().should_run is True
