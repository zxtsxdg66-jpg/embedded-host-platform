from service.command_models import Command, CommandResult, CommandStatus


def test_command_generates_unique_id_by_default() -> None:
    first = Command(device_id="dev-1", command_type="PING", origin="client-1")
    second = Command(device_id="dev-1", command_type="PING", origin="client-1")
    assert first.command_id != second.command_id


def test_command_default_parameters_is_empty_mapping() -> None:
    command = Command(device_id="dev-1", command_type="PING", origin="client-1")
    assert dict(command.parameters) == {}


def test_command_result_defaults_to_pending() -> None:
    result = CommandResult(command_id="cmd-1")
    assert result.status is CommandStatus.PENDING
    assert result.completed_at is None
