import pytest

from communication.exceptions import AlreadyConnectedError, NotConnectedError
from communication.interface import CommunicationChannel
from communication.loopback import LoopbackChannel


def test_loopback_channel_satisfies_communication_channel() -> None:
    channel = LoopbackChannel()
    assert isinstance(channel, CommunicationChannel)


def test_loopback_channel_starts_disconnected() -> None:
    channel = LoopbackChannel()
    assert not channel.is_connected


def test_connect_marks_channel_connected() -> None:
    channel = LoopbackChannel()
    channel.connect()
    assert channel.is_connected


def test_connect_twice_raises() -> None:
    channel = LoopbackChannel()
    channel.connect()
    with pytest.raises(AlreadyConnectedError):
        channel.connect()


def test_disconnect_marks_channel_not_connected() -> None:
    channel = LoopbackChannel()
    channel.connect()
    channel.disconnect()
    assert not channel.is_connected


def test_disconnect_when_not_connected_does_not_raise() -> None:
    channel = LoopbackChannel()
    channel.disconnect()
    assert not channel.is_connected


def test_send_before_connect_raises() -> None:
    channel = LoopbackChannel()
    with pytest.raises(NotConnectedError):
        channel.send(b"data")


def test_receive_before_connect_raises() -> None:
    channel = LoopbackChannel()
    with pytest.raises(NotConnectedError):
        channel.receive()


def test_receive_with_no_data_returns_empty_bytes() -> None:
    channel = LoopbackChannel()
    channel.connect()
    assert channel.receive() == b""


def test_send_then_receive_returns_same_bytes() -> None:
    channel = LoopbackChannel()
    channel.connect()
    channel.send(b"\x01\x02\x03")
    assert channel.receive() == b"\x01\x02\x03"


def test_multiple_sends_are_received_in_fifo_order() -> None:
    channel = LoopbackChannel()
    channel.connect()
    channel.send(b"first")
    channel.send(b"second")
    channel.send(b"third")

    assert channel.receive() == b"first"
    assert channel.receive() == b"second"
    assert channel.receive() == b"third"
    assert channel.receive() == b""


def test_send_accepts_bytearray_and_receive_returns_bytes() -> None:
    channel = LoopbackChannel()
    channel.connect()
    channel.send(bytearray(b"\xaa\x55"))
    received = channel.receive()
    assert received == b"\xaa\x55"
    assert isinstance(received, bytes)


def test_disconnect_clears_pending_buffer() -> None:
    channel = LoopbackChannel()
    channel.connect()
    channel.send(b"pending")
    channel.disconnect()
    channel.connect()
    assert channel.receive() == b""


def test_simulates_bidirectional_communication_via_two_channel_ends() -> None:
    """Two LoopbackChannel instances model a two-endpoint round trip.

    Each end loops its own outgoing bytes back to itself, so a request/
    response exchange is simulated by writing to each end's own buffer.
    """
    end_a = LoopbackChannel()
    end_b = LoopbackChannel()
    end_a.connect()
    end_b.connect()

    end_a.send(b"request")
    end_b.send(b"response")

    assert end_a.receive() == b"request"
    assert end_b.receive() == b"response"


def test_independent_channel_instances_do_not_share_buffers() -> None:
    channel_one = LoopbackChannel()
    channel_two = LoopbackChannel()
    channel_one.connect()
    channel_two.connect()

    channel_one.send(b"only for one")

    assert channel_one.receive() == b"only for one"
    assert channel_two.receive() == b""
