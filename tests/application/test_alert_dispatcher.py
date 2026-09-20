from application.alert_dispatcher import (
    DEFAULT_ALERT_CLIENT_ID,
    AlertCommandDispatcher,
)
from service.alarm_announcer import AlertKind, AnnouncementRequest
from service.command_models import Command, CommandResult, CommandStatus
from service.control_service_impl import InMemoryControlService


class _RecordingTransport:
    def __init__(self, status: CommandStatus = CommandStatus.SUCCESS) -> None:
        self.status = status
        self.delivered: list[Command] = []

    def deliver(self, command: Command) -> CommandResult:
        self.delivered.append(command)
        return CommandResult(command_id=command.command_id, status=self.status)


class _RaisingTransport:
    def deliver(self, command: Command) -> CommandResult:
        raise RuntimeError("device unreachable")


def _request(kind: AlertKind = AlertKind.TEMPERATURE) -> AnnouncementRequest:
    return AnnouncementRequest(kind=kind, device_id="mcu-1", channel="temperature")


def _dispatcher(
    transport: _RecordingTransport | _RaisingTransport,
) -> tuple[AlertCommandDispatcher, InMemoryControlService]:
    control = InMemoryControlService(transport=transport)
    return AlertCommandDispatcher(control, device_id="mcu-1"), control


# -- record now, send later ---------------------------------------------------


def test_handle_announcement_sends_nothing_by_itself() -> None:
    """Runs inside the data-publication chain, where sending would
    re-enter the serial read loop."""
    transport = _RecordingTransport()
    dispatcher, _ = _dispatcher(transport)

    dispatcher.handle_announcement(_request())

    assert transport.delivered == []
    assert dispatcher.pending is not None


def test_dispatch_pending_sends_the_phrase_command() -> None:
    transport = _RecordingTransport()
    dispatcher, _ = _dispatcher(transport)

    dispatcher.handle_announcement(_request(AlertKind.NOISE))
    dispatcher.dispatch_pending()

    assert len(transport.delivered) == 1
    assert transport.delivered[0].command_type == "ALERT_NOISE"
    assert transport.delivered[0].device_id == "mcu-1"
    assert transport.delivered[0].origin == DEFAULT_ALERT_CLIENT_ID


def test_dispatch_pending_is_a_noop_when_idle() -> None:
    transport = _RecordingTransport()
    dispatcher, _ = _dispatcher(transport)

    for _ in range(5):
        dispatcher.dispatch_pending()

    assert transport.delivered == []
    assert dispatcher.dispatch_count == 0


def test_announcement_is_sent_once_not_repeatedly() -> None:
    transport = _RecordingTransport()
    dispatcher, _ = _dispatcher(transport)

    dispatcher.handle_announcement(_request())
    for _ in range(5):
        dispatcher.dispatch_pending()

    assert len(transport.delivered) == 1
    assert dispatcher.pending is None


def test_only_the_latest_announcement_is_kept() -> None:
    """One speaker: queued phrases are the pile-up the cooldown exists to
    prevent."""
    transport = _RecordingTransport()
    dispatcher, _ = _dispatcher(transport)

    dispatcher.handle_announcement(_request(AlertKind.TEMPERATURE))
    dispatcher.handle_announcement(_request(AlertKind.NOISE))
    dispatcher.dispatch_pending()

    assert [command.command_type for command in transport.delivered] == ["ALERT_NOISE"]


def test_each_alert_kind_maps_to_its_command() -> None:
    transport = _RecordingTransport()
    dispatcher, _ = _dispatcher(transport)

    for kind in AlertKind:
        dispatcher.handle_announcement(_request(kind))
        dispatcher.dispatch_pending()

    assert [command.command_type for command in transport.delivered] == [
        "ALERT_TEMPERATURE",
        "ALERT_HUMIDITY",
        "ALERT_NOISE",
    ]


# -- occupancy ----------------------------------------------------------------


def test_control_is_released_after_dispatch() -> None:
    transport = _RecordingTransport()
    dispatcher, control = _dispatcher(transport)

    dispatcher.handle_announcement(_request())
    dispatcher.dispatch_pending()

    assert control.get_owner("mcu-1") is None


def test_deferred_while_a_human_holds_the_device() -> None:
    transport = _RecordingTransport()
    dispatcher, control = _dispatcher(transport)
    control.acquire("mcu-1", "dev-gui")

    dispatcher.handle_announcement(_request())
    dispatcher.dispatch_pending()

    assert transport.delivered == []
    assert dispatcher.deferred_count == 1


def test_deferred_announcement_stays_pending_and_is_retried() -> None:
    """Nothing was sent, so unlike a real attempt this one is kept."""
    transport = _RecordingTransport()
    dispatcher, control = _dispatcher(transport)
    control.acquire("mcu-1", "dev-gui")
    dispatcher.handle_announcement(_request())
    dispatcher.dispatch_pending()
    assert dispatcher.pending is not None

    control.release("mcu-1", "dev-gui")
    dispatcher.dispatch_pending()

    assert len(transport.delivered) == 1


# -- failure handling ---------------------------------------------------------


def test_transport_exception_is_counted_not_raised() -> None:
    dispatcher, _ = _dispatcher(_RaisingTransport())

    dispatcher.handle_announcement(_request())
    dispatcher.dispatch_pending()

    assert dispatcher.failure_count == 1
    assert isinstance(dispatcher.last_error, RuntimeError)


def test_control_is_released_even_when_delivery_raises() -> None:
    dispatcher, control = _dispatcher(_RaisingTransport())

    dispatcher.handle_announcement(_request())
    dispatcher.dispatch_pending()

    assert control.get_owner("mcu-1") is None


def test_failed_announcement_is_not_retried() -> None:
    """By the next cycle the alarm is seconds old; a late announcement is
    worse than none."""
    transport = _RecordingTransport(status=CommandStatus.FAILED)
    dispatcher, _ = _dispatcher(transport)

    dispatcher.handle_announcement(_request())
    dispatcher.dispatch_pending()
    dispatcher.dispatch_pending()

    assert len(transport.delivered) == 1
    assert dispatcher.failure_count == 1
    assert dispatcher.pending is None


def test_raised_failure_also_clears_the_pending_request() -> None:
    dispatcher, _ = _dispatcher(_RaisingTransport())

    dispatcher.handle_announcement(_request())
    dispatcher.dispatch_pending()

    assert dispatcher.pending is None
