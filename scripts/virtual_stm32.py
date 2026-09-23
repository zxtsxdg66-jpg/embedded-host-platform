"""Virtual STM32: simulates a real UART device end to end.

Corresponds to docs/decisions/01-simulation.md. Purpose: exercise
Hardware Mode's *entire* real receive chain --

    SerialChannel.receive() -> protocol.decode() -> HardwareDeviceReceiver
        -> DataService.publish() -> ... -> UI

-- without a physical MCU, by playing the device side of a real serial
link. Unlike every other test double in this codebase (LoopbackChannel,
mocked pyserial), this script writes to an *actual* OS serial port, so it
can be paired with a real GUI process (``scripts/run_gui.py --mode
hardware``) running against the other end of a virtual COM port pair
(e.g. com0com on Windows) -- the closest thing to a hardware-in-the-loop
test achievable without owning an STM32.

This script deliberately does not import anything from src/protocol,
src/communication, src/application, src/service, src/api, or src/ui
beyond what it needs to *use* their already-public, unmodified APIs
(protocol.encoder.encode, protocol.frame.Frame, communication.serial.
SerialChannel) -- none of those five packages are modified by this file.

It also deliberately hardcodes DATA_REPORT_CODE = 0x01 (and, for the same
reason, COMMAND_ACK_CODE = 0x02) rather than importing them from
application.manager: this script plays the role of the *device* (MCU)
side of the wire, and a real STM32 firmware would hardcode these same
values in C, not import PC-side Python -- duplicating the constants here
is a more faithful stand-in for what real firmware does than sharing code
with the host application would be. Both sides only ever agree through
the protocol *specification* (docs/protocol.md),
never through shared code. For the same reason, the small byte-stream
frame-boundary recovery this script needs to read incoming commands is
reimplemented locally (see ``_extract_frame`` below) rather than
importing application.frame_stream.FrameStreamBuffer -- a real MCU would
have to implement that logic in C from scratch regardless.

Between each cycle of sending its three DATA_REPORT frames, this script
also listens for and acknowledges any command frame addressed to it
(COMMAND_ACK_CODE reply), so that ``scripts/run_gui.py --mode
hardware``'s "发送命令" action gets a genuine response from this virtual
device -- not just from Simulator mode's LoopbackChannel, which the host
side (application/manager.py's DeviceManager.deliver) fabricates locally
and this script has no part in.

Reuses device.sensors' realistic value generators (SmoothRandomWalkGenerator/
NoiseWithSpikesGenerator via TemperatureSensorSimulator/HumiditySensorSimulator/
NoiseSensorSimulator) purely for their .generate(channel).value output --
device/sensors/* is not in this task's forbidden-to-modify list, and reusing
it keeps the simulated values consistent with the rest of the project
instead of duplicating range constants.

Usage
-----
    python scripts/virtual_stm32.py --port COM4
    python scripts/virtual_stm32.py --port COM4 --device-id 1 --interval 2.0

See docs/decisions/01-simulation.md for how to pair this with
``scripts/run_gui.py --mode hardware`` using a virtual COM port pair.

In-process use (2026-09-23)
---------------------------
The loop now lives in :class:`VirtualStm32`, which talks to any
``CommunicationChannel`` -- a real serial port as before, or the device end
of ``communication.pipe.make_pipe_pair()``. ``scripts/run_api_server.py
--mode virtual`` uses the latter, so the host's real receive chain runs
without a board *or* a virtual COM driver
(docs/decisions/08-web.md).

It can also misbehave on purpose (:class:`FaultPlan`): split a frame
across writes, glue a cycle's frames into one write, put stray bytes
between frames, flip a bit in a CRC. The first three are what a real UART
does to a byte stream and must be absorbed silently by the host's frame
sync; the fourth must be caught by the CRC and counted. Watching that
happen live is what the web console's protocol inspector is for. The
device side still imports nothing from ``application``: it agrees with the
host only through the protocol specification, as real firmware would.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

# Allow running this script directly without first requiring
# `pip install -e .`: add src/ to sys.path before importing project code.
_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from communication.interface import CommunicationChannel  # noqa: E402
from communication.serial import SerialChannel  # noqa: E402
from device.sensors.channels import (  # noqa: E402
    HUMIDITY_CHANNEL,
    NOISE_CHANNEL,
    TEMPERATURE_CHANNEL,
)
from device.sensors.humidity import HumiditySensorSimulator  # noqa: E402
from device.sensors.noise import NoiseSensorSimulator  # noqa: E402
from device.sensors.temperature import TemperatureSensorSimulator  # noqa: E402
from protocol.decoder import decode  # noqa: E402
from protocol.encoder import (  # noqa: E402
    BYTE_ORDER,
    CRC_SIZE,
    HEADER,
    LENGTH_SIZE,
    encode,
)
from protocol.exceptions import ProtocolError  # noqa: E402
from protocol.frame import Frame  # noqa: E402

DATA_REPORT_CODE = 0x01
"""Must match the frame.command_type value docs/protocol.md and
application/manager.py reserve for device -> host data
reports. See module docstring for why this is a literal, not an import."""

COMMAND_ACK_CODE = 0x02
"""Must match application/manager.py's COMMAND_ACK_CODE. See module
docstring for why this is a literal, not an import (same reasoning as
DATA_REPORT_CODE above)."""

DEFAULT_DEVICE_ID = 1
DEFAULT_BAUDRATE = 115200
DEFAULT_INTERVAL_SECONDS = 2.0

_LENGTH_OFFSET = len(HEADER) + 1 + 1  # header + device_id(1B) + command_type(1B)
_FIXED_PREFIX_SIZE = _LENGTH_OFFSET + LENGTH_SIZE
_COMMAND_POLL_CHUNK_SECONDS = 0.1


def build_frame(device_id: int, channel_id: str, value: float) -> bytes:
    """Encode one DATA_REPORT frame for ``channel_id``=``value``, exactly
    as a real MCU following the protocol spec would.

    Payload is UTF-8 JSON ``{"channel": ..., "value": ...}`` -- the same
    phase-1 convention application/manager.py and application/
    hardware_runtime.py already use on the PC side.
    """
    payload = json.dumps({"channel": channel_id, "value": value}).encode("utf-8")
    frame = Frame(device_id=device_id, command_type=DATA_REPORT_CODE, payload=payload)
    return encode(frame)


def _extract_frame(buffer: bytearray) -> bytes | None:
    """Slice exactly one complete frame off the front of ``buffer`` if one
    is fully present, discarding leading bytes that cannot start a frame.

    A minimal, self-contained stand-in for what real MCU firmware would
    need to implement in C to parse a byte stream with no message
    boundaries -- see module docstring for why this duplicates (rather
    than imports) application/frame_stream.py's equivalent logic.
    """
    if not buffer:
        return None
    index = buffer.find(HEADER)
    if index != 0:
        if index == -1:
            # No header anywhere buffered: drop garbage, keeping only a
            # possible partial header match at the tail for next call.
            keep = min(len(HEADER) - 1, len(buffer))
            del buffer[: len(buffer) - keep]
        else:
            # Header found, but with leading garbage before it: drop only
            # that garbage, keeping the header and everything after it.
            del buffer[:index]
        return None
    if len(buffer) < _FIXED_PREFIX_SIZE:
        return None
    declared_length = int.from_bytes(
        buffer[_LENGTH_OFFSET : _LENGTH_OFFSET + LENGTH_SIZE], BYTE_ORDER
    )
    total_size = _FIXED_PREFIX_SIZE + declared_length + CRC_SIZE
    if len(buffer) < total_size:
        return None
    frame_bytes = bytes(buffer[:total_size])
    del buffer[:total_size]
    return frame_bytes


def _drain_and_ack_commands(
    channel: CommunicationChannel,
    device_id: int,
    buffer: bytearray,
    listen_seconds: float,
    stop: threading.Event | None = None,
    verbose: bool = True,
) -> None:
    """Spend ``listen_seconds`` listening for command frames addressed to
    ``device_id`` and acknowledging every one of them with a
    COMMAND_ACK_CODE frame.

    Accepts every command type unconditionally -- unlike Simulator mode's
    ``registration.accepted_commands`` gate (application/manager.py), this
    script has no equivalent concept; a real device would decide
    accept/reject in its own firmware.
    """
    elapsed = 0.0
    while elapsed < listen_seconds and not (stop is not None and stop.is_set()):
        raw = channel.receive()
        if raw:
            buffer.extend(raw)
        while True:
            frame_bytes = _extract_frame(buffer)
            if frame_bytes is None:
                break
            try:
                frame = decode(frame_bytes)
            except ProtocolError:
                continue
            if frame.device_id != device_id or frame.command_type in (
                DATA_REPORT_CODE,
                COMMAND_ACK_CODE,
            ):
                continue
            ack_payload = json.dumps({"status": "success"}).encode("utf-8")
            ack = Frame(
                device_id=device_id,
                command_type=COMMAND_ACK_CODE,
                payload=ack_payload,
            )
            channel.send(encode(ack))
            if verbose:
                print(f"[virtual-stm32] acked command_type={frame.command_type}")
        time.sleep(_COMMAND_POLL_CHUNK_SECONDS)
        elapsed += _COMMAND_POLL_CHUNK_SECONDS


@dataclass(frozen=True)
class FaultPlan:
    """How often each kind of misbehaviour happens, as probabilities.

    ``garbage`` bytes never include 0xAA, the first header byte, so each
    injection costs the host exactly one resync -- a stray byte that
    happened to start a false header would add a decode error on top,
    which is realistic but makes the counters harder to read in a demo.
    """

    split: float = 0.0
    """A frame is written in two pieces with a short pause between."""
    merge: float = 0.0
    """A whole cycle's frames go out in a single write."""
    garbage: float = 0.0
    """1-6 stray bytes precede a frame."""
    bitflip: float = 0.0
    """One bit of a frame's CRC is flipped, so the host must reject it."""


