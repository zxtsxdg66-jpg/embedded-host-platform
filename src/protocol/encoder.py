"""Frame encoder: Frame -> bytes.

Wire format (all multi-byte integers big-endian / network byte order)::

    +--------+-----------+--------------+--------+-----------+-----+
    | Header | Device ID | Command Type | Length | Payload   | CRC |
    | 2B     | 1B        | 1B           | 2B     | Length B  | 4B  |
    +--------+-----------+--------------+--------+-----------+-----+

Field choices made for this phase-1 implementation -- all left open by
docs/protocol.md's "后续工作" section, decided here
rather than in that document:

- **Header**: fixed 2-byte sync marker, used by the decoder to locate the
  start of a frame.
- **Device ID / Command Type**: 1 byte each (0-255). Mapping a Service
  Layer string ``DeviceId`` (see core/models.py) onto this numeric wire id
  is a bridging concern for a later phase (once ``communication`` exists),
  not part of this module.
- **Length**: 2-byte unsigned payload length (0-65535 bytes).
- **CRC**: 4-byte CRC-32 (``zlib.crc32``, Python standard library -- no
  third-party dependency), computed over Device ID + Command Type +
  Length + Payload. The header sync marker is excluded from the checksum
  since it never varies and carries no information to protect.
"""

from __future__ import annotations

import zlib
from typing import Literal

from protocol.frame import Frame

HEADER = b"\xaa\x55"
DEVICE_ID_SIZE = 1
COMMAND_TYPE_SIZE = 1
LENGTH_SIZE = 2
CRC_SIZE = 4
BYTE_ORDER: Literal["big"] = "big"


def encode(frame: Frame) -> bytes:
    """Serialize ``frame`` into its wire-format bytes."""
    body = (
        frame.device_id.to_bytes(DEVICE_ID_SIZE, BYTE_ORDER)
        + frame.command_type.to_bytes(COMMAND_TYPE_SIZE, BYTE_ORDER)
        + len(frame.payload).to_bytes(LENGTH_SIZE, BYTE_ORDER)
        + frame.payload
    )
    crc = zlib.crc32(body).to_bytes(CRC_SIZE, BYTE_ORDER)
    return HEADER + body + crc
