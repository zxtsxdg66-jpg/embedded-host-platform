"""ApplicationRuntime's ventilation wiring: auto-subscription and dispatch."""

from application.fan_dispatcher import (
    DEFAULT_FAN_OFF_COMMAND,
    DEFAULT_FAN_ON_COMMAND,
)
from application.runtime import ApplicationRuntime
from communication.loopback import LoopbackChannel
from device.sensors.channels import HUMIDITY_CHANNEL, TEMPERATURE_CHANNEL
from device.simulator import ConstantValueGenerator, SimulatedChannel, SimulatorDevice
from service.data_models import DataPoint
from service.ventilation_controller import FanDecision, FanMode

_FAN_COMMANDS = (DEFAULT_FAN_ON_COMMAND, DEFAULT_FAN_OFF_COMMAND)


def _runtime_with_device(
    device_id: str = "mcu-1",
    channels: tuple[str, ...] = (TEMPERATURE_CHANNEL, HUMIDITY_CHANNEL),
    accepted_commands: tuple[str, ...] = _FAN_COMMANDS,
) -> ApplicationRuntime:
    runtime = ApplicationRuntime()
    device = SimulatorDevice(
        device_id=device_id,
        channels=[
            SimulatedChannel(channel_id=channel, generator=ConstantValueGenerator(1.0))
            for channel in channels
        ],
    )
    runtime.register_device(
        device, LoopbackChannel(), accepted_commands=accepted_commands
    )
    return runtime


# -- auto-subscription --------------------------------------------------------


def test_register_device_auto_subscribes_ventilation() -> None:
    runtime = _runtime_with_device()
    runtime.set_ventilation_thresholds(temperature_max=30.0)
    seen: list[FanDecision] = []
    runtime.subscribe_fan_decision(seen.append)

    runtime.data_service.publish(
        DataPoint(device_id="mcu-1", channel=TEMPERATURE_CHANNEL, value=35.0)
    )

    assert seen and seen[-1].should_run is True


def test_watch_alarms_for_alias_also_wires_ventilation() -> None:
    """Hardware mode's composition calls the old name; it must not silently
    skip ventilation."""
    runtime = ApplicationRuntime()
    device = SimulatorDevice(
        device_id="mcu-1",
        channels=[
            SimulatedChannel(
                channel_id=TEMPERATURE_CHANNEL, generator=ConstantValueGenerator(1.0)
            )
        ],
    )
    runtime.devices.register(device, LoopbackChannel(), _FAN_COMMANDS)
    runtime.watch_alarms_for(device)
    runtime.set_ventilation_thresholds(temperature_max=30.0)
    seen: list[FanDecision] = []
    runtime.subscribe_fan_decision(seen.append)

    runtime.data_service.publish(
        DataPoint(device_id="mcu-1", channel=TEMPERATURE_CHANNEL, value=35.0)
    )

    assert seen and seen[-1].should_run is True


def test_alarm_processor_still_wired_alongside_ventilation() -> None:
    """Adding ventilation must not have displaced the alarm subscription."""
    runtime = _runtime_with_device()
    alarms: list[object] = []
    runtime.subscribe_alarm_status(alarms.append)

    runtime.data_service.publish(
        DataPoint(device_id="mcu-1", channel=TEMPERATURE_CHANNEL, value=40.0)
    )

    assert alarms


# -- dispatch opt-in ----------------------------------------------------------


def test_no_commands_dispatched_before_enable_fan_control() -> None:
    runtime = _runtime_with_device()
    runtime.set_ventilation_thresholds(temperature_max=30.0)

    runtime.data_service.publish(
        DataPoint(device_id="mcu-1", channel=TEMPERATURE_CHANNEL, value=40.0)
    )

    assert runtime.fan_dispatcher is None


def test_enable_fan_control_dispatches_on_threshold_crossing() -> None:
    runtime = _runtime_with_device()
    runtime.set_ventilation_thresholds(temperature_max=30.0)
    dispatcher = runtime.enable_fan_control("mcu-1")

    runtime.data_service.publish(
        DataPoint(device_id="mcu-1", channel=TEMPERATURE_CHANNEL, value=40.0)
    )
    dispatcher.dispatch_pending()

    assert dispatcher.applied_state is True
    assert dispatcher.dispatch_count == 1


def test_fan_stops_when_reading_returns_below_threshold() -> None:
    runtime = _runtime_with_device()
    runtime.set_ventilation_thresholds(temperature_max=30.0)
    dispatcher = runtime.enable_fan_control("mcu-1")

    runtime.data_service.publish(
        DataPoint(device_id="mcu-1", channel=TEMPERATURE_CHANNEL, value=40.0)
    )
    dispatcher.dispatch_pending()
    runtime.data_service.publish(
        DataPoint(device_id="mcu-1", channel=TEMPERATURE_CHANNEL, value=20.0)
    )
    dispatcher.dispatch_pending()

    assert dispatcher.applied_state is False
    assert dispatcher.dispatch_count == 2


def test_fan_dispatcher_property_exposes_the_installed_dispatcher() -> None:
    runtime = _runtime_with_device()

    dispatcher = runtime.enable_fan_control("mcu-1")

    assert runtime.fan_dispatcher is dispatcher


def test_manual_mode_dispatches_without_any_reading() -> None:
    """The demonstration path: no sensor data needed to prove the fan works."""
    runtime = _runtime_with_device()
    dispatcher = runtime.enable_fan_control("mcu-1")

    runtime.set_fan_mode(FanMode.MANUAL_ON)
    dispatcher.dispatch_pending()

    assert dispatcher.applied_state is True


def test_lowering_threshold_dispatches_without_a_new_reading() -> None:
    runtime = _runtime_with_device()
    runtime.set_ventilation_thresholds(temperature_max=30.0)
    dispatcher = runtime.enable_fan_control("mcu-1")
    runtime.data_service.publish(
        DataPoint(device_id="mcu-1", channel=TEMPERATURE_CHANNEL, value=25.0)
    )
    dispatcher.dispatch_pending()
    assert dispatcher.applied_state is False

    runtime.set_ventilation_thresholds(temperature_max=20.0)
    dispatcher.dispatch_pending()

    assert dispatcher.applied_state is True


def test_ventilation_ignores_noise_channel_end_to_end() -> None:
    runtime = _runtime_with_device(channels=(TEMPERATURE_CHANNEL, "noise"))
    dispatcher = runtime.enable_fan_control("mcu-1")

    runtime.data_service.publish(
        DataPoint(device_id="mcu-1", channel="noise", value=120.0)
    )
    dispatcher.dispatch_pending()

    assert dispatcher.applied_state is False
