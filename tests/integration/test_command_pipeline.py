"""End-to-end command pipeline: Service -> Protocol -> Communication ->
SimulatorDevice -> back."""

import pytest

from application.runtime import ApplicationRuntime
from communication.loopback import LoopbackChannel
from core.exceptions import NotFoundError, StateTransitionError
from device.simulator import ConstantValueGenerator, SimulatedChannel, SimulatorDevice
from service.command_models import Command, CommandStatus


def _make_runtime_with_device(
    device_id: str = "sim-1", accepted_commands: tuple[str, ...] = ("PING",)
) -> ApplicationRuntime:
    runtime = ApplicationRuntime()
    device = SimulatorDevice(
        device_id=device_id,
        channels=[
            SimulatedChannel(channel_id="ch1", generator=ConstantValueGenerator(0))
        ],
    )
    runtime.register_device(
        device, LoopbackChannel(), accepted_commands=accepted_commands
    )
    return runtime


def test_accepted_command_round_trips_to_success() -> None:
    runtime = _make_runtime_with_device()
    runtime.acquire("sim-1", "client-1")
    command = Command(device_id="sim-1", command_type="PING", origin="client-1")

    result = runtime.submit_command(command)

    assert result.command_id == command.command_id
    assert result.status is CommandStatus.SUCCESS
    assert result.completed_at is not None


def test_unaccepted_command_round_trips_to_failed() -> None:
    runtime = _make_runtime_with_device()
    runtime.acquire("sim-1", "client-1")
    command = Command(
        device_id="sim-1", command_type="UNKNOWN_COMMAND", origin="client-1"
    )

    result = runtime.submit_command(command)

    assert result.status is CommandStatus.FAILED
    assert "UNKNOWN_COMMAND" in result.message


def test_get_result_matches_submit_result() -> None:
    runtime = _make_runtime_with_device()
    runtime.acquire("sim-1", "client-1")
    command = Command(device_id="sim-1", command_type="PING", origin="client-1")

    submitted = runtime.submit_command(command)
    fetched = runtime.get_result(command.command_id)

    assert fetched == submitted


def test_get_result_for_unknown_command_id_raises() -> None:
    runtime = _make_runtime_with_device()
    with pytest.raises(NotFoundError):
        runtime.get_result("no-such-command")


def test_submit_without_acquiring_raises() -> None:
    runtime = _make_runtime_with_device()
    command = Command(device_id="sim-1", command_type="PING", origin="client-1")
    with pytest.raises(StateTransitionError):
        runtime.submit_command(command)


def test_submit_by_non_owning_client_raises() -> None:
    runtime = _make_runtime_with_device()
    runtime.acquire("sim-1", "client-1")
    command = Command(device_id="sim-1", command_type="PING", origin="client-2")
    with pytest.raises(StateTransitionError):
        runtime.submit_command(command)


def test_release_allows_another_client_to_acquire_and_submit() -> None:
    runtime = _make_runtime_with_device()
    runtime.acquire("sim-1", "client-1")
    runtime.release("sim-1", "client-1")

    assert runtime.acquire("sim-1", "client-2") is True
    command = Command(device_id="sim-1", command_type="PING", origin="client-2")
    result = runtime.submit_command(command)

    assert result.status is CommandStatus.SUCCESS


def test_command_with_parameters_round_trips_without_error() -> None:
    runtime = _make_runtime_with_device()
    runtime.acquire("sim-1", "client-1")
    command = Command(
        device_id="sim-1",
        command_type="PING",
        origin="client-1",
        parameters={"retries": 3, "mode": "fast"},
    )

    result = runtime.submit_command(command)

    assert result.status is CommandStatus.SUCCESS


def test_data_and_command_pipelines_do_not_interfere_on_same_device() -> None:
    runtime = _make_runtime_with_device()
    runtime.acquire("sim-1", "client-1")

    data_point = runtime.report_data("sim-1", "ch1")
    command_result = runtime.submit_command(
        Command(device_id="sim-1", command_type="PING", origin="client-1")
    )

    assert data_point.value == 0
    assert command_result.status is CommandStatus.SUCCESS
