"""DeviceManager: device registry and wire-level bridging.

Corresponds to docs/02_Architecture/Core_Service_Design.md Section 4's
"设备生命周期管理" (device lifecycle management) responsibility, and
realizes the bridging work flagged as deferred in protocol/README.md:
"Service Layer 字符串 DeviceId 与 Frame 数值型 device_id 之间的映射".

Registers and bridges any device.interface.DeviceInterface-conforming
object -- both Simulator mode (device.simulator.SimulatorDevice) and
Hardware mode (device.remote.RemoteDevice) devices register and dispatch
commands through the exact same code path here; see
docs/05_Test/Hardware_Simulation_Mode.md for what distinguishes the two
modes. The one capability that is *not* uniform is uplink data
generation (:meth:`report_data`): only devices that implement
``generate()`` (currently just SimulatorDevice) support it -- a
RemoteDevice never generates its own data, per its own module docstring,
so calling report_data() for one raises ValidationError instead of
silently doing nothing.

DeviceManager owns:

- the DeviceId (str) <-> Frame.device_id (int, 0-255) mapping, one entry
  per registered device
- turning a generated DataPoint into a data-report Frame and back
  (uplink), and a Command into a request Frame plus the device's
  acknowledgement Frame into a CommandResult (downlink)
- also satisfies service.control_service_impl.CommandTransport structurally,
  via its ``deliver`` method, so an InMemoryControlService can dispatch
  commands through it without importing protocol/communication itself

Phase-1 wire conventions (chosen here, not in Protocol_Design.md, and not
part of the Protocol Layer's own contract -- protocol/ remains fully
payload-agnostic):

- ``DATA_REPORT_CODE`` / ``COMMAND_ACK_CODE`` are two fixed
  ``Frame.command_type`` values reserved for device->host frames; any
  other code is a host->device business command, assigned per
  ``Command.command_type`` string the first time a device sees it.
- ``Frame.payload`` carries a UTF-8 JSON document (stdlib ``json``, not a
  third-party dependency) whose shape depends on the frame kind above.

Everything here runs synchronously and in-process: "sending" and
"receiving" happen back-to-back within one method call, since phase 1 has
no real concurrency to interleave (see communication/interface.py's
docstring for the same phase-1 simplification applied there).

Not bound to any specific sensor, controlled object, or MCU model: this
module only moves DataPoint/Command/CommandResult values across the wire,
never inspects their business meaning.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from application.frame_stream import FrameStreamBuffer
from communication.interface import CommunicationChannel
from core.exceptions import NotFoundError, OperationTimeoutError, ValidationError
from core.models import ChannelId, CommandType, DeviceId
from core.timestamps import monotonic_ms, now_utc
from device.interface import DeviceInterface
from protocol.decoder import decode
from protocol.encoder import encode
from protocol.exceptions import ProtocolError
from protocol.frame import Frame
from service.command_models import Command, CommandResult, CommandStatus
from service.data_models import DataPoint


@runtime_checkable
class _DataGeneratingDevice(Protocol):
    """Structural contract for devices that can produce their own DataPoint.

    Currently only device.simulator.SimulatorDevice satisfies this.
    device.remote.RemoteDevice deliberately does not -- a real device
    produces its own data over its own transport; DeviceManager must
    never be asked to generate data on a real device's behalf.
    """

    def generate(self, channel_id: ChannelId) -> DataPoint: ...

DATA_REPORT_CODE = 0x01
COMMAND_ACK_CODE = 0x02
_FIRST_BUSINESS_COMMAND_CODE = 0x10

RESERVED_COMMAND_CODES: dict[CommandType, int] = {
    "FAN_ON": 0x10,
    "FAN_OFF": 0x11,
    # Spoken alarm phrases. The names match service.alarm_announcer's
    # AlertKind values, which is where the channel -> phrase mapping lives.
    "ALERT_TEMPERATURE": 0x12,
    "ALERT_HUMIDITY": 0x13,
    "ALERT_NOISE": 0x14,
    # Per-channel alarm bitmap for the board's LCD. The device has to read
    # the payload, not just acknowledge it -- see
    # application.alarm_state_dispatcher.
    "ALERT_STATE": 0x15,
    # Last answer, for the board's second page. Six unsigned integers, and
    # deliberately not text: the board's font is a 34-glyph subset (see
    # application.answer_dispatcher), so a sentence cannot be drawn.
    "ANSWER_SHOW": 0x16,
}
"""Command types pinned to a fixed wire code, and why that is necessary.

Codes for business commands are normally assigned on first use (see
:meth:`DeviceRegistration.code_for`), which was fine as long as no device
*acted* on them -- the firmware acknowledged any command without
interpreting it. Ventilation changed that: the MCU has to tell "start the
fan" from "stop the fan", and a code that depends on which command
happened to be sent first in this session cannot carry that meaning.