DEFAULT_FAULTS = FaultPlan(split=0.25, merge=0.3, garbage=0.1, bitflip=0.03)
"""What ``--inject-faults`` uses: enough of each to see within a minute."""

_SPLIT_PAUSE_SECONDS = 0.05


class VirtualStm32:
    """The device side of the link: reports three channels, acks commands.

    ``channel`` must already be connected. :meth:`run` loops until
    ``stop`` is set, so it can live on a thread in-process or on the main
    thread of the command-line script.
    """

    def __init__(
        self,
        channel: CommunicationChannel,
        device_id: int = DEFAULT_DEVICE_ID,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        faults: FaultPlan | None = None,
        seed: int | None = None,
        verbose: bool = True,
    ) -> None:
        self._channel = channel
        self._device_id = device_id
        self._interval = interval_seconds
        self._faults = faults or FaultPlan()
        self._rng = random.Random(seed)
        self._verbose = verbose
        # With a seed the readings are seeded too, so a whole session is
        # reproducible: split points depend on frame lengths, which depend on
        # the values' digits -- an unseeded sensor made every run differ.
        def sensor_rng(offset: int) -> random.Random | None:
            return None if seed is None else random.Random(seed + offset)

        self._sensors = (
            (TemperatureSensorSimulator(rng=sensor_rng(1)), TEMPERATURE_CHANNEL),
            (HumiditySensorSimulator(rng=sensor_rng(2)), HUMIDITY_CHANNEL),
            (NoiseSensorSimulator(rng=sensor_rng(3)), NOISE_CHANNEL),
        )
        self._command_buffer = bytearray()
        self.injected: dict[str, int] = {
            "split": 0, "merge": 0, "garbage": 0, "bitflip": 0,
        }
        """How many of each fault were actually injected -- what the host's
        counters should be checked against."""

    def _chance(self, rate: float) -> bool:
        return rate > 0 and self._rng.random() < rate

    def _garbage(self) -> bytes:
        pool = [b for b in range(256) if b != HEADER[0]]
        return bytes(self._rng.choice(pool) for _ in range(self._rng.randint(1, 6)))

    def _prepare(self, frame: bytes) -> bytes:
        """Apply the per-frame faults: a flipped CRC bit, stray bytes before it."""
        if self._chance(self._faults.bitflip):
            buf = bytearray(frame)
            buf[-1 - self._rng.randrange(CRC_SIZE)] ^= 1 << self._rng.randrange(8)
            frame = bytes(buf)
            self.injected["bitflip"] += 1
        if self._chance(self._faults.garbage):
            frame = self._garbage() + frame
            self.injected["garbage"] += 1
        return frame

    def _write(self, data: bytes) -> None:
        if len(data) > 2 and self._chance(self._faults.split):
            cut = self._rng.randrange(1, len(data))
            self._channel.send(data[:cut])
            time.sleep(_SPLIT_PAUSE_SECONDS)
            self._channel.send(data[cut:])
            self.injected["split"] += 1
        else:
            self._channel.send(data)

    def cycle(self) -> None:
        """Send one report per channel, faults applied."""
        frames = []
        for sensor, channel_id in self._sensors:
            # Two decimals, as the real firmware reports -- full floats made the
            # frames longer than any board would send them.
            value = round(sensor.generate(channel_id).value, 2)
            frame = build_frame(self._device_id, channel_id, value)
            frames.append(self._prepare(frame))
            if self._verbose:
                print(f"[virtual-stm32] sent {channel_id}={value:.2f}")
        if self._chance(self._faults.merge):
            self.injected["merge"] += 1
            self._write(b"".join(frames))
        else:
            for frame in frames:
                self._write(frame)

    def run(self, stop: threading.Event | None = None) -> None:
        """Report, then listen for commands for one interval; repeat."""
        while not (stop is not None and stop.is_set()):
            self.cycle()
            _drain_and_ack_commands(
                self._channel, self._device_id, self._command_buffer,
                self._interval, stop=stop, verbose=self._verbose,
            )


