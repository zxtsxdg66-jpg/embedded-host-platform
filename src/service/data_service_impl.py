"""Concrete DataService: in-memory, synchronous publish/subscribe.

Corresponds to docs/02_Architecture/Core_Service_Design.md Section 4
("data processing and distribution"). Delivery is synchronous and
in-process for phase 1 -- a subscriber's callback runs on the calling
thread inside publish(), matching every other phase-1 module's choice to
defer async/event-driven behaviour (see communication/interface.py) until
a real transport makes it necessary.

Not bound to any specific device or channel: subscriptions are plain
(device_id, channel) pairs, matched exactly against each published
DataPoint.
"""

from __future__ import annotations

from itertools import count

from core.models import ChannelId, DeviceId
from service.data_models import DataPoint
from service.data_service import DataCallback, DataService


class InMemoryDataService(DataService):
    """Synchronous, in-memory implementation of the DataService contract."""

    def __init__(self) -> None:
        self._subscriptions: dict[str, tuple[DeviceId, ChannelId, DataCallback]] = {}
        self._next_id = count(1)

    def subscribe(
        self, device_id: DeviceId, channel: ChannelId, callback: DataCallback
    ) -> str:
        subscription_id = f"sub-{next(self._next_id)}"
        self._subscriptions[subscription_id] = (device_id, channel, callback)
        return subscription_id

    def unsubscribe(self, subscription_id: str) -> None:
        self._subscriptions.pop(subscription_id, None)

    def publish(self, data_point: DataPoint) -> None:
        for device_id, channel, callback in self._subscriptions.values():
            if device_id == data_point.device_id and channel == data_point.channel:
                callback(data_point)
