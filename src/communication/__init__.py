"""Communication: transport-medium adapters (UART/USB/TCP-IP/Bluetooth)
behind a unified interface.

Currently implemented: the CommunicationChannel abstract interface, the
communication exception hierarchy, LoopbackChannel (phase 1, an in-memory,
transport-free implementation for software-only verification), and
SerialChannel (phase 2, a real UART/USB-serial implementation based on
pyserial). TCP-IP/Bluetooth are not yet implemented. See
src/communication/README.md for the full module scope.
"""

from communication.exceptions import (
    AlreadyConnectedError,
    CommunicationError,
    NotConnectedError,
    SerialConnectionError,
    SerialPortNotFoundError,
    SerialReadTimeoutError,
    SerialWriteError,
)
from communication.interface import CommunicationChannel
from communication.loopback import LoopbackChannel
from communication.serial import SerialChannel

__all__ = [
    "CommunicationChannel",
    "LoopbackChannel",
    "SerialChannel",
    "CommunicationError",
    "NotConnectedError",
    "AlreadyConnectedError",
    "SerialPortNotFoundError",
    "SerialConnectionError",
    "SerialReadTimeoutError",
    "SerialWriteError",
]
