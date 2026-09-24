"""Tests for application.fault_injection: faults injected into a real byte stream.

The injector sits between a channel and the real HardwareDeviceReceiver. What
these tests hold it to is the whole point of the feature: every fault it
injects must show up in the receiver's own counters **exactly** once, and no
corrupted frame may ever be accepted as a reading. A fake wire feeds known
bytes; everything downstream of the injector is the production code.
"""

from __future__ import annotations

import json
import random
from collections import deque

from application.fault_injection import FaultInjectingChannel, FaultPlan
from application.hardware_runtime import HardwareDeviceReceiver
from application.link_monitor import LinkMonitor
from communication.interface import CommunicationChannel
from protocol.encoder import encode
from protocol.frame import Frame
from service.data_service_impl import InMemoryDataService


class _Wire(CommunicationChannel):
    """A serial port stand-in: hands out pre-loaded chunks, one per receive()."""

    def __init__(self, chunks: list[bytes] | None = None) -> None:
        self.chunks: deque[bytes] = deque(chunks or [])
        self.sent: list[bytes] = []
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def send(self, data: bytes) -> None:
        self.sent.append(data)

    def receive(self) -> bytes:
        return self.chunks.popleft() if self.chunks else b""


def _data(value: float, device_id: int = 1) -> bytes:
    payload = json.dumps({"channel": "temperature", "value": value}).encode()
    return encode(Frame(device_id=device_id, command_type=0x01, payload=payload))


def _ack() -> bytes:
    payload = b'{"status":"success"}'
    return encode(Frame(device_id=1, command_type=0x02, payload=payload))


def _frames(count: int) -> list[bytes]:
    return [_data(20 + i / 100) for i in range(count)]


def _rig(chunks: list[bytes], plan: FaultPlan, seed: int = 7):
    wire = _Wire(chunks)
    injector = FaultInjectingChannel(wire, plan, seed=seed)
    injector.connect()
    monitor = LinkMonitor()
    monitor.subscribe(injector.audit)
    receiver = HardwareDeviceReceiver(
        "dev", 1, injector, InMemoryDataService(), monitor=monitor
    )
    return wire, injector, receiver, monitor


def _drain(receiver: HardwareDeviceReceiver, wire: _Wire, injector) -> list:
    """Poll like the runner does until the wire and the injector are both empty."""
    points = []
    for _ in range(len(wire.chunks) + 50):
        points.extend(receiver.poll_until_empty())
        if not wire.chunks and injector.idle:
            points.extend(receiver.poll_until_empty())
            break
    return points


def _random_chunks(stream: bytes, rng: random.Random) -> list[bytes]:
    chunks, i = [], 0
    while i < len(stream):
        step = rng.randint(1, 120)
        chunks.append(stream[i : i + step])
        i += step
    return chunks


# -- transparency ---------------------------------------------------------------


def test_with_no_faults_the_stream_passes_through_byte_for_byte() -> None:
    stream = b"".join(_frames(40))
    wire = _Wire(_random_chunks(stream, random.Random(1)))
    injector = FaultInjectingChannel(wire, FaultPlan(), seed=1)
    out = b"".join(injector.receive() for _ in range(len(wire.chunks) + 5))
    assert out == stream


def test_send_and_the_connection_are_forwarded_untouched() -> None:
    wire = _Wire()
    injector = FaultInjectingChannel(wire, FaultPlan(bitflip=1.0), seed=1)
    injector.connect()
    assert wire.is_connected and injector.is_connected
    injector.send(b"\xaa\x55command")
    assert wire.sent == [b"\xaa\x55command"]
    injector.disconnect()
    assert not wire.is_connected


# -- each fault on its own -------------------------------------------------------


def test_stray_bytes_cost_exactly_one_resync_each() -> None:
    wire, injector, receiver, monitor = _rig(_frames(30), FaultPlan(garbage=1.0))
    points = _drain(receiver, wire, injector)
    stats = monitor.statistics()
    assert injector.counts().garbage == 30
    assert stats.resyncs == 30
    assert stats.frames == len(points) == 30
    assert injector.report(stats).consistent is True


def test_a_flipped_crc_is_caught_and_never_becomes_a_reading() -> None:
    wire, injector, receiver, monitor = _rig(_frames(30), FaultPlan(bitflip=1.0))
    points = _drain(receiver, wire, injector)
    stats = monitor.statistics()
    assert injector.counts().bitflip == 30
    assert stats.checksum_errors == 30
    assert points == []
    report = injector.report(stats)
    assert report.bad_accepted == 0
    assert report.consistent is True


def test_splitting_and_merging_cost_nothing() -> None:
    wire, injector, receiver, monitor = _rig(
        _frames(30), FaultPlan(split=1.0, merge=0.5)
    )
    points = _drain(receiver, wire, injector)
    stats = monitor.statistics()
    counts = injector.counts()
    assert counts.split > 0 and counts.merge > 0
    assert len(points) == stats.frames == 30
    assert stats.resyncs == stats.checksum_errors == stats.decode_errors == 0
    assert injector.report(stats).consistent is True


