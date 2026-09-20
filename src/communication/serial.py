"""SerialChannel: a real UART/USB-serial CommunicationChannel implementation.

Corresponds to docs/03_Communication/Communication_Design.md's UART/USB
transport sections and its "统一抽象接口"/"可替换性" design principles:
this is the first *real* (non-simulated) CommunicationChannel
implementation, alongside phase 1's communication.loopback.LoopbackChannel.
Neither communication.interface.CommunicationChannel nor LoopbackChannel is
modified by this module -- SerialChannel only implements the existing
abstract contract.

Design choices for this phase:

- **Non-blocking receive()**, to honor CommunicationChannel.receive()'s
  documented contract ("returns b'' if nothing currently available")
  without modifying that contract: the underlying ``serial.Serial`` port
  is opened with ``timeout=0`` (pyserial's non-blocking read mode), and
  receive() additionally checks ``in_waiting`` first so it never asks the
  OS to read more bytes than are already buffered. This keeps
  SerialChannel and LoopbackChannel behaviorally interchangeable from
  Protocol Layer's point of view.
- **Port existence checked explicitly**, via
  ``serial.tools.list_ports.comports()``, before attempting to open the
  port. pyserial itself raises the same ``SerialException`` whether a
  port doesn't exist or exists but can't be opened; checking existence
  first lets connect() raise a more specific
  :class:`communication.exceptions.SerialPortNotFoundError` instead of
  the generic :class:`communication.exceptions.SerialConnectionError`.
- **Every pyserial exception is translated** at this module's boundary
  into a communication.exceptions type. Callers of SerialChannel (via the
  CommunicationChannel interface) never need to import or catch pyserial
  exception types directly -- matching how LoopbackChannel never leaks a
  non-communication.exceptions error either.
"""

from __future__ import annotations

import serial
from serial.tools import list_ports

from communication.exceptions import (
    AlreadyConnectedError,
    NotConnectedError,
    SerialConnectionError,
    SerialPortNotFoundError,
    SerialReadTimeoutError,
    SerialWriteError,
)
from communication.interface import CommunicationChannel


class SerialChannel(CommunicationChannel):
    """A CommunicationChannel backed by a real UART/USB-serial port (pyserial)."""

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        write_timeout: float = 1.0,
    ) -> None:
        self._port = port
        self._baudrate = baudrate
        self._write_timeout = write_timeout
        self._serial: serial.Serial | None = None

    @property
    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def connect(self) -> None:
        if self.is_connected:
            raise AlreadyConnectedError("channel is already connected")

        available_ports = {info.device for info in list_ports.comports()}
        if self._port not in available_ports:
            raise SerialPortNotFoundError(f"serial port not found: {self._port!r}")

        try:
            self._serial = serial.Serial(
                port=self._port,
                baudrate=self._baudrate,
                timeout=0,
                write_timeout=self._write_timeout,
            )
        except serial.SerialException as exc:
            raise SerialConnectionError(
                f"failed to open serial port {self._port!r}: {exc}"
            ) from exc

    def disconnect(self) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None

    def send(self, data: bytes) -> None:
        serial_port = self._serial
        if serial_port is None or not serial_port.is_open:
            raise NotConnectedError("cannot send: channel is not connected")
        try:
            serial_port.write(bytes(data))
        except serial.SerialTimeoutException as exc:
            raise SerialWriteError(f"write to {self._port!r} timed out") from exc
        except serial.SerialException as exc:
            raise SerialWriteError(f"write to {self._port!r} failed: {exc}") from exc

    def receive(self) -> bytes:
        serial_port = self._serial
        if serial_port is None or not serial_port.is_open:
            raise NotConnectedError("cannot receive: channel is not connected")
        try:
            waiting = serial_port.in_waiting
            if not waiting:
                return b""
            return bytes(serial_port.read(waiting))
        except serial.SerialException as exc:
            raise SerialReadTimeoutError(
                f"read from {self._port!r} failed or timed out: {exc}"
            ) from exc
