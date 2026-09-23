"""Tests for communication.pipe -- the in-memory byte pipe behind the
``virtual`` run mode.

The property that matters is the one LoopbackChannel lacks: **no message
boundaries**. Several writes arrive as one read, exactly as on a UART.
"""

from __future__ import annotations

import pytest

from communication.exceptions import NotConnectedError
from communication.pipe import make_pipe_pair


def _connected_pair():
    host, device = make_pipe_pair()
    host.connect()
    device.connect()
    return host, device


def test_what_one_end_sends_the_other_receives() -> None:
    host, device = _connected_pair()
    device.send(b"\xaa\x55")
    assert host.receive() == b"\xaa\x55"
    host.send(b"ack")
    assert device.receive() == b"ack"


def test_writes_are_not_kept_apart() -> None:
    """Three writes, one read: the boundaries a real port would not keep."""
    host, device = _connected_pair()
    for part in (b"one", b"two", b"three"):
        device.send(part)
    assert host.receive() == b"onetwothree"


def test_a_read_empties_the_inbox() -> None:
    host, device = _connected_pair()
    device.send(b"x")
    host.receive()
    assert host.receive() == b""


def test_an_end_does_not_hear_itself() -> None:
    host, device = _connected_pair()
    host.send(b"cmd")
    assert host.receive() == b""
    assert device.receive() == b"cmd"


def test_bytes_sent_before_the_peer_connects_are_waiting_for_it() -> None:
    host, device = make_pipe_pair()
    device.connect()
    device.send(b"early")
    host.connect()
    assert host.receive() == b"early"


def test_an_unconnected_end_refuses_both_directions() -> None:
    host, _ = make_pipe_pair()
    with pytest.raises(NotConnectedError):
        host.send(b"x")
    with pytest.raises(NotConnectedError):
        host.receive()
