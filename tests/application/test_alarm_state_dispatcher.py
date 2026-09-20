from application.alarm_state_dispatcher import (
    ALARM_STATE_COMMAND,
    BITS_PARAMETER,
    DEFAULT_ALARM_STATE_CLIENT_ID,
    AlarmStateDispatcher,
)
from device.sensors.channels import (
    HUMIDITY_CHANNEL,
    NOISE_CHANNEL,
    TEMPERATURE_CHANNEL,
)
from service.command_models import Command, CommandResult, CommandStatus
from service.control_service_impl import InMemoryControlService
from service.sensor_data_processor import AlarmKind, ThresholdStatus


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


def _status(
    channel: str, triggered: bool, device_id: str = "mcu-1"
) -> ThresholdStatus:
    return ThresholdStatus(
        device_id=device_id,
        channel=channel,
        value=99.0,
        threshold=80.0,
        kind=AlarmKind.ABOVE_MAX,
        triggered=triggered,
    )


def _dispatcher(
    transport: _RecordingTransport | _RaisingTransport,
) -> tuple[AlarmStateDispatcher, InMemoryControlService]:
    control = InMemoryControlService(transport=transport)
    return AlarmStateDispatcher(control, device_id="mcu-1"), control


def _bits(command: Command) -> int:
    return int(command.parameters[BITS_PARAMETER])


# -- recording and sending are separate ---------------------------------------


def test_handle_status_sends_nothing_by_itself() -> None:
    """Same hazard as the fan and alert dispatchers: this callback runs
    inside the data-publication chain, which in Hardware mode is driven
    from the serial read loop."""
    transport = _RecordingTransport()
    dispatcher, _ = _dispatcher(transport)

    dispatcher.handle_threshold_status(_status(TEMPERATURE_CHANNEL, True))

    assert transport.delivered == []
    assert dispatcher.pending_bits == 0x01
    assert dispatcher.applied_bits == 0


def test_dispatch_pending_sends_the_recorded_bitmap() -> None:
    transport = _RecordingTransport()
    dispatcher, _ = _dispatcher(transport)

    dispatcher.handle_threshold_status(_status(NOISE_CHANNEL, True))
    dispatcher.dispatch_pending()

    assert len(transport.delivered) == 1
    assert transport.delivered[0].command_type == ALARM_STATE_COMMAND
    assert transport.delivered[0].origin == DEFAULT_ALARM_STATE_CLIENT_ID
    assert _bits(transport.delivered[0]) == 0x04
    assert dispatcher.applied_bits == 0x04


# -- bitmap composition -------------------------------------------------------


def test_channels_combine_into_one_bitmap() -> None:
    transport = _RecordingTransport()
    dispatcher, _ = _dispatcher(transport)

    dispatcher.handle_threshold_status(_status(TEMPERATURE_CHANNEL, True))
    dispatcher.handle_threshold_status(_status(HUMIDITY_CHANNEL, True))
    dispatcher.dispatch_pending()

    assert _bits(transport.delivered[-1]) == 0x03


def test_returning_to_normal_clears_only_that_channel() -> None:
    transport = _RecordingTransport()
    dispatcher, _ = _dispatcher(transport)

    dispatcher.handle_threshold_status(_status(TEMPERATURE_CHANNEL, True))
    dispatcher.handle_threshold_status(_status(NOISE_CHANNEL, True))
    dispatcher.dispatch_pending()
    dispatcher.handle_threshold_status(_status(TEMPERATURE_CHANNEL, False))
    dispatcher.dispatch_pending()

    assert _bits(transport.delivered[-1]) == 0x04


def test_two_devices_on_one_channel_do_not_cancel_each_other() -> None:
    """The set is keyed by (device, channel): a second device reporting
    normal must not clear an alarm the first device is still in."""
    transport = _RecordingTransport()
    dispatcher, _ = _dispatcher(transport)

    dispatcher.handle_threshold_status(_status(NOISE_CHANNEL, True, "mcu-1"))
    dispatcher.handle_threshold_status(_status(NOISE_CHANNEL, False, "mcu-2"))

    assert dispatcher.pending_bits == 0x04


def test_unknown_channel_is_ignored() -> None:
    """A future sensor type has no row on the board's screen."""
    transport = _RecordingTransport()
    dispatcher, _ = _dispatcher(transport)

    dispatcher.handle_threshold_status(_status("pressure", True))

    assert dispatcher.pending_bits == 0
    assert dispatcher.has_pending_change is False


# -- deduplication and retry (state semantics, like the fan dispatcher) -------


def test_unchanged_bitmap_sends_nothing() -> None:
    transport = _RecordingTransport()
    dispatcher, _ = _dispatcher(transport)

    dispatcher.handle_threshold_status(_status(TEMPERATURE_CHANNEL, True))
    dispatcher.dispatch_pending()
    dispatcher.handle_threshold_status(_status(TEMPERATURE_CHANNEL, True))
    dispatcher.dispatch_pending()

    assert len(transport.delivered) == 1


def test_all_clear_at_start_up_sends_nothing() -> None:
    """The firmware powers up with every row showing 正常, so an
    all-clear bitmap needs no command."""
    transport = _RecordingTransport()
    dispatcher, _ = _dispatcher(transport)

    dispatcher.handle_threshold_status(_status(TEMPERATURE_CHANNEL, False))
    dispatcher.dispatch_pending()

    assert transport.delivered == []


def test_failed_delivery_is_retried_next_cycle() -> None:
    transport = _RecordingTransport(status=CommandStatus.FAILED)
    dispatcher, _ = _dispatcher(transport)

    dispatcher.handle_threshold_status(_status(NOISE_CHANNEL, True))
    dispatcher.dispatch_pending()
    dispatcher.dispatch_pending()

    assert len(transport.delivered) == 2
    assert dispatcher.applied_bits == 0
    assert dispatcher.failure_count == 2


def test_transport_exception_never_escapes() -> None:
    dispatcher, _ = _dispatcher(_RaisingTransport())

    dispatcher.handle_threshold_status(_status(NOISE_CHANNEL, True))
    dispatcher.dispatch_pending()

    assert dispatcher.failure_count == 1
    assert isinstance(dispatcher.last_error, RuntimeError)


def test_deferred_while_a_human_holds_the_device() -> None:
    transport = _RecordingTransport()
    dispatcher, control = _dispatcher(transport)
    assert control.acquire("mcu-1", "operator")

    dispatcher.handle_threshold_status(_status(NOISE_CHANNEL, True))
    dispatcher.dispatch_pending()

    assert transport.delivered == []
    assert dispatcher.deferred_count == 1
    assert dispatcher.has_pending_change is True
