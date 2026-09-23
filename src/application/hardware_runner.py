"""HardwareRuntimeRunner: start/stop state management and a polling entry
point wrapping HardwareDeviceReceiver, for the "Hardware Runtime 持续驱动"
phase.

Corresponds to docs/verification.md's
observation that ``HardwareDeviceReceiver.poll_once()``/``poll_until_empty()``
had no outer driver keeping them running. This module adds exactly that
driver -- nothing else. It does not touch protocol/*, communication/*,
service/*, api/*, or ui/*, and does not modify
application/hardware_runtime.py: it only holds a HardwareDeviceReceiver
and calls its existing, unmodified public methods.

No QThread, no asyncio, no third-party dependency: "持续运行" is achieved
by whoever composes this (a future QTimer in ui/, a plain script loop, a
test) repeatedly calling :meth:`run_once` at :attr:`poll_interval_seconds`
cadence -- this class never loops or sleeps internally. This keeps it
trivially synchronous and testable with no real waiting required in
tests, consistent with every other phase-1 module in this codebase
staying synchronous until a real need for background execution arises
(see communication/interface.py's and application/hardware_runtime.py's
own docstrings for the same design choice applied one layer down).

Why this is not UI code: a QTimer (or any other driver) belongs to
whichever process embeds this runner -- deciding *when* to call
run_once() is a scheduling concern, not a rendering concern. Putting that
scheduling here keeps it reusable by a PyQt6 UI, a headless CLI script, or
a test, without any of them depending on the other two.
"""

from __future__ import annotations

from application.hardware_runtime import HardwareDeviceReceiver
from service.data_models import DataPoint

_DEFAULT_POLL_INTERVAL_SECONDS = 0.5


class HardwareRuntimeRunner:
    """Start/stop state + a single polling entry point around one
    HardwareDeviceReceiver.

    Holds exactly one HardwareDeviceReceiver (one Hardware-mode device's
    receive loop); running several devices means holding several
    HardwareRuntimeRunner instances, one per device -- this class does not
    manage a registry of them.
    """

    def __init__(
        self,
        receiver: HardwareDeviceReceiver,
        poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self._receiver = receiver
        self._poll_interval_seconds = poll_interval_seconds
        self._running = False
        self.error_count = 0
        self.last_error: Exception | None = None

    @property
    def receiver(self) -> HardwareDeviceReceiver:
        return self._receiver

    @property
    def running(self) -> bool:
        return self._running

    @property
    def poll_interval_seconds(self) -> float:
        """Configured polling cadence.

        Not used internally by this class -- it is a single source of
        truth for whatever external driver (a future QTimer, a plain
        script loop, ...) repeatedly calls :meth:`run_once`.
        """
        return self._poll_interval_seconds

    def start(self) -> None:
        """Mark the runner as running.

        Idempotent: calling start() again while already running does
        nothing -- it does not raise, does not reset error_count/
        last_error, and does not create a second concurrent "instance"
        of anything (there is nothing to duplicate: no thread, no task).
        """
        self._running = True

    def stop(self) -> None:
        """Mark the runner as stopped. Idempotent; safe even if never started."""
        self._running = False

    def run_once(self) -> list[DataPoint]:
        """Perform one poll cycle against the receiver and return the
        DataPoints processed.

        Works regardless of ``running`` state: ``running`` is metadata for
        an external driver to decide *whether* to call this repeatedly,
        not a gate this method enforces on itself -- a manual single-step
        call (e.g. from a test, or a "poll now" UI button) should always
        be honored.

        Never raises: any exception from the receiver or the
        communication channel it wraps (e.g. NotConnectedError if the
        channel was disconnected between calls) is caught, counted in
        ``error_count``, recorded in ``last_error``, and an empty list is
        returned. A transient receive failure must not corrupt this
        runner's own start/stop state or propagate into whatever is
        driving the poll loop -- the same "一个通信实例的异常不应影响其他
        模块或整体程序运行" isolation principle communication/interface.py
        already established, applied here one layer up.
        """
        try:
            return self._receiver.poll_until_empty()
        except Exception as exc:
            self.error_count += 1
            self.last_error = exc
            return []
