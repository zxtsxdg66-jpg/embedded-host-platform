"""Inject known faults into a real byte stream and account for every one.

Added 2026-09-24 so that link reliability can be checked on the real board,
not only against the in-process virtual device. A real serial link almost
never corrupts a frame (two one-hour runs: zero CRC errors), so waiting for
errors proves nothing; faults have to be made on purpose, in known numbers,
so that the receiver's counters can be checked against them exactly.

``FaultInjectingChannel`` wraps the channel the receiver reads from --
normally the real ``SerialChannel`` -- and damages the byte stream at frame
boundaries before the receiver sees it:

======== ===================================== =================================
fault    what it does                          what the receiver must do
======== ===================================== =================================
split    one frame handed over in two reads    reassemble it silently
merge    one read's frames held for the next   split them apart silently
garbage  1-6 stray bytes before a frame        one resync
bitflip  one bit of a frame's CRC flipped      one checksum error, frame dropped
length   one bit of the low length byte        (the known length-field defect)
======== ===================================== =================================

**The receiver, the frame sync and the protocol code are not touched** -- they
are what is being tested. The injector finds frame boundaries with its own
small scanner rather than reusing ``FrameStreamBuffer``, for the same reason
the virtual device writes its own: the checker must not share code with the
thing it checks.

Only data-report frames are damaged. Command acknowledgements pass through
as they are, or a fan command would time out and muddy the picture.

**Two readers share one serial port.** The device manager reads the same
port while it waits for a command acknowledgement. It gets its own view,
``passthrough()``, that shares the injector's buffer (so no byte is lost or
reordered) but never injects anything; only frames handed to the receiver
count as delivered. That is what keeps the reconciliation exact.

Errors that were already on the wire -- a read that starts in the middle of
a frame, a genuinely corrupted frame -- are recognised and attributed to the
wire, not to the injector, and are left exactly as they came.

Like every concrete channel, create it only in ``application`` or
``scripts``.
"""

from __future__ import annotations

import random
import threading
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime

from application.manager import DATA_REPORT_CODE
from communication.interface import CommunicationChannel
from core.link_events import FRAME, LinkEvent, LinkStatistics
from protocol.decoder import decode
from protocol.encoder import (
    BYTE_ORDER,
    COMMAND_TYPE_SIZE,
    CRC_SIZE,
    DEVICE_ID_SIZE,
    HEADER,
    LENGTH_SIZE,
)
from protocol.exceptions import ChecksumError, ProtocolError

_LENGTH_OFFSET = len(HEADER) + DEVICE_ID_SIZE + COMMAND_TYPE_SIZE
_PREFIX_SIZE = _LENGTH_OFFSET + LENGTH_SIZE
_COMMAND_OFFSET = len(HEADER) + DEVICE_ID_SIZE

MAX_FRAME_SIZE = 1024
"""Frames longer than this are treated as a false header and passed through.

This project's frames are under a hundred bytes. Without the cap, a corrupted
length arriving from the wire would make the injector itself wait for up to
64 KB -- the very defect the receiver has, which is the receiver's to show.
"""

_KEEP_ORIGINALS = 20000
"""How many intact frames to remember for the acceptance audit (~1 MB)."""


@dataclass(frozen=True)
class FaultPlan:
    """How often each fault is injected, as probabilities per frame (or read)."""

    split: float = 0.0
    merge: float = 0.0
    garbage: float = 0.0
    bitflip: float = 0.0
    length: float = 0.0


DEFAULT_FAULTS = FaultPlan(split=0.25, merge=0.3, garbage=0.1, bitflip=0.03)
"""The same rates as the virtual device's ``--inject-faults``."""

LENGTH_FAULT_RATE = 0.01
"""With ``--fault-length``: about one frame in a hundred, i.e. every ~100 s."""


@dataclass(frozen=True)
class FaultCounts:
    """What the injector did, and what it found already wrong on the wire."""

    delivered_frames: int = 0
    split: int = 0
    merge: int = 0
    garbage: int = 0
    bitflip: int = 0
    length: int = 0
    wire_runs: int = 0
    wire_checksum_errors: int = 0
    wire_decode_errors: int = 0


@dataclass(frozen=True)
class FaultReport:
    """Injected faults set against what the receiver actually reported.

    ``consistent`` is True when every count matches exactly and no corrupted
    frame was accepted, False when anything is off, and None when length
    faults were injected: where a corrupted length lands depends on the bytes
    that follow, so exact per-kind accounting is switched off rather than
    faked. The acceptance audit still applies.
    """

    consistent: bool | None
    bad_accepted: int
    longest_gap_seconds: float | None
    lines: tuple[str, ...]


@dataclass
class _Piece:
    data: bytes
    events: dict[str, int] = field(default_factory=dict)