def run(
    port: str,
    device_id: int = DEFAULT_DEVICE_ID,
    baudrate: int = DEFAULT_BAUDRATE,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    faults: FaultPlan | None = None,
) -> None:
    """Connect to ``port`` and send temperature/humidity/noise
    DATA_REPORT frames on a loop until interrupted (Ctrl+C)."""
    channel = SerialChannel(port=port, baudrate=baudrate)
    channel.connect()
    print(
        f"[virtual-stm32] connected to {port} at {baudrate} baud, "
        f"device_id={device_id}, interval={interval_seconds}s "
        "(Ctrl+C to stop)"
    )
    device = VirtualStm32(channel, device_id, interval_seconds, faults=faults)
    try:
        device.run()
    except KeyboardInterrupt:
        print(f"\n[virtual-stm32] stopping; injected {device.injected}")
    finally:
        channel.disconnect()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port", required=True, help="serial port to write frames to, e.g. COM4"
    )
    parser.add_argument(
        "--device-id",
        type=int,
        default=DEFAULT_DEVICE_ID,
        help=(
            "numeric device id embedded in each frame (Frame.device_id, "
            f"0-255; must match the wire id the receiving "
            f"HardwareDeviceReceiver expects, default: {DEFAULT_DEVICE_ID})"
        ),
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=DEFAULT_BAUDRATE,
        help=f"serial baud rate (default: {DEFAULT_BAUDRATE})",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"seconds between report cycles (default: {DEFAULT_INTERVAL_SECONDS})",
    )
    parser.add_argument(
        "--inject-faults",
        action="store_true",
        help="split/merge frames, add stray bytes and flip CRC bits (see FaultPlan)",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = _parse_args(sys.argv[1:])
    run(
        port=args.port,
        device_id=args.device_id,
        baudrate=args.baudrate,
        interval_seconds=args.interval,
        faults=DEFAULT_FAULTS if args.inject_faults else None,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
