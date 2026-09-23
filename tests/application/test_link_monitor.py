"""Tests for application.link_monitor, and for the receiver reporting to it.

The end-to-end test at the bottom is the one worth reading: a virtual
STM32 is told to split, merge, pad and corrupt frames with a fixed seed,
and the host's counters must match what was actually injected -- stray
bytes cost exactly one resync each, a flipped CRC bit exactly one checksum
error, and splitting or merging costs nothing at all. That is the
protocol's reliability argument as an executable claim.
"""

from __future__ import annotations

from application import link_monitor as link
from application.hardware_runtime import HardwareDeviceReceiver
from application.link_monitor import LinkEvent, LinkMonitor
from communication.pipe import make_pipe_pair
from scripts.virtual_stm32 import FaultPlan, VirtualStm32, build_frame
from service.data_service_impl import InMemoryDataService


def test_a_new_monitor_is_inactive_and_empty() -> None:
    stats = LinkMonitor().statistics()
    assert stats.active is False
    assert stats.frames == stats.resyncs == stats.checksum_errors == 0


def test_events_are_counted_by_kind_and_fanned_out() -> None:
    monitor = LinkMonitor()
    seen: list[LinkEvent] = []
    monitor.subscribe(seen.append)
    monitor.attach()
    monitor.event(link.FRAME, raw=b"\xaa\x55")
    monitor.event(link.RESYNC)
    monitor.event(link.CHECKSUM_ERROR, raw=b"\x00")
    monitor.record_bytes(12)

    stats = monitor.statistics()
    assert stats.active is True
    assert (stats.frames, stats.resyncs, stats.checksum_errors) == (1, 1, 1)
    assert stats.bytes_received == 12
    assert stats.last_frame_at is not None
    assert [e.kind for e in seen] == [link.FRAME, link.RESYNC, link.CHECKSUM_ERROR]


def test_a_failing_subscriber_does_not_stop_the_others() -> None:
    monitor = LinkMonitor()
    seen: list[str] = []

    def broken(_: LinkEvent) -> None:
        raise RuntimeError("viewer crashed")

    monitor.subscribe(broken)
    monitor.subscribe(lambda e: seen.append(e.kind))
    monitor.event(link.FRAME)
    assert seen == [link.FRAME]


def _receiver(monitor: LinkMonitor | None = None):
    host, device = make_pipe_pair()
    host.connect()
    device.connect()
    service = InMemoryDataService()
    receiver = HardwareDeviceReceiver("dev", 1, host, service, monitor=monitor)
    return receiver, device


def test_a_clean_frame_is_reported_with_its_decoded_fields() -> None:
    monitor = LinkMonitor()
    receiver, device = _receiver(monitor)
    seen: list[LinkEvent] = []
    monitor.subscribe(seen.append)
    frame = build_frame(1, "temperature", 24.5)
    device.send(frame)

    points = receiver.poll_until_empty()

    assert len(points) == 1
    (event,) = seen
    assert event.kind == link.FRAME
    assert event.raw == frame
    assert event.device_id == 1
    assert event.command_type == 0x01
    assert event.payload is not None and "temperature" in event.payload


def test_the_receiver_still_works_without_a_monitor() -> None:
    receiver, device = _receiver(None)
    device.send(build_frame(1, "temperature", 24.5))
    assert len(receiver.poll_until_empty()) == 1
    assert receiver.error_count == 0


def test_counters_match_exactly_what_the_virtual_device_injected() -> None:
    monitor = LinkMonitor()
    receiver, device_end = _receiver(monitor)
    virtual = VirtualStm32(
        device_end,
        device_id=1,
        faults=FaultPlan(split=0.3, merge=0.3, garbage=0.2, bitflip=0.1),
        seed=20260923,
        verbose=False,
    )
    cycles = 60
    points = []
    for _ in range(cycles):
        virtual.cycle()
        points.extend(receiver.poll_until_empty())

    injected = virtual.injected
    stats = monitor.statistics()
    # Every kind of fault actually happened, or the test proves nothing.
    assert all(count > 0 for count in injected.values()), injected
    # Stray bytes: one resync each. A flipped CRC: one checksum error each.
    assert stats.resyncs == injected["garbage"]
    assert stats.checksum_errors == injected["bitflip"]
    assert stats.decode_errors == 0
    # Splitting and merging cost nothing: every other frame arrived intact.
    assert stats.frames == 3 * cycles - injected["bitflip"]
    assert len(points) == stats.frames
    # The receiver's own counter agrees with the monitor's.
    assert receiver.error_count == stats.resyncs + stats.checksum_errors
