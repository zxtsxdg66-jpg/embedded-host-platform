import pytest

from protocol.decoder import decode
from protocol.encoder import CRC_SIZE, HEADER, encode
from protocol.exceptions import ChecksumError, FrameLengthError, FrameSyncError
from protocol.frame import Frame


@pytest.mark.parametrize(
    ("device_id", "command_type", "payload"),
    [
        (0, 0, b""),
        (1, 2, b"\x01\x02\x03"),
        (255, 255, b"x" * 300),
    ],
)
def test_decode_encode_roundtrip(
    device_id: int, command_type: int, payload: bytes
) -> None:
    original = Frame(device_id=device_id, command_type=command_type, payload=payload)
    restored = decode(encode(original))
    assert restored == original


def test_decode_rejects_data_shorter_than_minimum_frame() -> None:
    with pytest.raises(FrameLengthError):
        decode(b"\x00")


def test_decode_rejects_wrong_header() -> None:
    encoded = bytearray(encode(Frame(device_id=1, command_type=2)))
    encoded[0] ^= 0xFF
    with pytest.raises(FrameSyncError):
        decode(bytes(encoded))


def test_decode_rejects_truncated_frame() -> None:
    encoded = encode(Frame(device_id=1, command_type=2, payload=b"abc"))
    with pytest.raises(FrameLengthError):
        decode(encoded[:-1])


def test_decode_rejects_frame_with_trailing_extra_bytes() -> None:
    encoded = encode(Frame(device_id=1, command_type=2, payload=b"abc"))
    with pytest.raises(FrameLengthError):
        decode(encoded + b"\x00")


def test_decode_rejects_corrupted_payload() -> None:
    encoded = bytearray(encode(Frame(device_id=1, command_type=2, payload=b"abc")))
    # header + device_id + command_type + length
    payload_index = len(HEADER) + 1 + 1 + 2
    encoded[payload_index] ^= 0xFF
    with pytest.raises(ChecksumError):
        decode(bytes(encoded))


def test_decode_rejects_corrupted_crc() -> None:
    encoded = bytearray(encode(Frame(device_id=1, command_type=2, payload=b"abc")))
    encoded[-1] ^= 0xFF
    with pytest.raises(ChecksumError):
        decode(bytes(encoded))


def test_decode_empty_payload_roundtrip() -> None:
    original = Frame(device_id=9, command_type=9, payload=b"")
    restored = decode(encode(original))
    assert restored.payload == b""
    assert restored == original


def test_decode_minimum_valid_frame_has_expected_size() -> None:
    encoded = encode(Frame(device_id=0, command_type=0, payload=b""))
    assert len(encoded) == len(HEADER) + 1 + 1 + 2 + CRC_SIZE
