import inspect

import pytest

from communication.interface import CommunicationChannel


def test_communication_channel_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        CommunicationChannel()  # type: ignore[abstract]


def test_communication_channel_declares_expected_abstract_members() -> None:
    assert CommunicationChannel.__abstractmethods__ == frozenset(
        {"is_connected", "connect", "disconnect", "send", "receive"}
    )


def test_is_connected_is_a_property() -> None:
    assert isinstance(
        inspect.getattr_static(CommunicationChannel, "is_connected"), property
    )


def test_minimal_subclass_can_implement_contract() -> None:
    class _NullChannel(CommunicationChannel):
        def __init__(self) -> None:
            self._connected = False

        @property
        def is_connected(self) -> bool:
            return self._connected

        def connect(self) -> None:
            self._connected = True

        def disconnect(self) -> None:
            self._connected = False

        def send(self, data: bytes) -> None:
            pass

        def receive(self) -> bytes:
            return b""

    channel = _NullChannel()
    assert not channel.is_connected
    channel.connect()
    assert channel.is_connected
    channel.send(b"x")
    assert channel.receive() == b""
