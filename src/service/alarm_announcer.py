"""AlarmAnnouncer: decides *when* a threshold alarm should be spoken aloud.

Sits between service.sensor_data_processor (which decides that a reading
crossed a threshold) and whatever plays the audio. It answers a narrower
question than either: "should we say something out loud right now?" --
and the answer is deliberately not "yes, every time a reading is over the
limit".

Two guards, both required, for different reasons
------------------------------------------------
**Consecutive confirmation.** A single over-threshold sample is not
enough; ``confirm_cycles`` readings in a row are. A lone spike -- a door
slamming near the noise sensor, a hand brushing the temperature probe --
should not trigger an announcement. This also implements, for the
announcement path, an improvement the threshold alarm itself still lacks
("为报警判定引入回差与持续时间确认").

**Cooldown.** After announcing, stay quiet for ``cooldown_seconds``. This
is the guard that actually breaks the acoustic feedback loop: the speaker
is loud enough to push the noise sensor over its own 80 dB(A) threshold,
so without a cooldown one announcement could trigger the next, which
would trigger the next. Firmware-side blanking (skipping the noise
Modbus request while audio plays) removes the polluted *readings*; this
cooldown bounds the *announcements* even if some noise still leaks
through.

The cooldown is **global, not per-channel**: there is one speaker, it can
only say one thing at a time, and a queue of announcements from three
channels firing in sequence is exactly the runaway this is meant to
prevent. A consequence worth knowing: if temperature announces and noise
crosses its threshold a second later, noise stays silent until the
cooldown expires. That is intended -- the operator has already been
alerted, and the alarm is still visible on screen and in the activity log.

Scope boundary: this module only *decides*. It builds no Command, touches
no ControlService, and imports nothing from ``application``/
``communication``/``protocol`` -- exactly like
service.ventilation_controller. Turning an AnnouncementRequest into a
command is application.alert_dispatcher's job.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from core.models import ChannelId, DeviceId
from core.timestamps import monotonic_ms
from device.sensors.channels import HUMIDITY_CHANNEL, NOISE_CHANNEL, TEMPERATURE_CHANNEL
from service.sensor_data_processor import AlarmKind, ThresholdStatus

DEFAULT_CONFIRM_CYCLES = 1
"""Confirmation now happens upstream.

Was 2 until 2026-09-09, when the same rule moved into
:class:`service.sensor_data_processor.SensorDataProcessor` so that the
screen and the board's LCD would stop disagreeing with the speaker. Left
at 1 rather than removed: the streak below still does the other half of
this class's job -- announcing an excursion once rather than on every
reading of it -- and a caller that wants belt-and-braces confirmation on
top of the processor's can still ask for it."""
"""Consecutive over-threshold readings required before announcing.

Two, at the firmware's 3 s acquisition period, means roughly 6 s of a
sustained condition -- long enough to reject a single spike, short enough
that a real excursion is announced promptly.
"""

DEFAULT_COOLDOWN_SECONDS = 30.0
"""Quiet period after an announcement, across all channels."""


class AlertKind(Enum):
    """Which of the fixed spoken phrases an announcement asks for.

    A closed set on purpose: the firmware stores three pre-synthesised
    clips in its flash, so this cannot grow without also adding audio on
    the device side. The value is the wire-level command name, keeping the
    mapping to a device command in one place.
    """

    TEMPERATURE = "ALERT_TEMPERATURE"
    HUMIDITY = "ALERT_HUMIDITY"
    NOISE = "ALERT_NOISE"


_CHANNEL_ALERTS: dict[ChannelId, AlertKind] = {
    TEMPERATURE_CHANNEL: AlertKind.TEMPERATURE,
    HUMIDITY_CHANNEL: AlertKind.HUMIDITY,
    NOISE_CHANNEL: AlertKind.NOISE,
}


@dataclass(frozen=True)
class AnnouncementRequest:
    """One decision that a phrase should be spoken now."""

    kind: AlertKind
    device_id: DeviceId
    channel: ChannelId


AnnouncementCallback = Callable[[AnnouncementRequest], None]


class AlarmAnnouncer:
    """Turns a stream of ThresholdStatus into occasional announcements."""

    def __init__(
        self,
        confirm_cycles: int = DEFAULT_CONFIRM_CYCLES,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        clock_ms: Callable[[], int] = monotonic_ms,
    ) -> None:
        """``clock_ms`` is injectable so tests can advance time without
        sleeping; it must be monotonic (see core.timestamps.monotonic_ms)
        -- a wall clock would let a system time adjustment shorten or
        extend a cooldown."""
        if confirm_cycles < 1:
            raise ValueError("confirm_cycles must be at least 1")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must not be negative")
        self._confirm_cycles = confirm_cycles
        self._cooldown_ms = int(cooldown_seconds * 1000)
        self._clock_ms = clock_ms
        self._streaks: dict[tuple[DeviceId, ChannelId], tuple[AlarmKind, int]] = {}
        self._last_announced_ms: int | None = None
        self._callbacks: list[AnnouncementCallback] = []
        self.suppressed_count = 0
        """Announcements withheld because the cooldown was still active --
        counted so the behaviour is observable rather than invisible."""

    def on_announcement(self, callback: AnnouncementCallback) -> None:
        """Register ``callback`` for every future announcement decision."""
        self._callbacks.append(callback)

    def handle_threshold_status(self, status: ThresholdStatus) -> None:
        """Feed one threshold evaluation in.

        Matches ``service.sensor_data_processor.StatusCallback``'s
        signature, so this method itself is what gets registered with
        ``SensorDataProcessor.on_status``.
        """
        key = (status.device_id, status.channel)

        if not status.triggered:
            # Back to normal: the next excursion must earn its
            # confirmation from scratch rather than resuming a stale
            # streak from minutes ago.
            self._streaks.pop(key, None)
            return

        kind = _CHANNEL_ALERTS.get(status.channel)
        if kind is None:
            return

        # Restart the count when the excursion flips to the other side of
        # the band: humidity has two bounds since 2026-09-08, and a run
        # that drifts from "too dry" to "too damp" is a new excursion that
        # must earn its own confirmation -- carrying the streak over would
        # announce the second one immediately.
        previous = self._streaks.get(key)
        if previous is None or previous[0] is not status.kind:
            streak = 1
        else:
            streak = previous[1] + 1
        self._streaks[key] = (status.kind, streak)
        if streak < self._confirm_cycles:
            return
        if streak > self._confirm_cycles:
            # Already announced for this ongoing excursion; do not
            # re-announce every subsequent reading. The cooldown would
            # mostly absorb this anyway, but relying on it would mean a
            # long excursion announces again the moment it expires.
            return

        self._announce(
            AnnouncementRequest(
                kind=kind, device_id=status.device_id, channel=status.channel
            )
        )

    def _announce(self, request: AnnouncementRequest) -> None:
        if self._in_cooldown():
            self.suppressed_count += 1
            return
        self._last_announced_ms = self._clock_ms()
        for callback in self._callbacks:
            callback(request)

    def _in_cooldown(self) -> bool:
        if self._last_announced_ms is None:
            return False
        return (self._clock_ms() - self._last_announced_ms) < self._cooldown_ms

    @property
    def cooldown_active(self) -> bool:
        """Whether announcements are currently being suppressed."""
        return self._in_cooldown()
