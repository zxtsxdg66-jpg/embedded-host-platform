import zlib

from protocol.encoder import (
    BYTE_ORDER,
    COMMAND_TYPE_SIZE,
    CRC_SIZE,
    DEVICE_ID_SIZE,
    HEADER,
    LENGTH_SIZE,
    encode,
)
from protocol.frame import Frame


def test_encode_starts_with_header() -> None:
    encoded = encode(Frame(device_id=1, command_type=2))
    assert encoded.startswith(HEADER)


def test_encode_empty_payload_has_expected_total_length() -> None:
    encoded = encode(Frame(device_id=1, command_type=2, payload=b""))
    expected_length = (
        len(HEADER) + DEVICE_ID_SIZE + COMMAND_TYPE_SIZE + LENGTH_SIZE + CRC_SIZE
    )
    assert len(encoded) == expected_length


def test_encode_appends_payload_and_matching_length_field() -> None:
    payload = b"\x01\x02\x03"
    encoded = encode(Frame(device_id=1, command_type=2, payload=payload))

    length_offset = len(HEADER) + DEVICE_ID_SIZE + COMMAND_TYPE_SIZE
    length_field = encoded[length_offset : length_offset + LENGTH_SIZE]
    assert int.from_bytes(length_field, BYTE_ORDER) == len(payload)

    payload_offset = length_offset + LENGTH_SIZE
    assert encoded[payload_offset : payload_offset + len(payload)] == payload


def test_encode_device_id_and_command_type_fields() -> None:
    encoded = encode(Frame(device_id=7, command_type=42))
    device_id_offset = len(HEADER)
    command_type_offset = device_id_offset + DEVICE_ID_SIZE
    assert encoded[device_id_offset:command_type_offset] == (7).to_bytes(
        DEVICE_ID_SIZE, BYTE_ORDER
    )
    assert encoded[
        command_type_offset : command_type_offset + COMMAND_TYPE_SIZE
    ] == (42).to_bytes(COMMAND_TYPE_SIZE, BYTE_ORDER)


def test_encode_crc_matches_zlib_crc32_of_body() -> None:
    frame = Frame(device_id=1, command_type=2, payload=b"abc")
    encoded = encode(frame)

    body = encoded[len(HEADER) : -CRC_SIZE]
    crc_field = encoded[-CRC_SIZE:]
    assert crc_field == zlib.crc32(body).to_bytes(CRC_SIZE, BYTE_ORDER)


def test_encode_is_deterministic() -> None:
    frame = Frame(device_id=3, command_type=4, payload=b"same")
    assert encode(frame) == encode(frame)


def test_encode_different_payloads_produce_different_bytes() -> None:
    first = encode(Frame(device_id=1, command_type=1, payload=b"aaa"))
    second = encode(Frame(device_id=1, command_type=1, payload=b"bbb"))
    assert first != second
