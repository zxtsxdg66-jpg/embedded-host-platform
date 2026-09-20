"""Communication channel abstract interface: unified byte-level transport contract.

Corresponds to docs/03_Communication/Communication_Design.md's "接口设计原则"
Section, principle 1 ("统一抽象接口"): every transport medium (UART, USB,
TCP/IP, Bluetooth, and this phase's Loopback) implements the same contract,
so Protocol Layer and Application Layer never need to know which one they
are talking to.

Communication Layer scope, by design:
- Only moves bytes. It does not parse frames (that is protocol/), does not
  know about devices or services (that is device/ and service/), and is
  not bound to any specific transport medium.
- Phase 1 keeps the contract synchronous and queue-based (send() enqueues,
  receive() dequeues), matching Communication_Design.md's "回调或数据队列"
  wording for the upstream data path. Design principle 2 ("异步非阻塞") and
  principle 3's callback-based state notifications (``on_data_received`` /
  ``on_state_changed``) are deferred to a later phase once a real transport
  (e.g. UART) makes blocking I/O an actual concern; ``is_connected`` is the
  minimal observable-state surface phase 1 needs to satisfy principle 3
  ("状态可观测") without building that event machinery prematurely.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class CommunicationChannel(ABC):
    """Unified byte-transport contract implemented by every communication medium."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Whether the channel is currently connected."""

    @abstractmethod
    def connect(self) -> None:
        """Establish the connection.

        Implementations should raise
        :class:`communication.exceptions.AlreadyConnectedError` if the
        channel is already connected.
        """

    @abstractmethod
    def disconnect(self) -> None:
        """Tear down the connection. Safe to call even if not connected."""

    @abstractmethod
    def send(self, data: bytes) -> None:
        """Send raw bytes over the channel.

        Implementations should raise
        :class:`communication.exceptions.NotConnectedError` if the channel
        is not connected. Content is opaque -- no parsing or validation of
        ``data`` happens at this layer.
        """

    @abstractmethod
    def receive(self) -> bytes:
        """Return the next chunk of bytes available on the channel.

        Returns ``b""`` if nothing is currently available (non-blocking).
        Implementations should raise
        :class:`communication.exceptions.NotConnectedError` if the channel
        is not connected.
        """
