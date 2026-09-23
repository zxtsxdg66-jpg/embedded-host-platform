"""Generic protocol frame: a structured message, independent of wire bytes.

Corresponds to docs/protocol.md's frame structure
(帧头 / 设备ID / 命令类型 / 数据长度 / Payload / CRC校验). This module defines
only the *structured* message -- device id, command type, payload -- that
docs/protocol.md's "设备ID" and "命令类型" fields describe; byte-level
framing (header sync, length prefix, CRC) is handled by encoder.py /
decoder.py, matching that document's field-by-field breakdown.

Not bound to any specific sensor, MCU model, or transport (UART/TCP/BLE):
``device_id`` and ``command_type`` are opaque integers whose business
meaning is defined elsewhere (a device's capability descriptor, per
docs/architecture.md), and ``payload`` is
opaque bytes.
"""

from __future__ import annotations

from dataclasses import dataclass

from protocol.exceptions import FrameValueError

DEVICE_ID_MAX = 0xFF
"""Largest value a Frame's device_id may hold (1-byte wire field, phase 1)."""

COMMAND_TYPE_MAX = 0xFF
"""Largest value a Frame's command_type may hold (1-byte wire field, phase 1)."""

MAX_PAYLOAD_LENGTH = 0xFFFF
"""Largest payload size in bytes (2-byte length wire field, phase 1)."""


@dataclass(frozen=True)
class Frame:
    """A structured protocol message: target device, command kind, and data.

    Wire-format concerns (frame sync header, length prefix, CRC) are not
    part of this object -- see protocol/encoder.py and protocol/decoder.py.
    """

    device_id: int
    command_type: int
    payload: bytes = b""

    def __post_init__(self) -> None:
        if not 0 <= self.device_id <= DEVICE_ID_MAX:
            raise FrameValueError(
                f"device_id must be within 0..{DEVICE_ID_MAX}, got {self.device_id}"
            )
        if not 0 <= self.command_type <= COMMAND_TYPE_MAX:
            raise FrameValueError(
                "command_type must be within 0.."
                f"{COMMAND_TYPE_MAX}, got {self.command_type}"
            )
        if len(self.payload) > MAX_PAYLOAD_LENGTH:
            raise FrameValueError(
                f"payload length must not exceed {MAX_PAYLOAD_LENGTH} bytes, "
                f"got {len(self.payload)}"
            )
