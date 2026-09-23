"""LoopbackChannel: an in-memory CommunicationChannel for software-only verification.

Corresponds to docs/protocol.md's requirement
that every transport implement the same unified interface (principle 1) --
this is that interface's simplest possible implementation, with no real
transport medium at all.

Design: everything written via ``send()`` is queued internally in arrival
order and becomes available to ``receive()`` (FIFO), simulating a channel
that loops data back to its own receiver. This lets Protocol Layer
encode/decode round-trips (and, later, higher layers) be exercised
end-to-end without any real hardware, matching the role
device/simulator.py plays for the Device abstraction: a long-lived,
protocol-compatible stand-in for real I/O, not a throwaway test script.
"""

from __future__ import annotations

from collections import deque

from communication.exceptions import AlreadyConnectedError, NotConnectedError
from communication.interface import CommunicationChannel


class LoopbackChannel(CommunicationChannel):
    """A CommunicationChannel that loops sent bytes back to its own receiver."""

    def __init__(self) -> None:
        self._connected = False
        self._buffer: deque[bytes] = deque()

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        if self._connected:
            raise AlreadyConnectedError("channel is already connected")
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False
        self._buffer.clear()

    def send(self, data: bytes) -> None:
        if not self._connected:
            raise NotConnectedError("cannot send: channel is not connected")
        self._buffer.append(bytes(data))

    def receive(self) -> bytes:
        if not self._connected:
            raise NotConnectedError("cannot receive: channel is not connected")
        if not self._buffer:
            return b""
        return self._buffer.popleft()
