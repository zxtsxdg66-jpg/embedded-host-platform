from application.fan_dispatcher import (
    DEFAULT_FAN_CLIENT_ID,
    DEFAULT_FAN_OFF_COMMAND,
    DEFAULT_FAN_ON_COMMAND,
    FanCommandDispatcher,
)
from service.command_models import Command, CommandResult, CommandStatus
from service.control_service_impl import InMemoryControlService
from service.data_models import DataPoint
from service.ventilation_controller import FanDecision, FanMode, VentilationController


class _RecordingTransport:
    """CommandTransport stub recording every delivered command."""

    def __init__(self, status: CommandStatus = CommandStatus.SUCCESS) -> None:
        self.status = status
        self.delivered: list[Command] = []

    def deliver(self, command: Command) -> CommandResult:
        self.delivered.append(command)
        return CommandResult(command_id=command.command_id, status=self.status)


class _RaisingTransport:
    """CommandTransport stub that always fails to deliver."""

    def deliver(self, command: Command) -> CommandResult:
        raise RuntimeError("device unreachable")


def _decision(should_run: bool) -> FanDecision:
    return FanDecision(should_run=should_run, reason="test", mode=FanMode.AUTO)


def _dispatcher(
    transport: _RecordingTransport | _RaisingTransport,
) -> tuple[FanCommandDispatcher, InMemoryControlService]:
    control = InMemoryControlService(transport=transport)
    return FanCommandDispatcher(control, device_id="mcu-1"), control


# -- deciding and sending are separate ----------------------------------------


def test_handle_decision_sends_nothing_by_itself() -> None:
    """The whole point of the split: this runs inside the data-publication
    chain, where talking to the device would re-enter the serial read
    loop (see the module docstring)."""
    transport = _RecordingTransport()
    dispatcher, _ = _dispatcher(transport)

    dispatcher.handle_decision(_decision(True))

    assert transport.delivered == []
    assert dispatcher.pending_state is True
    assert dispatcher.applied_state is False


def test_dispatch_pending_sends_the_recorded_state() -> None:
    transport = _RecordingTransport()
    dispatcher, _ = _dispatcher(transport)

    dispatcher.handle_decision(_decision(True))
    dispatcher.dispatch_pending()

    assert len(transport.delivered) == 1
    assert transport.delivered[0].command_type == DEFAULT_FAN_ON_COMMAND
    assert transport.delivered[0].device_id == "mcu-1"
    assert dispatcher.applied_state is True


def test_startup_assumes_the_fan_is_off() -> None:
    """The firmware powers up with the fan stopped, so an initial "off"
    decision must not cost a command round trip."""
    transport = _RecordingTransport()
    dispatcher, _ = _dispatcher(transport)

    assert dispatcher.applied_state is False
    dispatcher.handle_decision(_decision(False))
    dispatcher.dispatch_pending()

    assert transport.delivered == []
    assert dispatcher.has_pending_change is False


def test_dispatch_pending_is_a_noop_when_nothing_changed() -> None:
    transport = _RecordingTransport()
    dispatcher, _ = _dispatcher(transport)
    dispatcher.handle_decision(_decision(True))
    dispatcher.dispatch_pending()

    for _ in range(5):
        dispatcher.dispatch_pending()

    assert len(transport.delivered) == 1
    assert dispatcher.dispatch_count == 1


def test_repeated_identical_decisions_dispatch_once() -> None:
    transport = _RecordingTransport()
    dispatcher, _ = _dispatcher(transport)

    for _ in range(5):
        dispatcher.handle_decision(_decision(True))
        dispatcher.dispatch_pending()

    assert len(transport.delivered) == 1


def test_state_change_dispatches_again() -> None:
    transport = _RecordingTransport()
    dispatcher, _ = _dispatcher(transport)

    for state in (True, False, True):
        dispatcher.handle_decision(_decision(state))
        dispatcher.dispatch_pending()

    assert [command.command_type for command in transport.delivered] == [
        DEFAULT_FAN_ON_COMMAND,
        DEFAULT_FAN_OFF_COMMAND,
        DEFAULT_FAN_ON_COMMAND,
    ]


def test_only_the_latest_decision_is_dispatched() -> None:
    """Several decisions can arrive between two poll cycles; the fan only
    needs the last one."""
    transport = _RecordingTransport()
    dispatcher, _ = _dispatcher(transport)

    dispatcher.handle_decision(_decision(True))
    dispatcher.handle_decision(_decision(False))
    dispatcher.dispatch_pending()

    assert transport.delivered == []
    assert dispatcher.applied_state is False


def test_dispatch_uses_the_dedicated_client_identity() -> None:
    transport = _RecordingTransport()
    dispatcher, _ = _dispatcher(transport)

    dispatcher.handle_decision(_decision(True))
    dispatcher.dispatch_pending()

    assert transport.delivered[0].origin == DEFAULT_FAN_CLIENT_ID


