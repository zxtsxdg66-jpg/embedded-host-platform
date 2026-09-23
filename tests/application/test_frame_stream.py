"""Tests for FrameStreamBuffer, in particular its resync accounting.

This module previously had no tests of its own -- it was only exercised
indirectly through HardwareDeviceReceiver, which checked *frames* but never
the ``on_discard`` callback. That gap let a real defect through: a buffer
holding nothing but half a frame header was counted as a sync error, and
counted again on every poll while the other half was in flight. The
2026-08-18 noise step-response run reported 13 "frame sync errors" while
losing exactly zero frames (all 58 cycles delivered all 3 channels), which
would have reported communication errors that never happened.
"""

from __future__ import annotations

from application.frame_stream import FrameStreamBuffer
from protocol.encoder import HEADER, encode
from protocol.frame import Frame


def _frame(channel: str = "noise", value: float = 45.3) -> bytes:
    payload = f'{{"channel":"{channel}","value":{value}}}'.encode()
    return encode(Frame(device_id=1, command_type=1, payload=payload))


class _Counter:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self) -> None:
        self.count += 1


def test_a_lone_partial_header_is_not_counted_as_a_sync_error() -> None:
    """The regression. A trailing 0xAA whose 0x55 has not arrived yet is a
    normal state of a byte stream, not an error: nothing was discarded."""
    counter = _Counter()
    buffer = FrameStreamBuffer(on_discard=counter)

    buffer.feed(_frame() + HEADER[:1])

    assert buffer.extract_frame() is not None
    assert buffer.extract_frame() is None  # 只剩半个帧头，等下半个
    assert counter.count == 0


def test_waiting_on_a_partial_header_does_not_accumulate_errors() -> None:
    """What turned one boundary into 13 errors: the caller polls ~20x/s, and
    every poll re-entered the same branch and incremented again."""
    counter = _Counter()
    buffer = FrameStreamBuffer(on_discard=counter)
    buffer.feed(_frame() + HEADER[:1])
    buffer.extract_frame()

    for _ in range(20):
        buffer.extract_frame()

    assert counter.count == 0


def test_a_split_header_still_yields_the_frame_once_completed() -> None:
    """Correctness must not be traded for the quieter counter: the frame
    whose header was split across two receive() calls still comes out."""
    counter = _Counter()
    buffer = FrameStreamBuffer(on_discard=counter)
    second = _frame("temperature", 22.1)
    buffer.feed(_frame() + second[:1])
    buffer.extract_frame()

    buffer.feed(second[1:])

    assert buffer.extract_frame() == second
    assert counter.count == 0


def test_real_stray_bytes_are_still_counted() -> None:
    """The counter must keep working for what it exists to detect."""
    counter = _Counter()
    buffer = FrameStreamBuffer(on_discard=counter)

    buffer.feed(b"\x01\x02\x03" + _frame())

    assert buffer.extract_frame() is not None
    assert counter.count == 1


def test_garbage_with_no_header_at_all_is_dropped_and_counted() -> None:
    counter = _Counter()
    buffer = FrameStreamBuffer(on_discard=counter)

    buffer.feed(b"\x01\x02\x03\x04")

    assert buffer.extract_frame() is None
    assert counter.count == 1


def test_garbage_ending_in_a_partial_header_counts_once_and_keeps_the_tail():
    """Mixed case: the junk before the partial header is a genuine discard,
    but the partial header itself must survive for the next frame."""
    counter = _Counter()
    buffer = FrameStreamBuffer(on_discard=counter)
    frame = _frame()
    buffer.feed(b"\xff\xfe" + frame[:1])
    buffer.extract_frame()

    assert counter.count == 1

    buffer.feed(frame[1:])
    assert buffer.extract_frame() == frame
    assert counter.count == 1  # 补齐过程不再产生新的计数


def test_several_concatenated_frames_come_out_one_by_one_without_errors():
    counter = _Counter()
    buffer = FrameStreamBuffer(on_discard=counter)
    frames = [_frame("temperature", 22.1), _frame("humidity", 71.2), _frame()]

    buffer.feed(b"".join(frames))

    assert [buffer.extract_frame() for _ in frames] == frames
    assert buffer.extract_frame() is None
    assert counter.count == 0
