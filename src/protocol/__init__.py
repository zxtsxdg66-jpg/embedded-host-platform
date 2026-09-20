"""Protocol: generic frame codec (header, device id, command type,
length, payload, CRC).

Currently implemented (phase 1): Frame (structured message), encode()
(Frame -> bytes), decode() (bytes -> Frame), and the protocol exception
hierarchy. Not yet implemented: command-type table maintenance, a real
Communication Layer to carry these bytes. See src/protocol/README.md for
the full module scope.
"""

from protocol.decoder import decode
from protocol.encoder import encode
from protocol.exceptions import (
    ChecksumError,
    FrameLengthError,
    FrameSyncError,
    FrameValueError,
    ProtocolError,
)
from protocol.frame import Frame

__all__ = [
    "Frame",
    "encode",
    "decode",
    "ProtocolError",
    "FrameValueError",
    "FrameSyncError",
    "FrameLengthError",
    "ChecksumError",
]
