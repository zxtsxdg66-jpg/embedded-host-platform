import pytest

from core.models import ClientId, DeviceId
from service.command_models import Command, CommandResult, CommandStatus
from service.control_service import ControlService


def test_control_service_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        ControlService()  # type: ignore[abstract]


class _InMemoryControlService(ControlService):
    """Minimal fake used only to prove the abstract contract is implementable."""

    def __init__(self) -> None:
        self._owner: dict[DeviceId, ClientId] = {}
        self._results: dict[str, CommandResult] = {}

    def acquire(self, device_id: DeviceId, client_id: ClientId) -> bool:
        current_owner = self._owner.get(device_id)
        if current_owner is not None and current_owner != client_id:
            return False
        self._owner[device_id] = client_id
        return True

    def release(self, device_id: DeviceId, client_id: ClientId) -> None:
        if self._owner.get(device_id) == client_id:
            del self._owner[device_id]

    def submit_command(self, command: Command) -> CommandResult:
        result = CommandResult(
            command_id=command.command_id, status=CommandStatus.PENDING
        )
        self._results[command.command_id] = result
        return result

    def get_result(self, command_id: str) -> CommandResult:
        return self._results[command_id]


def test_acquire_grants_exclusive_authority() -> None:
    service = _InMemoryControlService()
    assert service.acquire("dev-1", "client-1") is True
    assert service.acquire("dev-1", "client-2") is False


def test_release_frees_device_for_other_clients() -> None:
    service = _InMemoryControlService()
    service.acquire("dev-1", "client-1")
    service.release("dev-1", "client-1")
    assert service.acquire("dev-1", "client-2") is True


def test_submit_command_returns_pending_result_and_is_retrievable() -> None:
    service = _InMemoryControlService()
    command = Command(device_id="dev-1", command_type="PING", origin="client-1")

    result = service.submit_command(command)

    assert result.status is CommandStatus.PENDING
    assert service.get_result(command.command_id).command_id == command.command_id
