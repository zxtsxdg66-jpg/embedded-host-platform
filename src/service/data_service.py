"""Data service base interface: subscription-based data distribution.

Corresponds to docs/architecture.md
(Service Layer responsibilities -- "data processing and distribution") and
Section 5 (identical interface used by both PC and Android callers,
whether the implementation lives locally or behind a future gateway).

This module defines the contract only; no concrete implementation, storage,
or dispatch mechanism is provided here, and none of it is bound to any
specific device or communication method.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from core.models import ChannelId, DeviceId
from service.data_models import DataPoint

DataCallback = Callable[[DataPoint], None]
"""Callback invoked with each DataPoint delivered to a subscriber."""


class DataService(ABC):
    """Base interface for subscribing to and distributing device data."""

    @abstractmethod
    def subscribe(
        self, device_id: DeviceId, channel: ChannelId, callback: DataCallback
    ) -> str:
        """Register ``callback`` for updates on ``device_id``/``channel``.

        Returns an opaque subscription id that can later be passed to
        :meth:`unsubscribe`.
        """

    @abstractmethod
    def unsubscribe(self, subscription_id: str) -> None:
        """Remove a previously registered subscription, if it still exists."""

    @abstractmethod
    def publish(self, data_point: DataPoint) -> None:
        """Distribute ``data_point`` to every subscriber matching its device/channel."""
