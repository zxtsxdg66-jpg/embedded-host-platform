"""End-to-end data pipeline: SimulatorDevice -> Protocol -> Communication -> Service."""

import pytest

from application.runtime import ApplicationRuntime
from communication.loopback import LoopbackChannel
from core.exceptions import NotFoundError
from device.simulator import (
    ConstantValueGenerator,
    SequenceValueGenerator,
    SimulatedChannel,
    SimulatorDevice,
)
from service.data_models import DataPoint


def _make_runtime_with_device(
    device_id: str = "sim-1",
) -> tuple[ApplicationRuntime, SimulatorDevice]:
    runtime = ApplicationRuntime()
    device = SimulatorDevice(
        device_id=device_id,
        channels=[
            SimulatedChannel(channel_id="ch1", generator=ConstantValueGenerator(42)),
            SimulatedChannel(channel_id="ch2", generator=ConstantValueGenerator("ok")),
        ],
    )
    runtime.register_device(device, LoopbackChannel())
    return runtime, device


def test_report_data_returns_reconstructed_data_point() -> None:
    runtime, _ = _make_runtime_with_device()

    point = runtime.report_data("sim-1", "ch1")

    assert isinstance(point, DataPoint)
    assert point.device_id == "sim-1"
    assert point.channel == "ch1"
    assert point.value == 42


def test_subscriber_receives_data_through_full_pipeline() -> None:
    runtime, _ = _make_runtime_with_device()
    received: list[DataPoint] = []
    runtime.subscribe("sim-1", "ch1", received.append)

    published = runtime.report_data("sim-1", "ch1")

    assert received == [published]


def test_subscriber_on_other_channel_does_not_receive() -> None:
    runtime, _ = _make_runtime_with_device()
    received: list[DataPoint] = []
    runtime.subscribe("sim-1", "ch2", received.append)

    runtime.report_data("sim-1", "ch1")

    assert received == []


def test_unsubscribe_stops_delivery() -> None:
    runtime, _ = _make_runtime_with_device()
    received: list[DataPoint] = []
    subscription_id = runtime.subscribe("sim-1", "ch1", received.append)
    runtime.unsubscribe(subscription_id)

    runtime.report_data("sim-1", "ch1")

    assert received == []


def test_multiple_channels_are_independently_delivered() -> None:
    runtime, _ = _make_runtime_with_device()
    ch1_received: list[DataPoint] = []
    ch2_received: list[DataPoint] = []
    runtime.subscribe("sim-1", "ch1", ch1_received.append)
    runtime.subscribe("sim-1", "ch2", ch2_received.append)

    runtime.report_data("sim-1", "ch1")
    runtime.report_data("sim-1", "ch2")

    assert len(ch1_received) == 1 and ch1_received[0].value == 42
    assert len(ch2_received) == 1 and ch2_received[0].value == "ok"


def test_sequence_generator_values_change_across_report_cycles() -> None:
    runtime = ApplicationRuntime()
    device = SimulatorDevice(
        device_id="sim-seq",
        channels=[
            SimulatedChannel(
                channel_id="ch1", generator=SequenceValueGenerator(values=[1, 2, 3])
            )
        ],
    )
    runtime.register_device(device, LoopbackChannel())

    values = [runtime.report_data("sim-seq", "ch1").value for _ in range(3)]

    assert values == [1, 2, 3]


def test_report_data_for_unregistered_device_raises() -> None:
    runtime = ApplicationRuntime()
    with pytest.raises(NotFoundError):
        runtime.report_data("unknown", "ch1")


def test_two_devices_on_independent_channels_do_not_interfere() -> None:
    runtime = ApplicationRuntime()
    device_one = SimulatorDevice(
        device_id="sim-a",
        channels=[
            SimulatedChannel(channel_id="ch1", generator=ConstantValueGenerator(1))
        ],
    )
    device_two = SimulatorDevice(
        device_id="sim-b",
        channels=[
            SimulatedChannel(channel_id="ch1", generator=ConstantValueGenerator(2))
        ],
    )
    runtime.register_device(device_one, LoopbackChannel())
    runtime.register_device(device_two, LoopbackChannel())

    received_a: list[DataPoint] = []
    received_b: list[DataPoint] = []
    runtime.subscribe("sim-a", "ch1", received_a.append)
    runtime.subscribe("sim-b", "ch1", received_b.append)

    runtime.report_data("sim-a", "ch1")
    runtime.report_data("sim-b", "ch1")

    assert [p.value for p in received_a] == [1]
    assert [p.value for p in received_b] == [2]
