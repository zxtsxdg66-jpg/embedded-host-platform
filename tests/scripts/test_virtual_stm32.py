"""Tests for scripts/virtual_stm32.py.

Verifies exactly what the task requires: a frame built by
virtual_stm32.build_frame() can be parsed by the real, unmodified
protocol.decoder.decode() and by the real, unmodified
application.hardware_runtime.HardwareDeviceReceiver -- i.e. this script's
output is genuinely compatible with Hardware Mode's real receive chain,
not just self-consistent with itself.

Uses communication.loopback.LoopbackChannel to carry the bytes between
"virtual_stm32" and "the receiver" within one test process -- the byte
format produced is identical to what would go out over a real
SerialChannel (virtual_stm32.py's own module docstring explains why a
real port is used when actually pairing with a running GUI; a test
process only needs to prove the *bytes* are correct).
"""

from __future__ import annotations

import json

import pytest

from application.hardware_runtime import HardwareDeviceReceiver
from communication.loopback import LoopbackChannel
from device.sensors.channels import HUMIDITY_CHANNEL, NOISE_CHANNEL, TEMPERATURE_CHANNEL
from protocol.decoder import decode
from protocol.exceptions import ChecksumError
from scripts.virtual_stm32 import DATA_REPORT_CODE, build_frame
from service.data_models import DataPoint
from service.data_service_impl import InMemoryDataService

# -- build_frame() produces a valid, decodable protocol frame -----------------


def test_build_frame_uses_the_documented_header() -> None:
    encoded = build_frame(device_id=1, channel_id="temperature", value=25.5)
    assert encoded.startswith(b"\xaa\x55")


def test_build_frame_is_decodable_by_the_real_protocol_decoder() -> None:
    encoded = build_frame(device_id=1, channel_id="temperature", value=25.5)

    frame = decode(encoded)

    assert frame.device_id == 1
    assert frame.command_type == DATA_REPORT_CODE
    body = json.loads(frame.payload.decode("utf-8"))
    assert body == {"channel": "temperature", "value": 25.5}


def test_build_frame_rejects_a_bit_flip_via_crc() -> None:
    """The generated frame must carry a real, verifiable CRC -- not just
    look right structurally."""
    encoded = bytearray(build_frame(device_id=1, channel_id="temperature", value=25.5))
    encoded[-1] ^= 0xFF

    with pytest.raises(ChecksumError):
        decode(bytes(encoded))


@pytest.mark.parametrize("device_id", [0, 1, 255])
def test_build_frame_supports_the_full_device_id_range(device_id: int) -> None:
    encoded = build_frame(device_id=device_id, channel_id="noise", value=42.0)
    assert decode(encoded).device_id == device_id


# -- HardwareDeviceReceiver can parse frames virtual_stm32 produces -----------


def _make_receiver() -> (
    tuple[HardwareDeviceReceiver, LoopbackChannel, InMemoryDataService]
):
    channel = LoopbackChannel()
    channel.connect()
    data_service = InMemoryDataService()
    receiver = HardwareDeviceReceiver(
        device_id="mcu-1", wire_id=1, channel=channel, data_service=data_service
    )
    return receiver, channel, data_service


def test_hardware_device_receiver_parses_a_virtual_stm32_temperature_frame() -> None:
    receiver, channel, _data_service = _make_receiver()
    channel.send(build_frame(device_id=1, channel_id="temperature", value=25.5))

    point = receiver.poll_once()

    assert point is not None
    assert point.device_id == "mcu-1"
    assert point.channel == "temperature"
    assert point.value == 25.5


def test_hardware_device_receiver_parses_all_three_channels_in_order() -> None:
    receiver, channel, data_service = _make_receiver()
    received: list[DataPoint] = []
    data_service.subscribe("mcu-1", TEMPERATURE_CHANNEL, received.append)
    data_service.subscribe("mcu-1", HUMIDITY_CHANNEL, received.append)
    data_service.subscribe("mcu-1", NOISE_CHANNEL, received.append)

    channel.send(build_frame(device_id=1, channel_id=TEMPERATURE_CHANNEL, value=25.5))
    channel.send(build_frame(device_id=1, channel_id=HUMIDITY_CHANNEL, value=55.0))
    channel.send(build_frame(device_id=1, channel_id=NOISE_CHANNEL, value=48.0))

    points = receiver.poll_until_empty()

    assert [p.channel for p in points] == [
        TEMPERATURE_CHANNEL,
        HUMIDITY_CHANNEL,
        NOISE_CHANNEL,
    ]
    assert [p.value for p in points] == [25.5, 55.0, 48.0]
    assert len(received) == 3


def test_frame_addressed_to_a_different_device_id_is_ignored() -> None:
    receiver, channel, _data_service = _make_receiver()
    channel.send(build_frame(device_id=2, channel_id="temperature", value=25.5))

    point = receiver.poll_once()

    assert point is None
    assert receiver.ignored_frame_count == 1


def test_full_loop_via_hardware_runtime_runner() -> None:
    """End-to-end: virtual_stm32 frames -> HardwareDeviceReceiver ->
    HardwareRuntimeRunner.run_once() -> DataService, exactly the shape a
    real GUI session would drive via QTimer."""
    from application.hardware_runner import HardwareRuntimeRunner

    receiver, channel, data_service = _make_receiver()
    runner = HardwareRuntimeRunner(receiver)
    received: list[DataPoint] = []
    data_service.subscribe("mcu-1", "noise", received.append)

    channel.send(build_frame(device_id=1, channel_id="noise", value=52.5))
    runner.start()
    points = runner.run_once()

    assert len(points) == 1
    assert points[0].value == 52.5
    assert received == points
