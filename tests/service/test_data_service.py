import pytest

from core.models import ChannelId, DeviceId
from service.data_models import DataPoint
from service.data_service import DataCallback, DataService


def test_data_service_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        DataService()  # type: ignore[abstract]


class _InMemoryDataService(DataService):
    """Minimal fake used only to prove the abstract contract is implementable."""

    def __init__(self) -> None:
        self._subscribers: dict[str, tuple[DeviceId, ChannelId, DataCallback]] = {}

    def subscribe(
        self, device_id: DeviceId, channel: ChannelId, callback: DataCallback
    ) -> str:
        subscription_id = f"{device_id}:{channel}:{len(self._subscribers)}"
        self._subscribers[subscription_id] = (device_id, channel, callback)
        return subscription_id

    def unsubscribe(self, subscription_id: str) -> None:
        self._subscribers.pop(subscription_id, None)

    def publish(self, data_point: DataPoint) -> None:
        for device_id, channel, callback in self._subscribers.values():
            if device_id == data_point.device_id and channel == data_point.channel:
                callback(data_point)


def test_subscriber_receives_matching_data_point() -> None:
    received: list[DataPoint] = []
    service = _InMemoryDataService()
    service.subscribe("dev-1", "ch1", received.append)

    point = DataPoint(device_id="dev-1", channel="ch1", value=1)
    service.publish(point)

    assert received == [point]


def test_subscriber_does_not_receive_unrelated_channel() -> None:
    received: list[DataPoint] = []
    service = _InMemoryDataService()
    service.subscribe("dev-1", "ch1", received.append)

    other_channel_point = DataPoint(device_id="dev-1", channel="ch2", value=1)
    service.publish(other_channel_point)

    assert received == []


def test_unsubscribe_stops_further_delivery() -> None:
    received: list[DataPoint] = []
    service = _InMemoryDataService()
    subscription_id = service.subscribe("dev-1", "ch1", received.append)
    service.unsubscribe(subscription_id)

    service.publish(DataPoint(device_id="dev-1", channel="ch1", value=1))

    assert received == []