class _SharedStream:
    """The bytes read from the wire, cut at frame boundaries, shared by both views."""

    def __init__(self, inner: CommunicationChannel) -> None:
        self.inner = inner
        self.lock = threading.RLock()
        self.buffer = bytearray()

    def pull(self) -> list[tuple[str, bytes]]:
        """Read once from the wire; return every complete segment, in order.

        A segment is ``("run", bytes)`` for bytes that are not a frame, or
        ``(kind, frame)`` with kind ``data``, ``other``, ``bad_checksum`` or
        ``bad_decode``. An incomplete frame stays buffered.
        """
        data = self.inner.receive()
        if data:
            self.buffer.extend(data)
        segments: list[tuple[str, bytes]] = []
        run = bytearray()
        buf = self.buffer
        while buf:
            index = buf.find(HEADER)
            if index == -1:
                # Keep a lone first header byte: its partner may be in the next read.
                keep = 1 if buf[-1] == HEADER[0] else 0
                run += buf[: len(buf) - keep]
                del buf[: len(buf) - keep]
                break
            if index > 0:
                run += buf[:index]
                del buf[:index]
                continue
            if len(buf) < _PREFIX_SIZE:
                break
            length = int.from_bytes(
                buf[_LENGTH_OFFSET:_PREFIX_SIZE], BYTE_ORDER
            )
            total = _PREFIX_SIZE + length + CRC_SIZE
            if total > MAX_FRAME_SIZE:
                run += buf[:1]
                del buf[:1]
                continue
            if len(buf) < total:
                break
            frame = bytes(buf[:total])
            del buf[:total]
            if run:
                segments.append(("run", bytes(run)))
                run.clear()
            segments.append((_classify(frame), frame))
        if run:
            segments.append(("run", bytes(run)))
        return segments


def _classify(frame: bytes) -> str:
    try:
        decode(frame)
    except ChecksumError:
        return "bad_checksum"
    except ProtocolError:
        return "bad_decode"
    return "data" if frame[_COMMAND_OFFSET] == DATA_REPORT_CODE else "other"


