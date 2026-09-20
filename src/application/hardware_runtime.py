"""HardwareDeviceReceiver: Hardware-mode data receive loop, bridging
CommunicationChannel (SerialChannel in production) -> Protocol -> DataService.

Corresponds to docs/05_Test/Hardware_Simulation_Mode.md's Hardware-mode
link (RemoteDevice + SerialChannel + Protocol) and completes the one piece
that document flagged as still missing: the data *receive* loop --
"从 SerialChannel 持续读取字节、解码为 Frame、映射回具体 RemoteDevice 的数据
接收循环".

Data flow this module realizes::

    SerialChannel.receive() -> protocol.decode() -> Frame ->
    DataPoint -> DataService.publish() -> (SensorDataProcessor / UI, via
    their own existing DataService subscriptions -- unmodified)

This is purely an application-layer bridge: it does not modify
protocol/frame.py, protocol/encoder.py, protocol/decoder.py,
communication/interface.py, communication/serial.py, or any
service/api/ui interface -- it only *calls* their existing, unmodified
public functions/methods, exactly like application/manager.py already
does for Simulator mode's downlink (DeviceManager.deliver()). The
DATA_REPORT_CODE wire convention is imported (not redefined) from
application.manager, which already owns that phase-1 convention, so the
two never drift apart.

Deliberately standalone: HardwareDeviceReceiver does not go through
DeviceManager/ApplicationRuntime's device registry -- it takes the wire id
a Hardware-mode device already agreed on directly, rather than relying on
DeviceManager's auto-incrementing registration (which Simulator mode
uses). This keeps this module purely additive: no change to
application/manager.py or application/runtime.py was needed to add it.

Command dispatch (downlink) is a separate concern -- see
application/manager.py's DeviceManager.deliver(), which now has its own
Hardware-mode round trip (a real wait for the device's acknowledgement,
not the uplink loop this module implements); this module only completes
the uplink/receive half, so that Hardware mode's final data flow matches
Simulator mode's exactly once both are wired to the same DataService:

    Simulator: SimulatorDevice -> DataService
    Hardware:  RemoteDevice -> SerialChannel -> HardwareDeviceReceiver -> DataService

Frame-boundary recovery over the raw byte stream (SerialChannel has no
message boundaries, unlike LoopbackChannel) is delegated to
application.frame_stream.FrameStreamBuffer, shared with
DeviceManager.deliver()'s Hardware-mode ack wait so both callers that
read frames off a real stream use one correct implementation.
"""

from __future__ import annotations

import json

from application.frame_stream import FrameStreamBuffer
from application.manager import DATA_REPORT_CODE
from communication.interface import CommunicationChannel
from core.models import ChannelId, DeviceId
from protocol.decoder import decode
from protocol.exceptions import ProtocolError
from service.data_models import DataPoint
from service.data_service import DataService

_MAX_DRAIN_ITERATIONS = 1000


class HardwareDeviceReceiver:
    """Drains DATA_REPORT frames from one CommunicationChannel and
    publishes them as DataPoints for one RemoteDevice.

    ``wire_id`` is the numeric device id this device's frames are expected
    to carry (the Hardware-mode counterpart to DeviceManager's
    auto-assigned wire ids for Simulator mode) -- it must match whatever
    the connected MCU firmware was configured to send.
    """

    def __init__(
        self,
        device_id: DeviceId,
        wire_id: int,
        channel: CommunicationChannel,
        data_service: DataService,
    ) -> None:
        self._device_id = device_id
        self._wire_id = wire_id
        self._channel = channel
        self._data_service = data_service
        self.error_count = 0
        self.ignored_frame_count = 0
        self._stream = FrameStreamBuffer(on_discard=self._count_discard)

    def _count_discard(self) -> None:
        self.error_count += 1

    @property
    def device_id(self) -> DeviceId:
        return self._device_id

    def poll_once(self) -> DataPoint | None:
        """Read and process at most one pending frame from the channel.

        Returns the published DataPoint, or None if nothing was pending
        (or not enough bytes had arrived yet to complete a frame -- the
        remainder stays buffered for the next call), the frame was
        malformed (CRC/sync/length error), addressed to a different wire
        id, not a DATA_REPORT frame, or carried an unparseable payload --
        callers that want to observe those cases can inspect
        ``error_count``/``ignored_frame_count`` afterward.
        """
        frame_bytes = self._next_frame()
        if frame_bytes is None:
            return None
        return self._process_frame(frame_bytes)

    def poll_until_empty(self) -> list[DataPoint]:
        """Repeatedly poll until the channel reports nothing pending.

        This is the "持续读取" loop the task describes, expressed as a
        single synchronous drain rather than a background thread --
        consistent with every other phase-1 module in this codebase
        staying synchronous (see communication/interface.py's docstring)
        until a real need for async/threaded execution arises. A
        corrupted or ignored frame does not stop the drain -- only
        running out of complete frames to extract (or the safety
        iteration cap) does. A single receive() burst that happens to
        contain several concatenated frames (routine over a real
        byte-stream transport) is fully drained across iterations of this
        loop even though only one receive() call produced it.
        """
        points: list[DataPoint] = []
        for _ in range(_MAX_DRAIN_ITERATIONS):
            frame_bytes = self._next_frame()
            if frame_bytes is None:
                break
            point = self._process_frame(frame_bytes)
            if point is not None:
                points.append(point)
        return points

    def _next_frame(self) -> bytes | None:
        """Return the next complete frame's raw bytes, buffering as needed.

        Tries the already-buffered bytes first (a prior receive() may have
        delivered more than one frame at once); only calls
        ``channel.receive()`` if the buffer doesn't already hold a
        complete frame.
        """
        frame_bytes = self._stream.extract_frame()
        if frame_bytes is not None:
            return frame_bytes

        raw = self._channel.receive()
        if raw:
            self._stream.feed(raw)
        return self._stream.extract_frame()

    def _process_frame(self, raw: bytes) -> DataPoint | None:
        try:
            frame = decode(raw)
        except ProtocolError:
            self.error_count += 1
            return None

        if frame.device_id != self._wire_id or frame.command_type != DATA_REPORT_CODE:
            self.ignored_frame_count += 1
            return None

        try:
            body = json.loads(frame.payload.decode("utf-8"))
            channel_id: ChannelId = body["channel"]
            value = body["value"]
        except (ValueError, KeyError):
            self.error_count += 1
            return None

        point = DataPoint(device_id=self._device_id, channel=channel_id, value=value)
        self._data_service.publish(point)
        return point