def test_mixed_faults_reconcile_exactly() -> None:
    stream = b"".join(_frames(400))
    chunks = _random_chunks(stream, random.Random(20260924))
    plan = FaultPlan(split=0.3, merge=0.3, garbage=0.15, bitflip=0.08)
    wire, injector, receiver, monitor = _rig(chunks, plan, seed=20260924)
    points = _drain(receiver, wire, injector)

    counts = injector.counts()
    stats = monitor.statistics()
    # Every kind happened, or the test proves nothing.
    assert min(counts.split, counts.merge, counts.garbage, counts.bitflip) > 0, counts
    assert stats.resyncs == counts.garbage
    assert stats.checksum_errors == counts.bitflip
    assert stats.decode_errors == 0
    assert stats.frames == len(points) == counts.delivered_frames - counts.bitflip
    assert counts.delivered_frames == 400
    report = injector.report(stats)
    assert report.bad_accepted == 0
    assert report.consistent is True, report.lines


# -- what must not be touched -------------------------------------------------------


def test_command_acknowledgements_are_never_corrupted() -> None:
    stream = b"".join(_ack() for _ in range(20))
    wire = _Wire([stream])
    plan = FaultPlan(split=1.0, merge=1.0, garbage=1.0, bitflip=1.0, length=1.0)
    injector = FaultInjectingChannel(wire, plan, seed=3)
    # Splitting on every read hands over a little at a time; read until idle.
    parts = []
    for _ in range(500):
        parts.append(injector.receive())
        if not wire.chunks and injector.idle:
            break
    out = b"".join(parts)
    assert out == stream
    counts = injector.counts()
    assert counts.garbage == counts.bitflip == counts.length == 0


def test_the_device_manager_view_never_injects_and_keeps_the_order() -> None:
    first, second = _frames(10), _frames(10)
    wire = _Wire([b"".join(first), b"".join(second)])
    injector = FaultInjectingChannel(wire, FaultPlan(garbage=1.0, bitflip=1.0), seed=5)
    manager_view = injector.passthrough()

    # The device manager reads while waiting for an ack: it gets the frames
    # exactly as they came off the wire, and none of them counts as delivered.
    assert manager_view.receive() == b"".join(first)
    assert injector.counts().delivered_frames == 0

    monitor = LinkMonitor()
    monitor.subscribe(injector.audit)
    receiver = HardwareDeviceReceiver(
        "dev", 1, injector, InMemoryDataService(), monitor=monitor
    )
    _drain(receiver, wire, injector)
    stats = monitor.statistics()
    assert injector.counts().delivered_frames == 10
    assert stats.resyncs == 10 and stats.checksum_errors == 10
    assert injector.report(stats).consistent is True


def test_the_manager_view_forwards_sending_and_connection() -> None:
    wire = _Wire()
    view = FaultInjectingChannel(wire, FaultPlan(), seed=1).passthrough()
    view.connect()
    view.send(b"x")
    assert wire.is_connected and view.is_connected and wire.sent == [b"x"]


# -- errors that were already on the wire ---------------------------------------------


def test_errors_already_on_the_wire_are_attributed_to_the_wire() -> None:
    good = _data(21.0)
    corrupted = bytearray(_data(22.0))
    corrupted[-1] ^= 0x01
    # A read that starts mid-frame (as at start-up), a real CRC error, a good frame.
    chunks = [good[9:] + bytes(corrupted) + good]
    wire, injector, receiver, monitor = _rig(chunks, FaultPlan())
    points = _drain(receiver, wire, injector)
    stats = monitor.statistics()
    counts = injector.counts()
    assert counts.wire_runs == 1 and counts.wire_checksum_errors == 1
    assert stats.resyncs == 1 and stats.checksum_errors == 1
    assert len(points) == 1
    assert injector.report(stats).consistent is True


def test_an_absurd_length_on_the_wire_does_not_make_the_injector_wait() -> None:
    bogus = b"\xaa\x55\x01\x01\xff\xff"
    stream = bogus + b"".join(_frames(3))
    wire = _Wire([stream])
    injector = FaultInjectingChannel(wire, FaultPlan(), seed=1)
    out = b"".join(injector.receive() for _ in range(5))
    assert out == stream


# -- the known length-field defect ----------------------------------------------


def test_a_flipped_length_byte_stalls_briefly_and_no_bad_frame_is_accepted() -> None:
    stream = b"".join(_frames(150))
    chunks = _random_chunks(stream, random.Random(9))
    wire, injector, receiver, monitor = _rig(chunks, FaultPlan(length=0.1), seed=9)
    points = _drain(receiver, wire, injector)
    assert injector.counts().length > 0

    # Stop injecting; the link must come back on its own.
    injector.plan = FaultPlan()
    before = len(points)
    wire.chunks.extend(_frames(20))
    points.extend(_drain(receiver, wire, injector))
    assert len(points) - before >= 15

    report = injector.report(monitor.statistics())
    assert report.bad_accepted == 0
    # Where a corrupted length lands is not predictable frame by frame, so the
    # exact per-kind reconciliation is switched off rather than faked.
    assert report.consistent is None


def test_only_the_low_length_byte_is_flipped() -> None:
    frames = _frames(50)
    wire = _Wire([b"".join(frames)])
    injector = FaultInjectingChannel(wire, FaultPlan(length=1.0), seed=2)
    out = b"".join(injector.receive() for _ in range(5))
    assert injector.counts().length == 50
    # The high length byte is untouched: a stall stays within ~255 bytes.
    start = 0
    for frame in frames:
        assert out[start + 4] == frame[4]
        assert out[start + 5] != frame[5]
        start += len(frame)
