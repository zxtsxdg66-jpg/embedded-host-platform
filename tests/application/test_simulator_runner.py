"""Tests for application.simulator_runner.

The gap this driver closes is worth stating in a test: before it existed,
composing a SimulatorDevice the way a launcher script does and then
subscribing produced *no* data at all, because nothing called
report_data() outside the test suite.
"""

from __future__ import annotations

import pytest

from application.runtime import ApplicationRuntime
from application.simulator_runner import SimulatorRuntimeRunner
from communication.loopback import LoopbackChannel
from device.simulator import (
    SequenceValueGenerator,
    SimulatedChannel,
    SimulatorDevice,
)
from service.data_models import DataPoint


def _runtime_with_device() -> ApplicationRuntime:
    runtime = ApplicationRuntime()
    device = SimulatorDevice(
        device_id="sim-1",
        channels=[
            SimulatedChannel(
                channel_id="ch1", generator=SequenceValueGenerator(values=[1, 2, 3])
            )
        ],
    )
    runtime.register_device(device, LoopbackChannel(), accepted_commands=("PING",))
    return runtime


def test_run_once_publishes_to_subscribers() -> None:
    runtime = _runtime_with_device()
    received: list[DataPoint] = []
    runtime.subscribe("sim-1", "ch1", received.append)

    SimulatorRuntimeRunner(runtime, [("sim-1", "ch1")]).run_once()

    assert len(received) == 1


def test_run_once_returns_generated_points() -> None:
    runtime = _runtime_with_device()

    points = SimulatorRuntimeRunner(runtime, [("sim-1", "ch1")]).run_once()

    assert len(points) == 1
    assert points[0].device_id == "sim-1"
    assert points[0].channel == "ch1"


def test_successive_calls_advance_the_generator() -> None:
    runtime = _runtime_with_device()
    runner = SimulatorRuntimeRunner(runtime, [("sim-1", "ch1")])

    values = [runner.run_once()[0].value for _ in range(3)]

    assert values == [1, 2, 3]


def test_unknown_target_is_counted_not_raised() -> None:
    """One bad target must not break the driver loop -- same isolation
    principle as HardwareRuntimeRunner.run_once()."""
    runtime = _runtime_with_device()
    runner = SimulatorRuntimeRunner(runtime, [("unknown-device", "ch1")])

    points = runner.run_once()

    assert points == []
    assert runner.error_count == 1
    assert runner.last_error is not None


def test_a_failing_target_does_not_block_the_others() -> None:
    runtime = _runtime_with_device()
    runner = SimulatorRuntimeRunner(
        runtime, [("unknown-device", "ch1"), ("sim-1", "ch1")]
    )

    points = runner.run_once()

    assert len(points) == 1
    assert points[0].device_id == "sim-1"
    assert runner.error_count == 1


def test_start_and_stop_toggle_running() -> None:
    runner = SimulatorRuntimeRunner(_runtime_with_device(), [("sim-1", "ch1")])
    assert runner.running is False

    runner.start()
    assert runner.running is True

    runner.stop()
    assert runner.running is False


def test_run_once_works_even_when_not_started() -> None:
    """``running`` is metadata for an external driver, not a gate -- same
    contract as HardwareRuntimeRunner."""
    runtime = _runtime_with_device()
    runner = SimulatorRuntimeRunner(runtime, [("sim-1", "ch1")])

    assert len(runner.run_once()) == 1


def test_non_positive_interval_rejected() -> None:
    with pytest.raises(ValueError):
        SimulatorRuntimeRunner(_runtime_with_device(), [], poll_interval_seconds=0)
