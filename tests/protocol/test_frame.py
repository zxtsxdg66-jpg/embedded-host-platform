import dataclasses

import pytest

from protocol.exceptions import FrameValueError
from protocol.frame import COMMAND_TYPE_MAX, DEVICE_ID_MAX, MAX_PAYLOAD_LENGTH, Frame


def test_frame_stores_given_fields() -> None:
    frame = Frame(device_id=1, command_type=2, payload=b"\x01\x02")
    assert frame.device_id == 1
    assert frame.command_type == 2
    assert frame.payload == b"\x01\x02"


def test_frame_defaults_to_empty_payload() -> None:
    frame = Frame(device_id=1, command_type=2)
    assert frame.payload == b""


@pytest.mark.parametrize("device_id", [-1, DEVICE_ID_MAX + 1])
def test_frame_rejects_out_of_range_device_id(device_id: int) -> None:
    with pytest.raises(FrameValueError):
        Frame(device_id=device_id, command_type=0)


@pytest.mark.parametrize("command_type", [-1, COMMAND_TYPE_MAX + 1])
def test_frame_rejects_out_of_range_command_type(command_type: int) -> None:
    with pytest.raises(FrameValueError):
        Frame(device_id=0, command_type=command_type)


def test_frame_accepts_boundary_values() -> None:
    frame = Frame(device_id=DEVICE_ID_MAX, command_type=COMMAND_TYPE_MAX)
    assert frame.device_id == DEVICE_ID_MAX
    assert frame.command_type == COMMAND_TYPE_MAX


def test_frame_rejects_payload_over_max_length() -> None:
    with pytest.raises(FrameValueError):
        Frame(device_id=0, command_type=0, payload=b"\x00" * (MAX_PAYLOAD_LENGTH + 1))


def test_frame_accepts_payload_at_max_length() -> None:
    payload = b"\x00" * MAX_PAYLOAD_LENGTH
    frame = Frame(device_id=0, command_type=0, payload=payload)
    assert len(frame.payload) == MAX_PAYLOAD_LENGTH


def test_frame_is_immutable() -> None:
    frame = Frame(device_id=1, command_type=2)
    with pytest.raises(dataclasses.FrozenInstanceError):
        frame.device_id = 5  # type: ignore[misc]
