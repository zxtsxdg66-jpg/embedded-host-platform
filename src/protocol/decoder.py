"""Frame decoder: bytes -> Frame.

Mirrors the wire format defined in protocol/encoder.py. Validates frame
sync, declared payload length, and CRC before returning a Frame --
corrupted or incomplete input raises a protocol.exceptions.ProtocolError
subclass rather than returning a partially-decoded result (per
.claude/skills/improving-python-code-quality: fail loud, don't degrade
silently).
"""

from __future__ import annotations

import zlib

from protocol.encoder import (
    BYTE_ORDER,
    COMMAND_TYPE_SIZE,
    CRC_SIZE,
    DEVICE_ID_SIZE,
    HEADER,
    LENGTH_SIZE,
)
from protocol.exceptions import ChecksumError, FrameLengthError, FrameSyncError
from protocol.frame import Frame

_HEADER_SIZE = len(HEADER)
_MIN_FRAME_SIZE = (
    _HEADER_SIZE + DEVICE_ID_SIZE + COMMAND_TYPE_SIZE + LENGTH_SIZE + CRC_SIZE
)


def decode(data: bytes) -> Frame:
    """Parse exactly one complete frame from ``data``.

    ``data`` must contain exactly one frame's worth of bytes: no leading
    garbage, no trailing bytes beyond the frame's own CRC. Locating a
    frame within an arbitrary, possibly partial byte stream is a
    Communication Layer concern for a later phase, not part of this
    function.
    """
    if len(data) < _MIN_FRAME_SIZE:
        raise FrameLengthError(
            f"data too short to contain a frame: {len(data)} < {_MIN_FRAME_SIZE} bytes"
        )
    if data[:_HEADER_SIZE] != HEADER:
        raise FrameSyncError(
            f"missing or corrupted frame header: {data[:_HEADER_SIZE]!r}"
        )

    offset = _HEADER_SIZE
    device_id = int.from_bytes(data[offset : offset + DEVICE_ID_SIZE], BYTE_ORDER)
    offset += DEVICE_ID_SIZE

    command_type = int.from_bytes(
        data[offset : offset + COMMAND_TYPE_SIZE], BYTE_ORDER
    )
    offset += COMMAND_TYPE_SIZE

    declared_length = int.from_bytes(data[offset : offset + LENGTH_SIZE], BYTE_ORDER)
    offset += LENGTH_SIZE

    payload_end = offset + declared_length
    crc_end = payload_end + CRC_SIZE
    if len(data) != crc_end:
        raise FrameLengthError(
            f"declared payload length {declared_length} does not match "
            f"available data: expected total {crc_end} bytes, got {len(data)}"
        )

    payload = data[offset:payload_end]
    received_crc = data[payload_end:crc_end]

    body = data[_HEADER_SIZE:payload_end]
    expected_crc = zlib.crc32(body).to_bytes(CRC_SIZE, BYTE_ORDER)
    if received_crc != expected_crc:
        raise ChecksumError(
            f"CRC mismatch: expected {expected_crc.hex()}, got {received_crc.hex()}"
        )

    return Frame(device_id=device_id, command_type=command_type, payload=payload)
