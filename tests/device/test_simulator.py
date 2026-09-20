from random import Random

import pytest

from core.exceptions import NotFoundError
from core.models import ChannelId, DeviceId
from device.interface import DeviceInterface
from device.simulator import (
    ConstantValueGenerator,
    RandomValueGenerator,
    SequenceValueGenerator,
    SimulatedChannel,
    SimulatorDevice,
)
from device.state import ConnectionState
from service.data_models import DataPoint
from service.data_service import DataCallback, DataService

# ---------------------------------------------------------------------------
# Value generators
# ---------------------------------------------------------------------------


def test_constant_generator_always_returns_same_value() -> None:
    generator = ConstantValueGenerator(value=7)
    assert generator.next_value() == 7
    assert generator.next_value() == 7


def test_sequence_generator_cycles_through_values() -> None:
    generator = SequenceValueGenerator(values=[1, 2, 3])
    produced = [generator.next_value() for _ in range(7)]
    assert produced == [1, 2, 3, 1, 2, 3, 1]


def test_sequence_generator_rejects_empty_values() -> None:
    with pytest.raises(ValueError):
        SequenceValueGenerator(values=[])


def test_random_generator_stays_within_bounds() -> None:
    generator = RandomValueGenerator(low=0.0, high=1.0, rng=Random(42))
    values = [generator.next_value() for _ in range(50)]
    assert all(0.0 <= value < 1.0 for value in values)


def test_random_generator_is_deterministic_given_same_seed() -> None:
    first = RandomValueGenerator(low=0.0, high=100.0, rng=Random(1))
    second = RandomValueGenerator(low=0.0, high=100.0, rng=Random(1))
    assert [first.next_value() for _ in range(10)] == [
        second.next_value() for _ in range(10)
    ]


# ---------------------------------------------------------------------------
# SimulatorDevice construction and Device abstraction conformance
# ---------------------------------------------------------------------------


def _make_device(device_id: DeviceId = "sim-1") -> SimulatorDevice:
    return SimulatorDevice(
        device_id=device_id,
        channels=[
            SimulatedChannel(channel_id="ch1", generator=ConstantValueGenerator(1)),
            SimulatedChannel(channel_id="ch2", generator=ConstantValueGenerator(2)),
        ],
    )


def test_simulator_device_requires_at_least_one_channel() -> None:
    with pytest.raises(ValueError):
        SimulatorDevice(device_id="sim-1", channels=[])


def test_simulator_device_is_connected_on_construction() -> None:
    device = _make_device()
    assert device.status.connection_state is ConnectionState.CONNECTED


def test_simulator_device_capability_reflects_configured_channels() -> None:
    device = _make_device()
    assert device.capability.has_channel("ch1")
    assert device.capability.has_channel("ch2")
    assert not device.capability.has_channel("ch3")


def test_simulator_device_satisfies_device_interface() -> None:
    device = _make_device()
    assert isinstance(device, DeviceInterface)


def test_simulator_device_exposes_underlying_device_snapshot() -> None:
    device = _make_device(device_id="sim-42")
    assert device.device.device_id == "sim-42"
    assert device.device.is_connected


# ---------------------------------------------------------------------------
# Data generation
# ---------------------------------------------------------------------------


def test_generate_produces_data_point_for_known_channel() -> None:
    device = _make_device()
    point = device.generate("ch1")
    assert point.device_id == device.device_id
    assert point.channel == "ch1"
    assert point.value == 1
    assert point.valid is True
    assert point.timestamp.tzinfo is not None


def test_generate_raises_for_unknown_channel() -> None:
    device = _make_device()
    with pytest.raises(NotFoundError):
        device.generate("unknown-channel")


def test_generate_all_returns_one_point_per_channel() -> None:
    device = _make_device()
    points = device.generate_all()
    assert {point.channel for point in points} == {"ch1", "ch2"}
    assert all(point.device_id == device.device_id for point in points)


def test_generate_pulls_a_fresh_value_each_call() -> None:
    device = SimulatorDevice(
        device_id="sim-seq",
        channels=[
            SimulatedChannel(
                channel_id="ch1", generator=SequenceValueGenerator(values=[10, 20, 30])
            )
        ],
    )
    values = [device.generate("ch1").value for _ in range(3)]
    assert values == [10, 20, 30]


# ---------------------------------------------------------------------------
# End-to-end: SimulatorDevice -> DataService -> subscriber (first flowing data)
# ---------------------------------------------------------------------------


class _InMemoryDataService(DataService):
    """Minimal DataService fake, local to this test module only."""

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


def test_publish_to_delivers_generated_point_to_subscriber() -> None:
    device = _make_device(device_id="sim-flow")
    data_service = _InMemoryDataService()
    received: list[DataPoint] = []
    data_service.subscribe("sim-flow", "ch1", received.append)

    published = device.publish_to(data_service, "ch1")

    assert received == [published]
    assert published.device_id == "sim-flow"
    assert published.channel == "ch1"


def test_publish_to_does_not_reach_subscriber_on_other_channel() -> None:
    device = _make_device(device_id="sim-flow")
    data_service = _InMemoryDataService()
    received: list[DataPoint] = []
    data_service.subscribe("sim-flow", "ch2", received.append)

    device.publish_to(data_service, "ch1")

    assert received == []
