"""SimulatorRuntimeRunner: the periodic driver Simulator mode was missing.

Why this exists
---------------
Hardware mode has a driver: ``HardwareRuntimeRunner.run_once()`` is called
repeatedly (by a QTimer in scripts/run_gui.py) to pull bytes off the serial
port. Simulator mode had no equivalent -- ``ApplicationRuntime.report_data()``
(the call that makes a SimulatorDevice actually produce a value) was invoked
*only from tests*, never from any running application. Verified empirically
on 2026-08-14: composing a SimulatorDevice exactly as scripts/run_gui.py
does, subscribing, and waiting produces zero data points until report_data()
is called explicitly.

So this module is the Simulator-mode counterpart of hardware_runner.py, and
is deliberately shaped identically to it:

- no thread, no asyncio, no sleeping, no internal loop
- one ``run_once()`` entry point an external driver calls at
  ``poll_interval_seconds`` cadence (a QTimer, a plain script loop, a test)
- ``start()``/``stop()``/``running`` are metadata for that external driver,
  not gates this class enforces on itself
- ``run_once()`` never raises: a failure on one channel is counted and
  swallowed so it cannot break the driver or the other channels

It adds no new concept to the architecture -- it only calls
``ApplicationRuntime.report_data()``, which already existed and is already
the documented "software data generation" entry point (see
application/manager.py's report_data docstring: Simulator-mode devices
only).
"""

from __future__ import annotations

from application.runtime import ApplicationRuntime
from core.exceptions import PlatformError
from core.models import ChannelId, DeviceId
from service.data_models import DataPoint

_DEFAULT_POLL_INTERVAL_SECONDS = 1.0


class SimulatorRuntimeRunner:
    """Periodically drives ``report_data()`` for a fixed set of
    (device_id, channel_id) pairs.

    The pairs are supplied explicitly rather than discovered from the
    runtime, because "which channels should be generating data" is a
    composition decision belonging to whoever builds the runtime (a
    launcher script), not something this driver should infer -- the same
    reasoning that keeps HardwareRuntimeRunner holding exactly one
    receiver handed to it, rather than managing a registry.
    """

    def __init__(
        self,
        runtime: ApplicationRuntime,
        targets: list[tuple[DeviceId, ChannelId]],
        poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self._runtime = runtime
        self._targets = list(targets)
        self._poll_interval_seconds = poll_interval_seconds
        self._running = False
        self.error_count = 0
        self.last_error: Exception | None = None

    @property
    def targets(self) -> list[tuple[DeviceId, ChannelId]]:
        return list(self._targets)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def poll_interval_seconds(self) -> float:
        """Configured cadence; not used internally -- a single source of
        truth for whatever external driver calls :meth:`run_once`."""
        return self._poll_interval_seconds

    def start(self) -> None:
        """Mark the runner as running. Idempotent."""
        self._running = True

    def stop(self) -> None:
        """Mark the runner as stopped. Idempotent; safe if never started."""
        self._running = False

    def run_once(self) -> list[DataPoint]:
        """Generate one data point per configured target and return them.

        Works regardless of ``running`` state, same as
        HardwareRuntimeRunner.run_once(): ``running`` tells an external
        driver whether to keep calling, it does not gate a manual
        single-step call.

        Never raises: a PlatformError on one target (e.g. the device was
        unregistered between calls) is counted in ``error_count``,
        recorded in ``last_error``, and the remaining targets are still
        attempted.
        """
        points: list[DataPoint] = []
        for device_id, channel_id in self._targets:
            try:
                points.append(self._runtime.report_data(device_id, channel_id))
            except PlatformError as exc:
                self.error_count += 1
                self.last_error = exc
        return points
