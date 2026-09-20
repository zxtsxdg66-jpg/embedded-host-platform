"""AlarmStateDispatcher: mirrors per-channel alarm state onto the device.

The board's LCD shows 正常/报警 next to each reading, but the firmware
does not know the alarm thresholds -- they live in
``service.sensor_data_processor`` and nowhere else, which is what keeps
the platform's one argued threshold set (GB 37488-2019, see that module)
from being duplicated into a second, silently diverging copy in C. So
the PC tells the board what state to display.

Unlike its two siblings this class has no separate decision component in
``service/``. There is nothing to decide: the bitmap is a pure
restatement of threshold evaluations the processor already produced.
Splitting it would create a class whose only behaviour is ``|=``.

Structurally it follows ``application.fan_dispatcher`` rather than
``application.alert_dispatcher``, because alarm state is a *state*, not
an event:

- deduplicated against the last-applied bitmap, so an ongoing alarm
  costs one command, not one per reading;
- retried on failure, since a display left showing the wrong state stays
  wrong until it is corrected.

And, like both siblings, it only *records* from the callback and sends
from :meth:`dispatch_pending`: :meth:`handle_threshold_status` runs
inside the DataService publication chain, which in Hardware mode is
driven from the serial receive loop, and sending there would re-enter
that loop. See ``application/fan_dispatcher.py`` for the full account of
that hazard.
"""

from __future__ import annotations

from core.models import ChannelId, ClientId, CommandType, DeviceId
from device.sensors.channels import HUMIDITY_CHANNEL, NOISE_CHANNEL, TEMPERATURE_CHANNEL
from service.command_models import Command, CommandStatus
from service.control_service import ControlService
from service.sensor_data_processor import ThresholdStatus

DEFAULT_ALARM_STATE_CLIENT_ID: ClientId = "alarm-state-mirror"
"""Client identity the mirror acts under.

Distinct from the fan's and the announcer's, so device status shows
which automation is holding the device at any moment.
"""

ALARM_STATE_COMMAND: CommandType = "ALERT_STATE"
"""Wire command name. Pinned to code 0x15 in application.manager's
RESERVED_COMMAND_CODES and mirrored in the firmware's protocol_frame.h."""

CHANNEL_BITS: dict[ChannelId, int] = {
    TEMPERATURE_CHANNEL: 0x01,
    HUMIDITY_CHANNEL: 0x02,
    NOISE_CHANNEL: 0x04,
}
"""Bit per channel. Must match UI_ALERT_BIT_* in the firmware's
``Drivers/BSP/UI_SCREEN/ui_screen.h`` -- another two-program contract no
compiler can check for us."""

BITS_PARAMETER = "bits"
"""Key the bitmap travels under in the command payload.

The payload is JSON because every command payload on this link is JSON
(see ``application.manager``'s module docstring); the firmware reads the
integer back out with a small key scan rather than a JSON parser."""


class AlarmStateDispatcher:
    """Keeps one device's alarm-state bitmap in step with the processor."""

    def __init__(
        self,
        control_service: ControlService,
        device_id: DeviceId,
        client_id: ClientId = DEFAULT_ALARM_STATE_CLIENT_ID,
        command_type: CommandType = ALARM_STATE_COMMAND,
    ) -> None:
        self._control_service = control_service
        self._device_id = device_id
        self._client_id = client_id
        self._command_type = command_type
        # Which (device, channel) pairs are currently over threshold.
        # Keyed by device too, so two devices reporting the same channel
        # cannot cancel each other out.
        self._triggered: set[tuple[DeviceId, ChannelId]] = set()
        # 0, not None: the firmware powers up with every row showing
        # 正常, so assuming an all-clear bitmap avoids a redundant command
        # on start-up (same reasoning as FanCommandDispatcher's
        # ``_applied_state = False``).
        self._applied_bits = 0
        self._pending_bits = 0
        self.dispatch_count = 0
        self.deferred_count = 0
        self.failure_count = 0
        self.last_error: Exception | None = None

    @property
    def device_id(self) -> DeviceId:
        return self._device_id

    @property
    def applied_bits(self) -> int:
        """Bitmap currently believed to be displayed on the device."""
        return self._applied_bits

    @property
    def pending_bits(self) -> int:
        """Bitmap the platform wants displayed, applied or not."""
        return self._pending_bits

    @property
    def has_pending_change(self) -> bool:
        """Whether :meth:`dispatch_pending` currently has work to do."""
        return self._pending_bits != self._applied_bits

    def handle_threshold_status(self, status: ThresholdStatus) -> None:
        """Fold one threshold evaluation into the bitmap. Sends nothing.

        Matches ``service.sensor_data_processor.StatusCallback``, so it
        can be registered directly with ``SensorDataProcessor.on_status``.
        Channels with no bit assigned (a future sensor type) are ignored
        rather than rejected -- the board simply has no row for them.
        """
        if status.channel not in CHANNEL_BITS:
            return

        key = (status.device_id, status.channel)
        if status.triggered:
            self._triggered.add(key)
        else:
            self._triggered.discard(key)

        bits = 0
        for _, channel in self._triggered:
            bits |= CHANNEL_BITS[channel]
        self._pending_bits = bits

    def dispatch_pending(self) -> None:
        """Send the bitmap if it differs from the applied one. Never raises.

        Call from the same poll loop that drives ``runner.run_once()``.
        Cheap to call every cycle: returns immediately when nothing changed.
        """
        if not self.has_pending_change:
            return

        desired = self._pending_bits
        try:
            self._dispatch(desired)
        except Exception as exc:  # noqa: BLE001 -- see module docstring
            self.failure_count += 1
            self.last_error = exc

    def _dispatch(self, desired_bits: int) -> None:
        """Acquire, submit, release. Records the new bitmap only on success."""
        if not self._control_service.acquire(self._device_id, self._client_id):
            # A human client holds the device; the display can wait a cycle.
            self.deferred_count += 1
            return

        try:
            result = self._control_service.submit_command(
                Command(
                    device_id=self._device_id,
                    command_type=self._command_type,
                    origin=self._client_id,
                    parameters={BITS_PARAMETER: desired_bits},
                )
            )
        finally:
            self._control_service.release(self._device_id, self._client_id)

        self.dispatch_count += 1
        if result.status is CommandStatus.SUCCESS:
            self._applied_bits = desired_bits
        else:
            # Leaves _applied_bits alone so the next cycle retries.
            self.failure_count += 1
