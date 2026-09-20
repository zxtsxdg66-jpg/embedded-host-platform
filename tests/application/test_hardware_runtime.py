"""Tests for application.hardware_runtime.HardwareDeviceReceiver.

Uses communication.loopback.LoopbackChannel as the test double for "MCU
already deposited bytes on the wire": since HardwareDeviceReceiver only
depends on the abstract CommunicationChannel interface, LoopbackChannel
exercises exactly the same code path a real SerialChannel would -- it is
a genuine CommunicationChannel implementation, not an interaction mock,
so this is a faithful "mock SerialChannel" substitute for most cases. One
test additionally builds a real SerialChannel backed by a mocked pyserial
Serial object (same technique as tests/communication/test_serial.py) to
prove the receiver also works against the concrete SerialChannel type.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from application.hardware_runtime import DATA_REPORT_CODE, HardwareDeviceReceiver
from communication.loopback import LoopbackChannel
from communication.serial import SerialChannel
from protocol.encoder import encode
from protocol.frame import Frame
from service.data_models import DataPoint
from service.data_service_impl import InMemoryDataService

WIRE_ID = 1
COMMAND_ACK_CODE = 0x02  # must match application.manager.COMMAND_ACK_CODE


def _make_receiver() -> tuple[
    HardwareDeviceReceiver, LoopbackChannel, InMemoryDataService
]:
    channel = LoopbackChannel()
    channel.connect()
    data_service = InMemoryDataService()
    receiver = HardwareDeviceReceiver(
        device_id="mcu-1", wire_id=WIRE_ID, channel=channel, data_service=data_service
    )
    return receiver, channel, data_service


def _deposit_data_report(
    channel: LoopbackChannel, channel_id: str, value: object, wire_id: int = WIRE_ID
) -> None:
    payload = json.dumps({"channel": channel_id, "value": value}).encode("utf-8")
    frame = Frame(device_id=wire_id, command_type=DATA_REPORT_CODE, payload=payload)
    channel.send(encode(frame))


# -- 正常数据 -----------------------------------------------------------------


def test_poll_once_returns_none_when_nothing_pending() -> None:
    receiver, _channel, _data_service = _make_receiver()
    assert receiver.poll_once() is None


def test_poll_once_processes_a_single_temperature_report() -> None:
    receiver, channel, _data_service = _make_receiver()
    _deposit_data_report(channel, "temperature", 25.5)

    point = receiver.poll_once()

    assert point is not None
    assert point.device_id == "mcu-1"
    assert point.channel == "temperature"
    assert point.value == 25.5


def test_data_service_receives_the_published_point() -> None:
    receiver, channel, data_service = _make_receiver()
    received: list[DataPoint] = []
    data_service.subscribe("mcu-1", "temperature", received.append)
    _deposit_data_report(channel, "temperature", 25.5)

    receiver.poll_once()

    assert len(received) == 1
    assert received[0].device_id == "mcu-1"
    assert received[0].channel == "temperature"
    assert received[0].value == 25.5


def test_error_and_ignored_counters_start_at_zero() -> None:
    receiver, _channel, _data_service = _make_receiver()
    assert receiver.error_count == 0
    assert receiver.ignored_frame_count == 0


# -- 多通道数据 -----------------------------------------------------------------


def test_poll_until_empty_processes_multiple_channels_in_order() -> None:
    receiver, channel, data_service = _make_receiver()
    received: list[DataPoint] = []
    data_service.subscribe("mcu-1", "temperature", received.append)
    data_service.subscribe("mcu-1", "humidity", received.append)
    data_service.subscribe("mcu-1", "noise", received.append)

    _deposit_data_report(channel, "temperature", 25.5)
    _deposit_data_report(channel, "humidity", 55.0)
    _deposit_data_report(channel, "noise", 42.0)

    points = receiver.poll_until_empty()

    assert [p.channel for p in points] == ["temperature", "humidity", "noise"]
    assert [p.value for p in points] == [25.5, 55.0, 42.0]
    assert len(received) == 3


def test_poll_until_empty_returns_empty_list_when_nothing_pending() -> None:
    receiver, _channel, _data_service = _make_receiver()
    assert receiver.poll_until_empty() == []


# -- CRC 错误 -------------------------------------------------------------------


def test_corrupted_crc_is_counted_as_error_and_not_published() -> None:
    receiver, channel, data_service = _make_receiver()
    received: list[DataPoint] = []
    data_service.subscribe("mcu-1", "temperature", received.append)

    payload = json.dumps({"channel": "temperature", "value": 25.5}).encode("utf-8")
    frame = Frame(device_id=WIRE_ID, command_type=DATA_REPORT_CODE, payload=payload)
    encoded = bytearray(encode(frame))
    encoded[-1] ^= 0xFF  # corrupt the CRC's last byte
    channel.send(bytes(encoded))

    point = receiver.poll_once()

    assert point is None
    assert receiver.error_count == 1
    assert received == []


def test_poll_until_empty_continues_after_a_corrupted_frame() -> None:
    receiver, channel, _data_service = _make_receiver()

    payload = json.dumps({"channel": "temperature", "value": 25.5}).encode("utf-8")
    bad_frame = Frame(device_id=WIRE_ID, command_type=DATA_REPORT_CODE, payload=payload)
    bad_encoded = bytearray(encode(bad_frame))
    bad_encoded[-1] ^= 0xFF
    channel.send(bytes(bad_encoded))
    _deposit_data_report(channel, "humidity", 55.0)

    points = receiver.poll_until_empty()

    assert receiver.error_count == 1
    assert [p.channel for p in points] == ["humidity"]


# -- 非 DATA_REPORT 帧 ------------------------------------------------------------


def test_non_data_report_frame_is_ignored_not_published() -> None:
    receiver, channel, data_service = _make_receiver()
    received: list[DataPoint] = []
    data_service.subscribe("mcu-1", "temperature", received.append)

    ack_frame = Frame(
        device_id=WIRE_ID,
        command_type=COMMAND_ACK_CODE,
        payload=json.dumps({"status": "success"}).encode("utf-8"),
    )
    channel.send(encode(ack_frame))

    point = receiver.poll_once()

    assert point is None
    assert receiver.ignored_frame_count == 1
    assert received == []


def test_frame_for_a_different_wire_id_is_ignored() -> None:
    receiver, channel, _data_service = _make_receiver()
    _deposit_data_report(channel, "temperature", 25.5, wire_id=WIRE_ID + 1)

    point = receiver.poll_once()

    assert point is None
    assert receiver.ignored_frame_count == 1


def test_malformed_payload_is_counted_as_error() -> None:
    receiver, channel, _data_service = _make_receiver()
    frame = Frame(device_id=WIRE_ID, command_type=DATA_REPORT_CODE, payload=b"not json")
    channel.send(encode(frame))

    point = receiver.poll_once()

    assert point is None
    assert receiver.error_count == 1


# -- 与真实 SerialChannel（mock pyserial）结合验证 --------------------------------


class _FakeSerialPort:
    """Minimal virtual stand-in for serial.Serial (mirrors
    tests/communication/test_serial.py's own fake). Reading and writing
    share one buffer, so writes made through SerialChannel.send() are
    immediately visible to SerialChannel.receive() -- modeling "the MCU
    wrote to the wire" for test purposes."""

    def __init__(self) -> None:
        self.is_open = True
        self.buffer = bytearray()

    def write(self, data: bytes) -> int:
        self.buffer.extend(data)
        return len(data)

    @property
    def in_waiting(self) -> int:
        return len(self.buffer)

    def read(self, size: int) -> bytes:
        chunk = bytes(self.buffer[:size])
        del self.buffer[:size]
        return chunk

    def close(self) -> None:
        self.is_open = False


def test_works_with_a_real_serial_channel_backed_by_mocked_pyserial() -> None:
    fake_port = _FakeSerialPort()
    with patch(
        "communication.serial.list_ports.comports",
        return_value=[SimpleNamespace(device="COM3")],
    ):
        with patch("communication.serial.serial.Serial", return_value=fake_port):
            channel = SerialChannel(port="COM3")
            channel.connect()

    data_service = InMemoryDataService()
    receiver = HardwareDeviceReceiver(
        device_id="mcu-1", wire_id=WIRE_ID, channel=channel, data_service=data_service
    )

    payload = json.dumps({"channel": "temperature", "value": 25.5}).encode("utf-8")
    frame = Frame(device_id=WIRE_ID, command_type=DATA_REPORT_CODE, payload=payload)
    channel.send(encode(frame))  # simulates the MCU writing to the wire

    point = receiver.poll_once()

    assert point is not None
    assert point.value == 25.5


# -- 字节流拼帧/断帧（真实 SerialChannel 特有，LoopbackChannel 不会暴露）-----------
#
# LoopbackChannel preserves one send() as one receive() (see its own
# docstring), which is why none of the tests above ever needed to worry
# about frame boundaries. A real byte-stream transport has no such
# guarantee: virtual_stm32.py sends several DATA_REPORT frames back to
# back with no delay between them (scripts/virtual_stm32.py's run()), so
# by the time a poll cycle fires, SerialChannel.receive() can easily
# return several frames concatenated into one chunk -- or, just as
# possible, a frame split across two receive() calls. _StreamChannel
# below is a minimal CommunicationChannel stand-in that hands back raw
# bytes exactly as queued (unlike LoopbackChannel), so it can model both.


class _StreamChannel:
    """CommunicationChannel stand-in that returns raw byte chunks exactly
    as queued via ``push``, with no per-``send()`` message boundaries --
    modeling what a real byte-stream transport (SerialChannel) does."""

    def __init__(self) -> None:
        self._connected = True
        self._chunks: list[bytes] = []

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def send(self, data: bytes) -> None:
        raise NotImplementedError("not used by these tests")

    def push(self, data: bytes) -> None:
        """Queue a raw chunk to be returned by the next receive() call."""
        self._chunks.append(data)

    def receive(self) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


def _encode_data_report(
    channel_id: str, value: object, wire_id: int = WIRE_ID
) -> bytes:
    payload = json.dumps({"channel": channel_id, "value": value}).encode("utf-8")
    frame = Frame(device_id=wire_id, command_type=DATA_REPORT_CODE, payload=payload)
    return encode(frame)


def test_poll_until_empty_splits_several_frames_from_one_concatenated_chunk() -> None:
    channel = _StreamChannel()
    data_service = InMemoryDataService()
    receiver = HardwareDeviceReceiver(
        device_id="mcu-1", wire_id=WIRE_ID, channel=channel, data_service=data_service
    )
    concatenated = (
        _encode_data_report("temperature", 25.5)
        + _encode_data_report("humidity", 55.0)
        + _encode_data_report("noise", 42.0)
    )
    channel.push(concatenated)  # one receive() burst containing three frames

    points = receiver.poll_until_empty()

    assert [p.channel for p in points] == ["temperature", "humidity", "noise"]
    assert [p.value for p in points] == [25.5, 55.0, 42.0]


def test_poll_once_buffers_a_frame_split_across_two_receive_calls() -> None:
    channel = _StreamChannel()
    data_service = InMemoryDataService()
    receiver = HardwareDeviceReceiver(
        device_id="mcu-1", wire_id=WIRE_ID, channel=channel, data_service=data_service
    )
    whole = _encode_data_report("temperature", 25.5)
    split_at = len(whole) // 2
    channel.push(whole[:split_at])
    channel.push(whole[split_at:])

    first = receiver.poll_once()
    assert first is None  # only half a frame has arrived so far

    second = receiver.poll_once()
    assert second is not None
    assert second.channel == "temperature"
    assert second.value == 25.5


def test_stray_bytes_before_a_frame_are_discarded_and_counted_as_error() -> None:
    channel = _StreamChannel()
    data_service = InMemoryDataService()
    receiver = HardwareDeviceReceiver(
        device_id="mcu-1", wire_id=WIRE_ID, channel=channel, data_service=data_service
    )
    channel.push(b"\x00\x00garbage" + _encode_data_report("temperature", 25.5))

    point = receiver.poll_once()

    assert point is not None
    assert point.value == 25.5
    assert receiver.error_count == 1
