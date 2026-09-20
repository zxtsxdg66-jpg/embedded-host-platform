"""Tests for communication.serial.SerialChannel.

No real hardware is available in this environment, so pyserial's
``serial.Serial`` constructor and ``serial.tools.list_ports.comports()``
are replaced with test doubles rather than exercised against a physical or
virtual COM port -- per the task's "使用 mock 或虚拟串口方式测试" allowance.
``_FakeSerialPort`` below is a small, explicit "virtual serial port": it
implements just the subset of pyserial's ``Serial`` surface SerialChannel
actually uses (``is_open``, ``write``, ``in_waiting``, ``read``,
``close``), and lets each test configure exactly when a failure should
occur.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
import serial

from communication.exceptions import (
    AlreadyConnectedError,
    NotConnectedError,
    SerialConnectionError,
    SerialPortNotFoundError,
    SerialReadTimeoutError,
    SerialWriteError,
)
from communication.interface import CommunicationChannel
from communication.serial import SerialChannel


class _FakeSerialPort:
    """A minimal virtual stand-in for serial.Serial."""

    def __init__(self) -> None:
        self.is_open = True
        self.write_calls: list[bytes] = []
        self.buffer = bytearray()
        self.write_exception: Exception | None = None
        self.read_exception: Exception | None = None

    def write(self, data: bytes) -> int:
        if self.write_exception is not None:
            raise self.write_exception
        self.write_calls.append(bytes(data))
        return len(data)

    @property
    def in_waiting(self) -> int:
        if self.read_exception is not None:
            raise self.read_exception
        return len(self.buffer)

    def read(self, size: int) -> bytes:
        chunk = bytes(self.buffer[:size])
        del self.buffer[:size]
        return chunk

    def close(self) -> None:
        self.is_open = False


def _available_port(device: str = "COM3") -> SimpleNamespace:
    return SimpleNamespace(device=device)


def _connected_channel() -> tuple[SerialChannel, _FakeSerialPort]:
    channel = SerialChannel(port="COM3")
    port = _FakeSerialPort()
    with patch(
        "communication.serial.list_ports.comports", return_value=[_available_port()]
    ):
        with patch("communication.serial.serial.Serial", return_value=port):
            channel.connect()
    return channel, port


# -- interface conformance --------------------------------------------------


def test_serial_channel_satisfies_communication_channel() -> None:
    assert isinstance(SerialChannel(port="COM3"), CommunicationChannel)


# -- connect(): 串口不存在 / 连接失败 -----------------------------------------


def test_connect_raises_port_not_found_when_port_missing() -> None:
    channel = SerialChannel(port="COM3")
    with patch("communication.serial.list_ports.comports", return_value=[]):
        with pytest.raises(SerialPortNotFoundError):
            channel.connect()
    assert not channel.is_connected


def test_connect_does_not_attempt_to_open_when_port_missing() -> None:
    channel = SerialChannel(port="COM3")
    with patch("communication.serial.list_ports.comports", return_value=[]):
        with patch("communication.serial.serial.Serial") as serial_ctor:
            with pytest.raises(SerialPortNotFoundError):
                channel.connect()
            serial_ctor.assert_not_called()


def test_connect_success_opens_port_with_configured_parameters() -> None:
    channel = SerialChannel(port="COM3", baudrate=9600, write_timeout=2.0)
    fake_port = _FakeSerialPort()
    with patch(
        "communication.serial.list_ports.comports", return_value=[_available_port()]
    ):
        with patch(
            "communication.serial.serial.Serial", return_value=fake_port
        ) as serial_ctor:
            channel.connect()

    assert channel.is_connected
    serial_ctor.assert_called_once_with(
        port="COM3", baudrate=9600, timeout=0, write_timeout=2.0
    )


def test_connect_raises_serial_connection_error_when_open_fails() -> None:
    channel = SerialChannel(port="COM3")
    with patch(
        "communication.serial.list_ports.comports", return_value=[_available_port()]
    ):
        with patch(
            "communication.serial.serial.Serial",
            side_effect=serial.SerialException("Access is denied"),
        ):
            with pytest.raises(SerialConnectionError):
                channel.connect()
    assert not channel.is_connected


def test_connect_twice_raises_already_connected() -> None:
    channel, _port = _connected_channel()
    with patch(
        "communication.serial.list_ports.comports", return_value=[_available_port()]
    ):
        with pytest.raises(AlreadyConnectedError):
            channel.connect()


# -- disconnect() -------------------------------------------------------------


def test_disconnect_closes_port_and_marks_not_connected() -> None:
    channel, port = _connected_channel()

    channel.disconnect()

    assert not channel.is_connected
    assert port.is_open is False


def test_disconnect_when_not_connected_does_not_raise() -> None:
    channel = SerialChannel(port="COM3")
    channel.disconnect()
    assert not channel.is_connected


def test_reconnect_after_disconnect_succeeds() -> None:
    channel, _port = _connected_channel()
    channel.disconnect()

    with patch(
        "communication.serial.list_ports.comports", return_value=[_available_port()]
    ):
        with patch(
            "communication.serial.serial.Serial", return_value=_FakeSerialPort()
        ):
            channel.connect()

    assert channel.is_connected


# -- send() ---------------------------------------------------------------------


def test_send_before_connect_raises_not_connected() -> None:
    channel = SerialChannel(port="COM3")
    with pytest.raises(NotConnectedError):
        channel.send(b"\x01")


def test_send_writes_bytes_to_port() -> None:
    channel, port = _connected_channel()

    channel.send(b"\x01\x02\x03")

    assert port.write_calls == [b"\x01\x02\x03"]


def test_send_accepts_bytearray() -> None:
    channel, port = _connected_channel()

    channel.send(bytearray(b"\xaa\x55"))

    assert port.write_calls == [b"\xaa\x55"]


def test_send_after_disconnect_raises_not_connected() -> None:
    channel, _port = _connected_channel()
    channel.disconnect()

    with pytest.raises(NotConnectedError):
        channel.send(b"\x01")


# -- send(): 读取超时对应的写入侧异常也需要转译（写超时/写失败） ------------------


def test_send_write_timeout_raises_serial_write_error() -> None:
    channel, port = _connected_channel()
    port.write_exception = serial.SerialTimeoutException("write timeout")

    with pytest.raises(SerialWriteError):
        channel.send(b"\x01")


def test_send_generic_serial_failure_raises_serial_write_error() -> None:
    channel, port = _connected_channel()
    port.write_exception = serial.SerialException("device removed")

    with pytest.raises(SerialWriteError):
        channel.send(b"\x01")


# -- receive(): 读取超时 ----------------------------------------------------------


def test_receive_before_connect_raises_not_connected() -> None:
    channel = SerialChannel(port="COM3")
    with pytest.raises(NotConnectedError):
        channel.receive()


def test_receive_returns_empty_bytes_when_nothing_available() -> None:
    channel, _port = _connected_channel()

    assert channel.receive() == b""


def test_receive_returns_available_bytes_and_drains_them() -> None:
    channel, port = _connected_channel()
    port.buffer.extend(b"\x01\x02\x03")

    first = channel.receive()
    second = channel.receive()

    assert first == b"\x01\x02\x03"
    assert second == b""


def test_receive_reads_only_whats_currently_buffered() -> None:
    channel, port = _connected_channel()
    port.buffer.extend(b"\x01\x02")

    first = channel.receive()
    port.buffer.extend(b"\x03")
    second = channel.receive()

    assert first == b"\x01\x02"
    assert second == b"\x03"


def test_receive_failure_raises_serial_read_timeout_error() -> None:
    channel, port = _connected_channel()
    port.read_exception = serial.SerialException(
        "device reports readiness to read but returned no data"
    )

    with pytest.raises(SerialReadTimeoutError):
        channel.receive()


def test_receive_after_disconnect_raises_not_connected() -> None:
    channel, _port = _connected_channel()
    channel.disconnect()

    with pytest.raises(NotConnectedError):
        channel.receive()