class FaultInjectingChannel(CommunicationChannel):
    """The receiver's view of the wire, with faults. See the module docstring."""

    def __init__(
        self,
        inner: CommunicationChannel,
        plan: FaultPlan,
        seed: int | None = None,
    ) -> None:
        self.plan = plan
        self._stream = _SharedStream(inner)
        self._rng = random.Random(seed)
        self._carry: list[_Piece] = []
        self._carry_from_merge = False
        self._counts: Counter[str] = Counter()
        self._originals: set[bytes] = set()
        self._original_order: deque[bytes] = deque()
        self._bad_accepted = 0
        self._last_frame_at: datetime | None = None
        self._longest_gap: float | None = None

    # -- CommunicationChannel: everything but receive() is forwarded ---------

    @property
    def is_connected(self) -> bool:
        return self._stream.inner.is_connected

    def connect(self) -> None:
        self._stream.inner.connect()

    def disconnect(self) -> None:
        self._stream.inner.disconnect()

    def send(self, data: bytes) -> None:
        self._stream.inner.send(data)

    def receive(self) -> bytes:
        with self._stream.lock:
            segments = self._stream.pull()
            wire_trouble = any(kind == "run" for kind, _ in segments)
            pieces = self._carry
            from_merge = self._carry_from_merge
            self._carry, self._carry_from_merge = [], False
            for kind, data in segments:
                pieces.extend(self._inject(kind, data, allowed=not wire_trouble))
            if not pieces:
                return b""
            # Stray bytes already on the wire are left exactly where they were:
            # moving them around would change how many resyncs they cost.
            if not wire_trouble:
                if not from_merge and self._chance(self.plan.merge):
                    self._carry, self._carry_from_merge = pieces, True
                    self._counts["merge"] += 1
                    return b""
                if self._chance(self.plan.split):
                    pieces = self._split(pieces)
            return self._emit(pieces)

    # -- the second view --------------------------------------------------------

    def passthrough(self) -> CommunicationChannel:
        """The same wire for the device manager: shared buffer, no faults."""
        return _PassthroughView(self._stream)

    @property
    def idle(self) -> bool:
        """Nothing held back: no carried pieces and no partial frame buffered."""
        with self._stream.lock:
            return not self._carry and not self._stream.buffer

    # -- accounting ---------------------------------------------------------------

    def audit(self, event: LinkEvent) -> None:
        """Subscribe to the link monitor: every accepted frame must be an intact one."""
        if event.kind != FRAME:
            return
        with self._stream.lock:
            if event.raw not in self._originals:
                self._bad_accepted += 1
            if self._last_frame_at is not None:
                gap = (event.timestamp - self._last_frame_at).total_seconds()
                if self._longest_gap is None or gap > self._longest_gap:
                    self._longest_gap = gap
            self._last_frame_at = event.timestamp

    def counts(self) -> FaultCounts:
        with self._stream.lock:
            return FaultCounts(**dict(self._counts))

    def report(self, stats: LinkStatistics) -> FaultReport:
        """Set what was injected against what the receiver reported."""
        with self._stream.lock:
            c = self.counts()
            bad = self._bad_accepted
            gap = self._longest_gap
        expected = {
            "重同步": (stats.resyncs, c.garbage + c.wire_runs),
            "CRC 失败": (stats.checksum_errors, c.bitflip + c.wire_checksum_errors),
            "格式错误": (stats.decode_errors, c.wire_decode_errors),
            "正常帧": (stats.frames, c.delivered_frames - c.bitflip - c.length),
        }
        lines = [
            f"注入：拆帧 {c.split}、并帧 {c.merge}、杂散字节 {c.garbage}、"
            f"CRC 翻转 {c.bitflip}、长度翻转 {c.length}"
            f"（交给接收器的数据帧 {c.delivered_frames}）",
            f"线路自带：非帧字节 {c.wire_runs} 段、CRC 错 {c.wire_checksum_errors}、"
            f"格式错 {c.wire_decode_errors}",
            f"被当作读数接受的错帧：{bad}",
        ]
        if gap is not None:
            lines.append(f"相邻两帧之间的最长间隔：{gap:.1f} s")
        if bad:
            consistent: bool | None = False
        elif c.length:
            consistent = None
            lost = expected["正常帧"][1] - stats.frames
            lines.append(
                f"有长度翻转，逐项核对关闭：{c.length} 次翻转另外吞掉了 {lost} 帧"
            )
        else:
            consistent = all(got == want for got, want in expected.values())
        if not c.length:
            for name, (got, want) in expected.items():
                mark = "一致" if got == want else "不一致"
                lines.append(f"{name}：判出 {got}，应为 {want}（{mark}）")
        return FaultReport(consistent, bad, gap, tuple(lines))

    # -- internals ------------------------------------------------------------------

    def _chance(self, rate: float) -> bool:
        return rate > 0 and self._rng.random() < rate

    def _inject(self, kind: str, data: bytes, allowed: bool) -> list[_Piece]:
        if kind == "run":
            return [_Piece(data, {"wire_runs": 1})]
        if kind == "bad_checksum":
            return [_Piece(data, {"wire_checksum_errors": 1})]
        if kind == "bad_decode":
            return [_Piece(data, {"wire_decode_errors": 1})]
        if kind == "other":
            return [_Piece(data)]
        frame = bytearray(data)
        events = {"delivered_frames": 1}
        if allowed and self._chance(self.plan.bitflip):
            frame[-1 - self._rng.randrange(CRC_SIZE)] ^= 1 << self._rng.randrange(8)
            events["bitflip"] = 1
        elif allowed and self._chance(self.plan.length):
            # Low byte only: the stall stays within ~255 bytes (a few seconds).
            # A flip in the high byte can stall the link for minutes; see
            # docs "known defect: corrupted length field".
            frame[_PREFIX_SIZE - 1] ^= 1 << self._rng.randrange(8)
            events["length"] = 1
        else:
            self._remember(bytes(frame))
        pieces = []
        if allowed and self._chance(self.plan.garbage):
            pieces.append(_Piece(self._garbage(), {"garbage": 1}))
        pieces.append(_Piece(bytes(frame), events))
        return pieces

    def _garbage(self) -> bytes:
        # Never the first header byte: a stray 0xAA could start a false frame
        # and cost more than the one resync each injection is accounted as.
        pool = [b for b in range(256) if b != HEADER[0]]
        return bytes(self._rng.choice(pool) for _ in range(self._rng.randint(1, 6)))

    def _split(self, pieces: list[_Piece]) -> list[_Piece]:
        """Cut one frame in two; the tail and everything after it wait for next read."""
        candidates = [
            i
            for i, p in enumerate(pieces)
            if "garbage" not in p.events and len(p.data) > 1
        ]
        if not candidates:
            return pieces
        index = self._rng.choice(candidates)
        piece = pieces[index]
        cut = self._rng.randrange(1, len(piece.data))
        # The frame's events are counted when its last byte is handed over.
        head, tail = _Piece(piece.data[:cut]), _Piece(piece.data[cut:], piece.events)
        self._carry = [tail, *pieces[index + 1 :]]
        self._counts["split"] += 1
        return [*pieces[:index], head]

    def _emit(self, pieces: list[_Piece]) -> bytes:
        for piece in pieces:
            self._counts.update(piece.events)
        return b"".join(piece.data for piece in pieces)

    def _remember(self, frame: bytes) -> None:
        self._originals.add(frame)
        self._original_order.append(frame)
        if len(self._original_order) > _KEEP_ORIGINALS:
            self._originals.discard(self._original_order.popleft())


class _PassthroughView(CommunicationChannel):
    """The device manager's reads: same buffer, no faults, nothing counted."""

    def __init__(self, stream: _SharedStream) -> None:
        self._stream = stream

    @property
    def is_connected(self) -> bool:
        return self._stream.inner.is_connected

    def connect(self) -> None:
        self._stream.inner.connect()

    def disconnect(self) -> None:
        self._stream.inner.disconnect()

    def send(self, data: bytes) -> None:
        self._stream.inner.send(data)

    def receive(self) -> bytes:
        with self._stream.lock:
            return b"".join(data for _, data in self._stream.pull())
