"""AlertCommandDispatcher: sends "speak this phrase" commands to the device.

The acting half of service.alarm_announcer, mirroring the split that
application.fan_dispatcher already uses -- and for the same hard reason:
:meth:`handle_announcement` runs inside the DataService publication chain,
which in Hardware mode is driven from the serial receive loop. Sending
there would re-enter that loop to wait for an acknowledgement. So this
class only records; :meth:`dispatch_pending`, called from the poll loop,
sends.

Where it differs from the fan dispatcher: a fan command carries a
*state*, an announcement is an *event*. That changes two behaviours.

- **No deduplication against a last-applied value.** There is nothing to
  compare against; every request that survives the announcer's own
  confirmation and cooldown rules is meant to be spoken.
- **Not retried after a real attempt.** If the command was actually sent
  and the device reported failure, the request is dropped rather than
  repeated: by the next poll cycle the alarm is seconds old, and a
  late announcement is worse than none -- the operator can already see
  the alarm on screen and in the activity log. Being *deferred* is
  different (nothing was sent, because a human client holds the device),
  and that case does stay pending for the next cycle.

If several announcements arrive between two poll cycles only the most
recent is kept: they would otherwise queue up behind a speaker that can
only say one thing at a time -- exactly the pile-up the announcer's
global cooldown exists to prevent.

Never raises into its caller: failures are counted, mirroring
application/hardware_runner.py's ``error_count``/``last_error``.
"""

from __future__ import annotations

from core.models import ClientId, DeviceId
from service.alarm_announcer import AnnouncementRequest
from service.command_models import Command, CommandStatus
from service.control_service import ControlService

DEFAULT_ALERT_CLIENT_ID: ClientId = "alarm-announcer"
"""Client identity spoken announcements act under.

Distinct from the fan's, so device status shows which automation is
holding a device at any moment.
"""


class AlertCommandDispatcher:
    """Applies :class:`AnnouncementRequest` values to one device."""

    def __init__(
        self,
        control_service: ControlService,
        device_id: DeviceId,
        client_id: ClientId = DEFAULT_ALERT_CLIENT_ID,
    ) -> None:
        self._control_service = control_service
        self._device_id = device_id
        self._client_id = client_id
        self._pending: AnnouncementRequest | None = None
        self.dispatch_count = 0
        self.deferred_count = 0
        self.failure_count = 0
        self.last_error: Exception | None = None

    @property
    def device_id(self) -> DeviceId:
        return self._device_id

    @property
    def pending(self) -> AnnouncementRequest | None:
        """Announcement waiting to be sent, if any."""
        return self._pending

    def handle_announcement(self, request: AnnouncementRequest) -> None:
        """Record ``request``. Sends nothing -- see the module docstring.

        Safe to register directly with
        ``AlarmAnnouncer.on_announcement``.
        """
        self._pending = request

    def dispatch_pending(self) -> None:
        """Send the pending announcement, if there is one. Never raises.

        Call from the same poll loop that drives ``runner.run_once()``.
        Cheap to call every cycle: returns immediately when idle.
        """
        request = self._pending
        if request is None:
            return

        try:
            self._dispatch(request)
        except Exception as exc:  # noqa: BLE001 -- see module docstring
            self.failure_count += 1
            self.last_error = exc
            self._pending = None

    def _dispatch(self, request: AnnouncementRequest) -> None:
        if not self._control_service.acquire(self._device_id, self._client_id):
            # A human client holds the device. Nothing was sent, so keep
            # the request for the next cycle.
            self.deferred_count += 1
            return

        try:
            result = self._control_service.submit_command(
                Command(
                    device_id=self._device_id,
                    command_type=request.kind.value,
                    origin=self._client_id,
                )
            )
        finally:
            self._control_service.release(self._device_id, self._client_id)

        # Attempted: drop it either way. A retry would speak a stale alarm.
        self._pending = None
        self.dispatch_count += 1
        if result.status is not CommandStatus.SUCCESS:
            self.failure_count += 1
