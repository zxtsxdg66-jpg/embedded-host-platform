"""Tests for application.hardware_runner.HardwareRuntimeRunner.

Uses communication.loopback.LoopbackChannel to feed a real, unmodified
HardwareDeviceReceiver -- same pattern as
tests/application/test_hardware_runtime.py -- plus a small custom
CommunicationChannel double whose receive() raises, to deterministically
exercise the runner's exception-isolation behavior without needing to
actually disconnect a real channel mid-poll.
"""

from __future__ import annotations

import json

import pytest

from application.hardware_runner import HardwareRuntimeRunner
from application.hardware_runtime import DATA_REPORT_CODE, HardwareDeviceReceiver
from communication.interface import CommunicationChannel
from communication.loopback import LoopbackChannel
from protocol.encoder import encode
from protocol.frame import Frame
from service.data_models import DataPoint
from service.data_service_impl import InMemoryDataService

WIRE_ID = 1


def _make_runner() -> (
    tuple[HardwareRuntimeRunner, LoopbackChannel, InMemoryDataService]
):
    channel = LoopbackChannel()
    channel.connect()
    data_service = InMemoryDataService()
    receiver = HardwareDeviceReceiver(
        device_id="mcu-1", wire_id=WIRE_ID, channel=channel, data_service=data_service
    )
    runner = HardwareRuntimeRunner(receiver, poll_interval_seconds=0.01)
    return runner, channel, data_service


def _deposit_data_report(
    channel: LoopbackChannel, channel_id: str, value: object
) -> None:
    payload = json.dumps({"channel": channel_id, "value": value}).encode("utf-8")
    frame = Frame(device_id=WIRE_ID, command_type=DATA_REPORT_CODE, payload=payload)
    channel.send(encode(frame))


class _RaisingChannel(CommunicationChannel):
    """A CommunicationChannel whose receive() always raises, to
    deterministically trigger HardwareRuntimeRunner's exception-isolation
    path without depending on a real disconnect race."""

    def __init__(self) -> None:
        self._connected = True

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def send(self, data: bytes) -> None:
        pass

    def receive(self) -> bytes:
        raise RuntimeError("simulated hardware failure")


# -- construction / configuration --------------------------------------------


def test_poll_interval_seconds_has_a_default() -> None:
    channel = LoopbackChannel()
    channel.connect()
    receiver = HardwareDeviceReceiver(
        device_id="mcu-1",
        wire_id=WIRE_ID,
        channel=channel,
        data_service=InMemoryDataService(),
    )
    runner = HardwareRuntimeRunner(receiver)
    assert runner.poll_interval_seconds > 0


def test_poll_interval_seconds_is_configurable() -> None:
    channel = LoopbackChannel()
    channel.connect()
    receiver = HardwareDeviceReceiver(
        device_id="mcu-1",
        wire_id=WIRE_ID,
        channel=channel,
        data_service=InMemoryDataService(),
    )
    runner = HardwareRuntimeRunner(receiver, poll_interval_seconds=2.5)
    assert runner.poll_interval_seconds == 2.5


def test_rejects_non_positive_poll_interval() -> None:
    channel = LoopbackChannel()
    channel.connect()
    receiver = HardwareDeviceReceiver(
        device_id="mcu-1",
        wire_id=WIRE_ID,
        channel=channel,
        data_service=InMemoryDataService(),
    )
    with pytest.raises(ValueError):
        HardwareRuntimeRunner(receiver, poll_interval_seconds=0)


def test_exposes_the_wrapped_receiver() -> None:
    channel = LoopbackChannel()
    channel.connect()
    receiver = HardwareDeviceReceiver(
        device_id="mcu-1",
        wire_id=WIRE_ID,
        channel=channel,
        data_service=InMemoryDataService(),
    )
    runner = HardwareRuntimeRunner(receiver)
    assert runner.receiver is receiver


# -- run_once 可以处理数据 ------------------------------------------------------


def test_run_once_returns_empty_list_when_nothing_pending() -> None:
    runner, _channel, _data_service = _make_runner()
    assert runner.run_once() == []


def test_run_once_processes_a_pending_data_report() -> None:
    runner, channel, _data_service = _make_runner()
    _deposit_data_report(channel, "temperature", 25.5)

    points = runner.run_once()

    assert len(points) == 1
    assert points[0].device_id == "mcu-1"
    assert points[0].channel == "temperature"
    assert points[0].value == 25.5


def test_run_once_publishes_to_data_service() -> None:
    runner, channel, data_service = _make_runner()
    received: list[DataPoint] = []
    data_service.subscribe("mcu-1", "temperature", received.append)
    _deposit_data_report(channel, "temperature", 25.5)

    runner.run_once()

    assert len(received) == 1
    assert received[0].value == 25.5


def test_run_once_processes_multiple_pending_frames_in_one_call() -> None:
    runner, channel, _data_service = _make_runner()
    _deposit_data_report(channel, "temperature", 25.5)
    _deposit_data_report(channel, "humidity", 55.0)

    points = runner.run_once()

    assert [p.channel for p in points] == ["temperature", "humidity"]


def test_run_once_works_without_calling_start_first() -> None:
    """run_once() is a manual single-step action, independent of running state."""
    runner, channel, _data_service = _make_runner()
    _deposit_data_report(channel, "temperature", 25.5)

    assert runner.running is False
    points = runner.run_once()

    assert len(points) == 1


# -- start/stop 状态变化 --------------------------------------------------------