def test_command_names_are_configurable() -> None:
    transport = _RecordingTransport()
    control = InMemoryControlService(transport=transport)
    dispatcher = FanCommandDispatcher(
        control, device_id="mcu-1", on_command="BLOW", off_command="STOP"
    )

    dispatcher.handle_decision(_decision(True))
    dispatcher.dispatch_pending()

    assert transport.delivered[0].command_type == "BLOW"


# -- occupancy ----------------------------------------------------------------


def test_control_is_released_after_dispatch() -> None:
    """Automatic ventilation must not hold the device and lock a human out."""
    transport = _RecordingTransport()
    dispatcher, control = _dispatcher(transport)

    dispatcher.handle_decision(_decision(True))
    dispatcher.dispatch_pending()

    assert control.get_owner("mcu-1") is None


def test_defers_while_another_client_holds_the_device() -> None:
    transport = _RecordingTransport()
    dispatcher, control = _dispatcher(transport)
    control.acquire("mcu-1", "dev-gui")

    dispatcher.handle_decision(_decision(True))
    dispatcher.dispatch_pending()

    assert transport.delivered == []
    assert dispatcher.deferred_count == 1
    assert dispatcher.applied_state is False


def test_deferred_decision_is_retried_once_the_device_is_free() -> None:
    """A failed attempt leaves applied_state alone, so the next poll cycle
    repeats it. No retry timer needed."""
    transport = _RecordingTransport()
    dispatcher, control = _dispatcher(transport)
    control.acquire("mcu-1", "dev-gui")
    dispatcher.handle_decision(_decision(True))
    dispatcher.dispatch_pending()

    control.release("mcu-1", "dev-gui")
    dispatcher.dispatch_pending()

    assert len(transport.delivered) == 1
    assert dispatcher.applied_state is True


def test_holding_client_is_not_disturbed() -> None:
    transport = _RecordingTransport()
    dispatcher, control = _dispatcher(transport)
    control.acquire("mcu-1", "dev-gui")

    dispatcher.handle_decision(_decision(True))
    dispatcher.dispatch_pending()

    assert control.get_owner("mcu-1") == "dev-gui"


# -- failure handling ---------------------------------------------------------


def test_transport_exception_is_counted_not_raised() -> None:
    dispatcher, _ = _dispatcher(_RaisingTransport())

    dispatcher.handle_decision(_decision(True))
    dispatcher.dispatch_pending()

    assert dispatcher.failure_count == 1
    assert isinstance(dispatcher.last_error, RuntimeError)
    assert dispatcher.applied_state is False


def test_control_is_released_even_when_delivery_raises() -> None:
    dispatcher, control = _dispatcher(_RaisingTransport())

    dispatcher.handle_decision(_decision(True))
    dispatcher.dispatch_pending()

    assert control.get_owner("mcu-1") is None


def test_failed_command_result_does_not_record_applied_state() -> None:
    transport = _RecordingTransport(status=CommandStatus.FAILED)
    dispatcher, _ = _dispatcher(transport)

    dispatcher.handle_decision(_decision(True))
    dispatcher.dispatch_pending()

    assert dispatcher.failure_count == 1
    assert dispatcher.applied_state is False


def test_failed_command_is_retried_on_the_next_cycle() -> None:
    transport = _RecordingTransport(status=CommandStatus.FAILED)
    dispatcher, _ = _dispatcher(transport)

    dispatcher.handle_decision(_decision(True))
    dispatcher.dispatch_pending()
    dispatcher.dispatch_pending()

    assert len(transport.delivered) == 2


# -- integration with VentilationController -----------------------------------


def test_controller_decisions_drive_the_dispatcher() -> None:
    transport = _RecordingTransport()
    dispatcher, _ = _dispatcher(transport)
    controller = VentilationController(temperature_max=30.0)
    controller.on_decision(dispatcher.handle_decision)

    controller.set_mode(FanMode.MANUAL_ON)
    dispatcher.dispatch_pending()
    controller.set_mode(FanMode.MANUAL_OFF)
    dispatcher.dispatch_pending()

    assert [command.command_type for command in transport.delivered] == [
        DEFAULT_FAN_ON_COMMAND,
        DEFAULT_FAN_OFF_COMMAND,
    ]


def test_steady_readings_do_not_produce_repeated_commands() -> None:
    """The controller emits on every reading; the dispatcher must absorb
    that so a 3 s data stream does not become a 3 s command stream."""
    transport = _RecordingTransport()
    dispatcher, _ = _dispatcher(transport)
    controller = VentilationController(temperature_max=30.0)
    controller.on_decision(dispatcher.handle_decision)

    for value in (33.0, 34.0, 35.0, 36.0):
        controller.handle_data_point(
            DataPoint(device_id="mcu-1", channel="temperature", value=value)
        )
        dispatcher.dispatch_pending()

    assert len(transport.delivered) == 1
