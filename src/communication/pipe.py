"""PipeChannel: two in-memory channel ends joined back to back, like a
null-modem cable with no cable.

Added 2026-09-23 for the ``virtual`` run mode
(docs/02_Architecture/Web_Console_Design.md section 5.1): an in-process
virtual STM32 writes real protocol frames into one end, and the host's
ordinary Hardware-mode receiver reads them from the other -- so the whole
receive chain, frame sync included, runs without a board or a virtual COM
port driver.

**The difference from LoopbackChannel is the whole point.** Loopback hands
back each ``send()`` as one ``receive()`` -- it preserves message
boundaries, which is exactly the property a real serial port does not have
and which once hid four defects from Simulator mode (thesis chapter 5,
section 5.3). A pipe end's ``receive()`` returns *everything* that has
arrived, however many writes it came in: frames arrive concatenated, and a
writer that splits a frame across writes produces half-frames. That is what
the frame-sync code exists to handle, and what the web console's protocol
inspector exists to show.

Thread-safe: the virtual device writes from its own thread while the host
reads from the runtime's driver thread.

Like every concrete channel, create it only in ``application`` or
``scripts`` (``CLAUDE.md``).
"""

from __future__ import annotations

import threading

from communication.exceptions import AlreadyConnectedError, NotConnectedError
from communication.interface import CommunicationChannel


class _Inbox:
    """Bytes waiting to be read by one end."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.data = bytearray()


class PipeChannel(CommunicationChannel):
    """One end of a pipe. Build a joined pair with :func:`make_pipe_pair`."""

    def __init__(self, inbox: _Inbox, peer_inbox: _Inbox) -> None:
        self._inbox = inbox
        self._peer_inbox = peer_inbox
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        if self._connected:
            raise AlreadyConnectedError("channel is already connected")
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False
        with self._inbox.lock:
            self._inbox.data.clear()

    def send(self, data: bytes) -> None:
        """Append ``data`` to what the other end will read.

        Delivered whether or not the other end has connected yet, as bytes
        on a real wire are: a device that starts transmitting before the
        host opens its port does not get an error, the host just finds
        them waiting.
        """
        if not self._connected:
            raise NotConnectedError("cannot send: channel is not connected")
        with self._peer_inbox.lock:
            self._peer_inbox.data.extend(data)

    def receive(self) -> bytes:
        """Return every byte that has arrived since the last call."""
        if not self._connected:
            raise NotConnectedError("cannot receive: channel is not connected")
        with self._inbox.lock:
            chunk = bytes(self._inbox.data)
            self._inbox.data.clear()
        return chunk


def make_pipe_pair() -> tuple[PipeChannel, PipeChannel]:
    """Return ``(host_end, device_end)``: what one sends, the other receives."""
    host_inbox, device_inbox = _Inbox(), _Inbox()
    host = PipeChannel(inbox=host_inbox, peer_inbox=device_inbox)
    device = PipeChannel(inbox=device_inbox, peer_inbox=host_inbox)
    return host, device
