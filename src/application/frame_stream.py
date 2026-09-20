"""FrameStreamBuffer: recovers complete protocol frames from an arbitrary byte stream.

A real byte-stream transport (SerialChannel) has no message boundaries:
one receive() call can return several frames concatenated together, or a
frame split across two calls -- unlike communication.loopback.
LoopbackChannel, which happens to preserve one send() as one receive().
protocol/decoder.py's decode() deliberately does not handle this (see its
own docstring: locating a frame boundary within an arbitrary, possibly
partial byte stream is a Communication/Application Layer concern, not
part of that function) -- this module is that concern, factored out so
every caller in application/ that reads frames off a real byte stream
(hardware_runtime.HardwareDeviceReceiver's uplink loop,
manager.DeviceManager.deliver()'s Hardware-mode command round trip)
shares one correct implementation instead of duplicating it.

Does not modify protocol/decoder.py, protocol/encoder.py, or
communication/*: it only reads their existing public constants
(HEADER/LENGTH_SIZE/CRC_SIZE/BYTE_ORDER) to know where a frame ends.
"""

from __future__ import annotations

from collections.abc import Callable

from protocol.encoder import BYTE_ORDER, CRC_SIZE, HEADER, LENGTH_SIZE

# Fixed-size prefix every frame starts with (header + device id + command
# type + length), before the variable-length payload and trailing CRC --
# mirrors protocol/decoder.py's own _MIN_FRAME_SIZE/offset arithmetic.
_LENGTH_OFFSET = len(HEADER) + 1 + 1  # header + device_id(1B) + command_type(1B)
_FIXED_PREFIX_SIZE = _LENGTH_OFFSET + LENGTH_SIZE


class FrameStreamBuffer:
    """Accumulates raw bytes via :meth:`feed` and yields exactly one
    complete frame's worth at a time via :meth:`extract_frame`, buffering
    any incomplete remainder for the next call."""

    def __init__(self, on_discard: Callable[[], None] | None = None) -> None:
        """``on_discard`` (optional) is called once per resync event --
        i.e. whenever leading bytes had to be dropped because they could
        not be the start of a frame. Lets a caller that tracks an
        error/anomaly counter (e.g. HardwareDeviceReceiver.error_count)
        stay informed without this class needing to know that concept
        itself."""
        self._buffer = bytearray()
        self._on_discard = on_discard

    def feed(self, data: bytes) -> None:
        """Append newly received bytes to the buffer."""
        if data:
            self._buffer.extend(data)

    def extract_frame(self) -> bytes | None:
        """Slice exactly one complete frame off the front of the buffer,
        if one is fully present; otherwise leave the buffer untouched and
        return None to wait for more bytes."""
        self._resync()
        if len(self._buffer) < _FIXED_PREFIX_SIZE:
            return None

        declared_length = int.from_bytes(
            self._buffer[_LENGTH_OFFSET : _LENGTH_OFFSET + LENGTH_SIZE], BYTE_ORDER
        )
        total_size = _FIXED_PREFIX_SIZE + declared_length + CRC_SIZE
        if len(self._buffer) < total_size:
            return None

        frame_bytes = bytes(self._buffer[:total_size])
        del self._buffer[:total_size]
        return frame_bytes

    def _resync(self) -> None:
        """Drop any leading bytes that cannot be the start of a frame, so
        a stray or corrupted byte can't permanently wedge the buffer."""
        if not self._buffer:
            return
        index = self._buffer.find(HEADER)
        if index == 0:
            return
        if index == -1:
            # No full header anywhere buffered. Keep a possible partial
            # match at the tail (its first byte(s) could be the start of
            # a header whose remaining byte(s) haven't arrived yet).
            partial_tail_len = 0
            for size in range(min(len(HEADER) - 1, len(self._buffer)), 0, -1):
                if bytes(self._buffer[-size:]) == HEADER[:size]:
                    partial_tail_len = size
                    break
            # 只有真的丢掉了字节才算一次重同步。缓冲区里**恰好只剩半个帧头**
            # （等后半个字节到达）是字节流传输的正常状态，不是错误——此处原先
            # 无条件计数，且因为等待期间每次轮询都会重新走到这里，一次边界切分
            # 会被反复累加。2026-08-18 的噪声阶跃实验因此报出 13 次"帧同步错误"
            # 而实际 0 丢帧（58 个采集周期全部收齐 3 帧），若不修会把并不存在的
            # 通信错误写进论文。
            discarded = len(self._buffer) - partial_tail_len
            if partial_tail_len:
                del self._buffer[:discarded]
            else:
                self._buffer.clear()
            if discarded and self._on_discard is not None:
                self._on_discard()
            return
        del self._buffer[:index]
        if self._on_discard is not None:
            self._on_discard()
