import pytest

from core.exceptions import StateTransitionError
from device.state import ConnectionState, DeviceStatus, OccupancyState


def test_default_status_is_disconnected_and_free() -> None:
    status = DeviceStatus()
    assert status.connection_state is ConnectionState.DISCONNECTED
    assert status.occupancy_state is OccupancyState.FREE
    assert status.occupant is None


def test_occupied_without_occupant_is_invalid() -> None:
    with pytest.raises(StateTransitionError):
        DeviceStatus(occupancy_state=OccupancyState.OCCUPIED, occupant=None)


def test_free_with_occupant_is_invalid() -> None:
    with pytest.raises(StateTransitionError):
        DeviceStatus(occupancy_state=OccupancyState.FREE, occupant="client-1")


def test_occupy_transitions_to_occupied() -> None:
    occupied = DeviceStatus().occupy("client-1")
    assert occupied.occupancy_state is OccupancyState.OCCUPIED
    assert occupied.occupant == "client-1"


def test_occupy_twice_raises() -> None:
    status = DeviceStatus().occupy("client-1")
    with pytest.raises(StateTransitionError):
        status.occupy("client-2")


def test_release_by_owner_succeeds() -> None:
    status = DeviceStatus().occupy("client-1")
    released = status.release("client-1")
    assert released.occupancy_state is OccupancyState.FREE
    assert released.occupant is None


def test_release_by_non_owner_raises() -> None:
    status = DeviceStatus().occupy("client-1")
    with pytest.raises(StateTransitionError):
        status.release("client-2")


def test_release_when_already_free_raises() -> None:
    with pytest.raises(StateTransitionError):
        DeviceStatus().release("client-1")


def test_with_connection_updates_state_without_mutating_original() -> None:
    status = DeviceStatus()
    connected = status.with_connection(ConnectionState.CONNECTED)
    assert connected.connection_state is ConnectionState.CONNECTED
    assert status.connection_state is ConnectionState.DISCONNECTED