Anything a device must interpret therefore belongs here, and the firmware
side mirrors these exact values in
``firmware/stm32f407/Drivers/BSP/PROTOCOL/protocol_frame.h``. Keep the two
in sync -- they are a wire contract between two independently compiled
programs, and nothing but review catches a mismatch.
"""

_FIRST_DYNAMIC_COMMAND_CODE = 0x20
"""Where on-demand assignment starts.

Deliberately above the reserved block (0x10-0x1F) so a dynamically
assigned code can never collide with a pinned one, no matter how many
distinct command types a session uses.
"""
_MAX_WIRE_ID = 0xFF
_COMMAND_ACK_TIMEOUT_SECONDS = 2.0
_COMMAND_ACK_POLL_INTERVAL_SECONDS = 0.02


class DeviceRegistration:
    """Everything DeviceManager needs to talk to one managed device
    (Simulator- or Hardware-mode)."""

    def __init__(
        self,
        device: DeviceInterface,
        channel: CommunicationChannel,
        wire_id: int,
        accepted_commands: Sequence[CommandType],
    ) -> None:
        self.device = device
        self.channel = channel
        self.wire_id = wire_id
        self.accepted_commands = frozenset(accepted_commands)
        self._command_codes: dict[CommandType, int] = dict(RESERVED_COMMAND_CODES)
        self._next_command_code = _FIRST_DYNAMIC_COMMAND_CODE
        # Persistent across deliver() calls (not per-call) so bytes left
        # over after one command's ack -- e.g. a DATA_REPORT frame that
        # happened to arrive interleaved with it -- aren't discarded, only
        # deprioritized: they simply wait to be resolved (and dropped, see
        # DeviceManager._await_device_ack's docstring) on the next call.
        # Only ever used for Hardware-mode (RemoteDevice) registrations.
        self.ack_stream = FrameStreamBuffer()

    def code_for(self, command_type: CommandType) -> int:
        """Return the wire code for ``command_type``, assigning one if new.

        Types listed in :data:`RESERVED_COMMAND_CODES` already have their
        code seeded in ``_command_codes``, so they always resolve to the
        same value the firmware expects; everything else is assigned on
        first use from 0x20 upwards.
        """
        if command_type not in self._command_codes:
            self._command_codes[command_type] = self._next_command_code
            self._next_command_code += 1
        return self._command_codes[command_type]


class DeviceManager:
    """Registers Simulator- or Hardware-mode devices and bridges them to
    Protocol/Communication."""

    def __init__(self) -> None:
        self._registrations: dict[DeviceId, DeviceRegistration] = {}
        self._next_wire_id = 1

    def register(
        self,
        device: DeviceInterface,
        channel: CommunicationChannel,
        accepted_commands: Sequence[CommandType] = (),
    ) -> DeviceRegistration:
        """Register ``device`` (reachable over ``channel``), assign it a wire id,
        and connect ``channel`` if it is not already connected."""
        if device.device_id in self._registrations:
            raise ValidationError(f"device already registered: {device.device_id!r}")
        if self._next_wire_id > _MAX_WIRE_ID:
            raise ValidationError("no wire ids remaining (phase 1 limit: 255 devices)")

        if not channel.is_connected:
            channel.connect()

        registration = DeviceRegistration(
            device=device,
            channel=channel,
            wire_id=self._next_wire_id,
            accepted_commands=accepted_commands,
        )
        self._registrations[device.device_id] = registration
        self._next_wire_id += 1
        return registration

    def get(self, device_id: DeviceId) -> DeviceRegistration:
        try:
            return self._registrations[device_id]
        except KeyError as exc:
            raise NotFoundError(f"unknown device: {device_id!r}") from exc

    def list_device_ids(self) -> list[DeviceId]:
        """Return the ids of all currently registered devices."""
        return list(self._registrations.keys())

    # -- uplink: device generates data -> wire -> host reconstructs it ----

    def report_data(self, device_id: DeviceId, channel_id: ChannelId) -> DataPoint:
        """Run one full uplink cycle: generate, transmit, and receive it back.

        Only supported for devices that implement ``generate()`` (Simulator
        mode). A Hardware-mode RemoteDevice never generates its own data --
        calling this for one is a programming error, not a normal "no data
        yet" condition, so it raises rather than returning silently.
        """
        registration = self.get(device_id)
        if not isinstance(registration.device, _DataGeneratingDevice):
            raise ValidationError(
                f"device {device_id!r} does not support software data "
                "generation (only Simulator-mode devices do; see "
                "docs/05_Test/Hardware_Simulation_Mode.md)"
            )
        point = registration.device.generate(channel_id)

        payload = json.dumps({"channel": point.channel, "value": point.value}).encode(
            "utf-8"
        )
        frame = Frame(
            device_id=registration.wire_id,
            command_type=DATA_REPORT_CODE,
            payload=payload,
        )
        registration.channel.send(encode(frame))

        received = decode(registration.channel.receive())
        if (
            received.device_id != registration.wire_id
            or received.command_type != DATA_REPORT_CODE
        ):
            raise ProtocolError("unexpected frame received while reading data report")

        body = json.loads(received.payload.decode("utf-8"))
        return DataPoint(
            device_id=device_id, channel=body["channel"], value=body["value"]
        )

    # -- downlink: host dispatches a command -> wire -> device acks -------

    def deliver(self, command: Command) -> CommandResult:
        """CommandTransport implementation: dispatch ``command``, return its result."""
        registration = self.get(command.device_id)
        code = registration.code_for(command.command_type)

        request_payload = json.dumps(dict(command.parameters)).encode("utf-8")
        request = Frame(
            device_id=registration.wire_id, command_type=code, payload=request_payload
        )
        registration.channel.send(encode(request))

        if isinstance(registration.device, _DataGeneratingDevice):
            ack_body = self._simulate_device_ack(registration, command)
        else:
            ack_body = self._await_device_ack(registration)

        status = (
            CommandStatus.SUCCESS
            if ack_body["status"] == "success"
            else CommandStatus.FAILED
        )
        return CommandResult(
            command_id=command.command_id,
            status=status,
            message=(
                ""
                if status is CommandStatus.SUCCESS
                else f"device did not accept command type {command.command_type!r}"
            ),
            completed_at=now_utc(),
        )

    def _simulate_device_ack(
        self, registration: DeviceRegistration, command: Command
    ) -> dict[str, str]:
        """Simulator-mode only: LoopbackChannel has no independent "device"
        actor that reads and answers commands on its own, so DeviceManager
        plays that role locally here -- read back the just-sent request
        (its own echo, discarded) and fabricate an ack based on
        ``registration.accepted_commands``. This only works because
        LoopbackChannel preserves one send() as one receive() with no
        transmission delay; see _await_device_ack for why Hardware-mode
        devices cannot use this shortcut.
        """
        _ = decode(registration.channel.receive())
        accepted = command.command_type in registration.accepted_commands
        ack_payload = json.dumps(
            {"status": "success" if accepted else "failed"}
        ).encode("utf-8")
        ack = Frame(
            device_id=registration.wire_id,
            command_type=COMMAND_ACK_CODE,
            payload=ack_payload,
        )
        registration.channel.send(encode(ack))
        received_ack = decode(registration.channel.receive())
        return json.loads(received_ack.payload.decode("utf-8"))  # type: ignore[no-any-return]

    def _await_device_ack(self, registration: DeviceRegistration) -> dict[str, str]:
        """Hardware-mode: wait for a real COMMAND_ACK_CODE frame the
        connected device (real MCU firmware, or scripts/virtual_stm32.py
        standing in for one) sends back on its own initiative -- unlike
        Simulator mode, nothing on the host side can fabricate this ack;
        deciding accept/reject is the device's job, not
        ``registration.accepted_commands`` (which _simulate_device_ack
        alone reads).

        A real byte-stream transport has no message boundaries and
        command execution isn't instantaneous, so this polls
        ``registration.ack_stream`` (a FrameStreamBuffer, correctly
        recovering frames split or concatenated across receive() calls)
        with a bounded timeout instead of assuming the ack is already
        sitting in the channel's buffer the instant the request was sent.

        Frames that arrive while waiting but aren't this ack (wrong wire
        id/command type -- most commonly a DATA_REPORT frame interleaved
        with the ack) are not this method's to deliver anywhere: only
        HardwareDeviceReceiver's own poll loop publishes DataPoints, and
        it isn't reachable from here, so such a frame is simply skipped.
        This is a deliberate phase-1 tradeoff (see docs/05_Test/
        Project_Status_Context.md's Hardware-mode command notes): at most
        one sensor reading can be missed while a command round trip is in
        flight, in exchange for keeping this synchronous and not needing
        a shared receive loop between DeviceManager and
        HardwareDeviceReceiver.
        """
        stream = registration.ack_stream
        deadline_ms = monotonic_ms() + int(_COMMAND_ACK_TIMEOUT_SECONDS * 1000)
        while True:
            frame_bytes = stream.extract_frame()
            if frame_bytes is None:
                raw = registration.channel.receive()
                if raw:
                    stream.feed(raw)
                    frame_bytes = stream.extract_frame()

            if frame_bytes is not None:
                try:
                    frame = decode(frame_bytes)
                except ProtocolError:
                    continue  # corrupted frame; keep waiting for a good one
                if (
                    frame.device_id == registration.wire_id
                    and frame.command_type == COMMAND_ACK_CODE
                ):
                    return json.loads(frame.payload.decode("utf-8"))  # type: ignore[no-any-return]
                continue  # not our ack (e.g. a DATA_REPORT frame); keep waiting

            if monotonic_ms() >= deadline_ms:
                raise OperationTimeoutError(
                    f"device {registration.wire_id!r} did not acknowledge "
                    f"the command within {_COMMAND_ACK_TIMEOUT_SECONDS}s"
                )
            time.sleep(_COMMAND_ACK_POLL_INTERVAL_SECONDS)