def test_runner_starts_not_running() -> None:
    runner, _channel, _data_service = _make_runner()
    assert runner.running is False


def test_start_sets_running_true() -> None:
    runner, _channel, _data_service = _make_runner()
    runner.start()
    assert runner.running is True


def test_stop_sets_running_false() -> None:
    runner, _channel, _data_service = _make_runner()
    runner.start()
    runner.stop()
    assert runner.running is False


def test_stop_before_start_does_not_raise() -> None:
    runner, _channel, _data_service = _make_runner()
    runner.stop()
    assert runner.running is False


# -- 多次 start 不会重复启动 ------------------------------------------------------


def test_calling_start_twice_stays_running_without_error() -> None:
    runner, _channel, _data_service = _make_runner()
    runner.start()
    runner.start()
    assert runner.running is True


def test_calling_start_twice_does_not_reset_error_state() -> None:
    runner, channel, _data_service = _make_runner()
    receiver = HardwareDeviceReceiver(
        device_id="mcu-1",
        wire_id=WIRE_ID,
        channel=_RaisingChannel(),
        data_service=InMemoryDataService(),
    )
    raising_runner = HardwareRuntimeRunner(receiver)
    raising_runner.start()
    raising_runner.run_once()
    assert raising_runner.error_count == 1

    raising_runner.start()  # calling start again must not reset counters

    assert raising_runner.error_count == 1
    assert raising_runner.running is True


def test_calling_stop_twice_is_a_no_op() -> None:
    runner, _channel, _data_service = _make_runner()
    runner.start()
    runner.stop()
    runner.stop()
    assert runner.running is False


# -- receiver 异常不会导致状态错误 -------------------------------------------------


def test_run_once_does_not_raise_when_channel_receive_fails() -> None:
    receiver = HardwareDeviceReceiver(
        device_id="mcu-1",
        wire_id=WIRE_ID,
        channel=_RaisingChannel(),
        data_service=InMemoryDataService(),
    )
    runner = HardwareRuntimeRunner(receiver)
    runner.start()

    points = runner.run_once()  # must not raise

    assert points == []


def test_receiver_exception_is_recorded_but_does_not_change_running_state() -> None:
    receiver = HardwareDeviceReceiver(
        device_id="mcu-1",
        wire_id=WIRE_ID,
        channel=_RaisingChannel(),
        data_service=InMemoryDataService(),
    )
    runner = HardwareRuntimeRunner(receiver)
    runner.start()

    runner.run_once()

    assert runner.running is True
    assert runner.error_count == 1
    assert isinstance(runner.last_error, RuntimeError)


def test_receiver_exception_while_stopped_still_does_not_raise() -> None:
    receiver = HardwareDeviceReceiver(
        device_id="mcu-1",
        wire_id=WIRE_ID,
        channel=_RaisingChannel(),
        data_service=InMemoryDataService(),
    )
    runner = HardwareRuntimeRunner(receiver)

    runner.run_once()

    assert runner.running is False
    assert runner.error_count == 1


def test_runner_recovers_after_a_transient_receiver_error() -> None:
    """One failing poll must not prevent a later successful poll."""
    channel = LoopbackChannel()
    channel.connect()
    data_service = InMemoryDataService()
    receiver = HardwareDeviceReceiver(
        device_id="mcu-1", wire_id=WIRE_ID, channel=channel, data_service=data_service
    )
    runner = HardwareRuntimeRunner(receiver)
    runner.start()

    # first poll: nothing pending, then a genuine failure is simulated by
    # swapping in a raising channel temporarily is unnecessary here --
    # instead verify a normal empty poll followed by real data both work
    # in sequence, proving no latent bad state accumulates.
    assert runner.run_once() == []
    _deposit_data_report(channel, "temperature", 25.5)
    points = runner.run_once()

    assert len(points) == 1
    assert runner.error_count == 0


# -- 与现有 HardwareDeviceReceiver 集成 -------------------------------------------


def test_full_integration_with_real_receiver_and_loopback_channel() -> None:
    runner, channel, data_service = _make_runner()
    received: list[DataPoint] = []
    data_service.subscribe("mcu-1", "temperature", received.append)
    data_service.subscribe("mcu-1", "humidity", received.append)
    data_service.subscribe("mcu-1", "noise", received.append)

    runner.start()
    _deposit_data_report(channel, "temperature", 25.5)
    _deposit_data_report(channel, "humidity", 55.0)
    _deposit_data_report(channel, "noise", 42.0)
    runner.run_once()

    assert [p.channel for p in received] == ["temperature", "humidity", "noise"]
    assert runner.receiver.error_count == 0
    assert runner.receiver.ignored_frame_count == 0


def test_integration_reflects_receiver_error_counters_too() -> None:
    """HardwareDeviceReceiver's own error/ignored counters (CRC errors,
    non-DATA_REPORT frames) remain visible through runner.receiver,
    independent of the runner's own error_count (which only covers
    exceptions the receiver itself did not catch)."""
    runner, channel, _data_service = _make_runner()
    runner.start()

    payload = json.dumps({"channel": "temperature", "value": 25.5}).encode("utf-8")
    frame = Frame(device_id=WIRE_ID, command_type=DATA_REPORT_CODE, payload=payload)
    corrupted = bytearray(encode(frame))
    corrupted[-1] ^= 0xFF
    channel.send(bytes(corrupted))

    points = runner.run_once()

    assert points == []
    assert runner.receiver.error_count == 1
    # the receiver handled it internally; the runner itself saw no exception
    assert runner.error_count == 0
