"""FanCommandDispatcher: turns VentilationController decisions into commands.

This is the "act" half that service.ventilation_controller deliberately
does not do. Keeping the two apart follows the same split the codebase
already uses for alarms: ``SensorDataProcessor`` decides that a threshold
was crossed and knows nothing about UIs or commands; whoever composes the
platform decides what that should *cause*.

Placed in ``application`` rather than ``service`` because dispatching is a
composition concern -- it needs to know which device carries the fan, under
which client identity to act, and which command names that device
understands. None of that belongs to the rule that decides whether air
should be moving.

Three behaviours worth knowing about:

**Deduplication.** ``VentilationController`` emits a decision for *every*
evaluated reading (see its module docstring), i.e. roughly every 3 s in
Hardware mode. Sending a command that often would be pointless traffic on
a link whose reliability this project measures, so this class only
dispatches when the desired state differs from the last one it managed to
apply.

**Occupancy.** Command dispatch goes through ControlService, which enforces
docs/architecture.md's "共享读、独占写"
rule: a command is refused unless its origin currently holds the device.
Automatic ventilation is not a client competing for that lock, so it
acquires immediately before dispatching and releases immediately after,
rather than holding the device permanently and locking a human out. If a
human *is* holding the device, ``acquire`` fails and this class stands
down for that round -- manual control deliberately wins.

**Retry for free.** A failed dispatch (refused acquire, transport error,
device did not acknowledge) leaves ``applied_state`` unchanged, so the
next attempt re-offers the same desired state and simply repeats. There
is no retry timer because the poll loop already provides one.

Deciding and sending are deliberately split across two methods
-------------------------------------------------------------
:meth:`handle_decision` only *records* what the fan should be doing; only
:meth:`dispatch_pending` talks to the device. The caller drives the
second one from its poll loop, next to ``runner.run_once()``.

This split is not stylistic -- sending from inside ``handle_decision``
was tried first and is actively unsafe in Hardware mode. That callback
runs inside the DataService publication chain, which in Hardware mode is
itself invoked from ``HardwareRuntimeRunner.run_once()`` while it is
reading the serial port. Dispatching there re-enters
``DeviceManager.deliver()``, whose RemoteDevice path reads that *same*
port to wait for the acknowledgement, using its own FrameStreamBuffer.
Two readers on one stream lose frames to each other, and the whole
round trip blocks the caller's timer callback. It was not theoretical:
2026-09-07 it aborted the test process outright (``Fatal Python error:
Aborted`` while pytest-qt processed events), and on real hardware it
would have blocked the UI for the acknowledgement timeout and dropped
sensor readings arriving during the wait.

Never raises into its caller either way: failures are counted, mirroring
application/hardware_runner.py's ``error_count``/``last_error``.
"""

from __future__ import annotations

from core.models import ClientId, CommandType, DeviceId
from service.command_models import Command, CommandStatus
from service.control_service import ControlService
from service.ventilation_controller import FanDecision

DEFAULT_FAN_CLIENT_ID: ClientId = "ventilation-auto"
"""Client identity automatic ventilation acts under.

Distinct from any UI client id on purpose: device status shows who holds a
device, and "ventilation-auto" is more informative there than borrowing
the GUI's identity would be.
"""

DEFAULT_FAN_ON_COMMAND: CommandType = "FAN_ON"
DEFAULT_FAN_OFF_COMMAND: CommandType = "FAN_OFF"


class FanCommandDispatcher:
    """Applies :class:`FanDecision` values to one device as commands."""

    def __init__(
        self,
        control_service: ControlService,
        device_id: DeviceId,
        client_id: ClientId = DEFAULT_FAN_CLIENT_ID,
        on_command: CommandType = DEFAULT_FAN_ON_COMMAND,
        off_command: CommandType = DEFAULT_FAN_OFF_COMMAND,
    ) -> None:
        self._control_service = control_service
        self._device_id = device_id
        self._client_id = client_id
        self._on_command = on_command
        self._off_command = off_command
        # False, not None: the firmware powers up with the fan stopped, so
        # assuming "off" is what the device is actually doing avoids
        # sending a pointless FAN_OFF command on every start-up -- which
        # in Hardware mode costs a full command round trip before the
        # first reading has even been displayed.
        self._applied_state = False
        self._pending_state = False
        self.dispatch_count = 0
        self.deferred_count = 0
        self.failure_count = 0
        self.last_error: Exception | None = None

    @property
    def device_id(self) -> DeviceId:
        return self._device_id

    @property
    def applied_state(self) -> bool:
        """Fan state currently believed to be in effect on the device."""
        return self._applied_state

    @property
    def pending_state(self) -> bool:
        """Fan state the platform wants, whether or not it is applied yet."""
        return self._pending_state

    @property
    def has_pending_change(self) -> bool:
        """Whether :meth:`dispatch_pending` currently has work to do."""
        return self._pending_state != self._applied_state

    def handle_decision(self, decision: FanDecision) -> None:
        """Record the fan state ``decision`` asks for. Sends nothing.

        Safe to register directly with
        ``VentilationController.on_decision`` -- and safe *because* it
        sends nothing: this runs inside the data-publication chain, where
        talking to the device would re-enter the serial read loop (see
        the module docstring). :meth:`dispatch_pending` does the sending.
        """
        self._pending_state = decision.should_run

    def dispatch_pending(self) -> None:
        """Send a command if the desired state differs from the applied one.

        Call this from the same poll loop that drives
        ``runner.run_once()``, not from a data callback. Cheap and safe to
        call every cycle: it returns immediately when nothing changed.
        Never raises.
        """
        if not self.has_pending_change:
            return

        desired = self._pending_state
        command_type = self._on_command if desired else self._off_command
        try:
            self._dispatch(command_type, desired)
        except Exception as exc:  # noqa: BLE001 -- see module docstring
            self.failure_count += 1
            self.last_error = exc

    def _dispatch(self, command_type: CommandType, desired_state: bool) -> None:
        """Acquire, submit, release. Records the new state only on success."""
        if not self._control_service.acquire(self._device_id, self._client_id):
            # A human client holds the device; manual control wins this round.
            self.deferred_count += 1
            return

        try:
            result = self._control_service.submit_command(
                Command(
                    device_id=self._device_id,
                    command_type=command_type,
                    origin=self._client_id,
                )
            )
        finally:
            self._control_service.release(self._device_id, self._client_id)

        self.dispatch_count += 1
        if result.status is CommandStatus.SUCCESS:
            self._applied_state = desired_state
        else:
            # Leaves _applied_state alone so the next decision retries.
            self.failure_count += 1
