"""SensorDataProcessor: per-channel running statistics and threshold alarms.

Corresponds to docs/architecture.md's
"数据处理与分发" (data processing and distribution) responsibility, and
realizes the "传感器应用模拟验证阶段" task's data flow:

    SensorSimulator -> DataService -> SensorDataProcessor -> API/UI

``handle_data_point`` matches ``service.data_service.DataCallback``'s
signature exactly, so a SensorDataProcessor instance can be registered as
a normal DataService subscriber (``data_service.subscribe(device_id,
channel_id, processor.handle_data_point)``, or the ``subscribe_to()``
convenience below) -- no change to DataService/ApiInterface/ui is needed
for data to reach it.

The "-> API/UI" leg of that data flow was intentionally left unwired for
several tasks (see git history / docs/verification.md):
doing so meant extending ApiInterface, a deliberate step this codebase
requires justifying before taking (see CONTRIBUTING.md's "修改规则"). It has
since been wired up twice, both additively (no existing ApiInterface
method's signature changed): alarms (on_alarm/on_status ->
api.subscribe_alarm_status -> ui's activity log + row highlighting) and
statistics (on_statistics -> api.subscribe_statistics -> ui's
StatisticsPanelWidget). SensorDataProcessor itself remains a standalone,
independently pluggable component -- get_statistics()/on_alarm()/
on_status()/on_statistics() are its public surface; application/
runtime.py's ApplicationRuntime is what composes it into the platform.

Not device or UI logic: this module only processes DataPoint values it is
given through the DataService subscription mechanism -- it never imports
device.* or ui.*, and has no idea whether a value came from a
SimulatorDevice, a RemoteDevice, or anything else.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto

from core.exceptions import NotFoundError
from core.models import ChannelId, DeviceId
from device.sensors.channels import HUMIDITY_CHANNEL, NOISE_CHANNEL, TEMPERATURE_CHANNEL
from service.data_models import DataPoint
from service.data_service import DataService

TEMPERATURE_ALARM_MAX = 35.0
HUMIDITY_ALARM_MIN = 30.0
HUMIDITY_ALARM_MAX = 75.0
"""Upper humidity limit, added 2026-09-08 after the long-run
measurements showed the station sitting at 62~78%RH for most of a
run -- above the 40%~65% band GB 37488-2019 gives for air-conditioned
public spaces -- while the system, having only a lower bound, stayed
silent the whole time.

The number keeps the same 10-percentage-point margin outside the
standard's comfort band that the lower bound already used (40 - 10 = 30,
65 + 10 = 75). Both bounds are fault indicators, not comfort limits:
alarming at the edge of a comfort band would mean alarming during normal
operation, which is the reason the lower bound was placed outside it in
the first place.
"""
NOISE_ALARM_MAX = 80.0


class AlarmKind(Enum):
    """Which side of a threshold an AlarmEvent was triggered from."""

    ABOVE_MAX = auto()
    BELOW_MIN = auto()


@dataclass(frozen=True)
class AlarmBand:
    """A channel's acceptable range. Either bound may be absent.

    Replaces the single ``(AlarmKind, float)`` rule this module used until
    2026-09-08. A channel with one bound behaves exactly as before -- the
    change exists so a channel can have *two*, which humidity now does.
    """

    minimum: float | None = None
    maximum: float | None = None
    hysteresis: float = 0.0
    """Deadband applied when *clearing*, never when raising.

    An alarm starts the moment the reading crosses the bound, and ends only
    once it has come back this far inside it. Without the deadband a signal
    resting on its limit is alarmed or not according to sensor noise: the
    recorded long run has humidity sitting at 75.00%RH and dithering by
    ±0.07, which split one excursion into 45 / 1 / 45 readings -- the
    middle one being an alarm that lasted three seconds and meant nothing.

    Deliberately asymmetric. Raising late would delay a real alarm, which
    is the one thing this system must not do; clearing late only holds a
    warning slightly past its end.
    """

    def evaluate(
        self, value: float, alarmed: AlarmKind | None = None
    ) -> tuple[AlarmKind, float, bool]:
        """Classify ``value``: which bound the answer is about, that
        bound's value, and whether it is violated.

        A violated reading is always reported against the bound it
        actually crossed. A normal reading is reported against the
        **nearer** bound, so "22.0 ℃, well under 35 ℃" and "35%RH, not far
        off the 30%RH floor" each quote the limit that is in play rather
        than an arbitrary one. Exact ties go to the upper bound.

        ``alarmed`` is the side this channel is *currently* alarmed on, or
        None. It only ever widens the range that counts as violated, by
        :attr:`hysteresis` -- callers with no state to track (the question
        assistant describing one reading) leave it None and get the plain
        comparison. The bound returned is always the nominal one: a reader
        should see the limit the standard sets, not an internal deadband.
        """
        if self.maximum is not None:
            ceiling = self.maximum - (
                self.hysteresis if alarmed is AlarmKind.ABOVE_MAX else 0.0
            )
            if value > ceiling:
                return AlarmKind.ABOVE_MAX, self.maximum, True
        if self.minimum is not None:
            floor = self.minimum + (
                self.hysteresis if alarmed is AlarmKind.BELOW_MIN else 0.0
            )
            if value < floor:
                return AlarmKind.BELOW_MIN, self.minimum, True
        if self.maximum is None:
            assert self.minimum is not None  # guarded by __post_init__
            return AlarmKind.BELOW_MIN, self.minimum, False
        if self.minimum is None:
            return AlarmKind.ABOVE_MAX, self.maximum, False
        if value - self.minimum < self.maximum - value:
            return AlarmKind.BELOW_MIN, self.minimum, False
        return AlarmKind.ABOVE_MAX, self.maximum, False

    def __post_init__(self) -> None:
        if self.minimum is None and self.maximum is None:
            raise ValueError("an alarm band needs at least one bound")
        if self.hysteresis < 0:
            raise ValueError("hysteresis cannot be negative")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.hysteresis * 2 >= self.maximum - self.minimum
        ):
            # Two deadbands that meet in the middle would leave a band with
            # no normal region at all: once alarmed on either side, nothing
            # clears it.
            raise ValueError(
                f"hysteresis {self.hysteresis} is too wide for band "
                f"{self.minimum}~{self.maximum}"
            )
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum >= self.maximum
        ):
            raise ValueError(
                f"alarm band minimum {self.minimum} must be below maximum "
                f"{self.maximum}"
            )


TEMPERATURE_HYSTERESIS = 0.3
HUMIDITY_HYSTERESIS = 0.5
NOISE_HYSTERESIS = 1.0
"""Clearing deadbands, one per channel.

Sized against each channel's own restlessness rather than by a single
percentage: humidity was measured dithering ±0.07%RH while parked on its
bound, so 0.5 clears that with room to spare; temperature moves more
slowly still; noise swings by whole decibels between readings, and its
limit sits 40 dB above the ambient level, so its deadband exists for
completeness rather than because anything was seen to flap there.

Replaying all eleven recordings, 0.5%RH is also where the humidity
episode count stops changing -- see the sweep in the test below."""

_ALARM_RULES: dict[ChannelId, AlarmBand] = {
    TEMPERATURE_CHANNEL: AlarmBand(
        maximum=TEMPERATURE_ALARM_MAX, hysteresis=TEMPERATURE_HYSTERESIS
    ),
    HUMIDITY_CHANNEL: AlarmBand(
        minimum=HUMIDITY_ALARM_MIN,
        maximum=HUMIDITY_ALARM_MAX,
        hysteresis=HUMIDITY_HYSTERESIS,
    ),
    NOISE_CHANNEL: AlarmBand(
        maximum=NOISE_ALARM_MAX, hysteresis=NOISE_HYSTERESIS
    ),
}


@dataclass(frozen=True)
class AlarmEvent:
    """One threshold violation for one (device_id, channel) reading."""

    device_id: DeviceId
    channel: ChannelId
    value: float
    threshold: float
    kind: AlarmKind


@dataclass(frozen=True)
class ThresholdStatus:
    """Result of evaluating one DataPoint against its channel's threshold
    rule, whether or not it violates the threshold.

    Unlike AlarmEvent (only ever constructed when ``triggered`` is True,
    for :meth:`SensorDataProcessor.on_alarm`), this fires for *every*
    value on a channel that has a rule configured -- so a caller that
    needs to know when a channel has returned to normal (not just when it
    went into alarm) has something to subscribe to via
    :meth:`SensorDataProcessor.on_status`. A UI's "turn this row red"
    feature is the motivating case: on_alarm alone can turn a row red but
    never tells the UI when to turn it back.
    """

    device_id: DeviceId
    channel: ChannelId
    value: float
    threshold: float
    kind: AlarmKind
    triggered: bool


@dataclass(frozen=True)
class ChannelStatistics:
    """Immutable current/min/max/average snapshot for one (device, channel)."""

    current: float
    minimum: float
    maximum: float
    average: float
    sample_count: int


AlarmCallback = Callable[[AlarmEvent], None]
StatusCallback = Callable[[ThresholdStatus], None]
StatisticsCallback = Callable[[DeviceId, ChannelId, ChannelStatistics], None]


@dataclass
class _RunningStatistics:
    """Mutable accumulator backing one ChannelStatistics snapshot."""

    current: float
    minimum: float
    maximum: float
    total: float
    count: int

    @classmethod
    def start(cls, value: float) -> _RunningStatistics:
        return cls(current=value, minimum=value, maximum=value, total=value, count=1)

    def update(self, value: float) -> None:
        self.current = value
        self.minimum = min(self.minimum, value)
        self.maximum = max(self.maximum, value)
        self.total += value
        self.count += 1

    def snapshot(self) -> ChannelStatistics:
        return ChannelStatistics(
            current=self.current,
            minimum=self.minimum,
            maximum=self.maximum,
            average=self.total / self.count,
            sample_count=self.count,
        )


DEFAULT_CONFIRM_CYCLES = 2
"""Consecutive over-threshold readings before an alarm is considered real.

Confirmation used to live only in :class:`service.alarm_announcer.
AlarmAnnouncer`, so a lone spike stayed silent but still lit up the screen
and the board's LCD -- ``ThresholdStatus.triggered`` was evaluated per
reading and went straight to both. Two parts of one system disagreeing
about what counts as an alarm is the actual defect; moving the rule here
is what makes them agree.

Two cycles at a three-second period means an alarm appears three seconds
after the reading that caused it. That is an acceptable trade for a
monitoring system, and it is the same number the announcer already used.

**Only raising is confirmed; clearing is immediate.** Symmetric
confirmation would hold an alarm three seconds past its end, and nothing
in the recorded data suggests clearing flickers -- the two long runs cross
the threshold once each, both single-sample spikes from the noise sensor's
first Modbus frame. Should a real excursion ever be seen to flicker on the
clearing side, the counter below is where to add it."""


class SensorDataProcessor:
    """Maintains per-channel statistics and raises alarms for known
    environmental channels (temperature/humidity/noise thresholds)."""

    def __init__(self, confirm_cycles: int = DEFAULT_CONFIRM_CYCLES) -> None:
        if confirm_cycles < 1:
            raise ValueError("confirm_cycles must be at least 1")
        self._confirm_cycles = confirm_cycles
        self._statistics: dict[tuple[DeviceId, ChannelId], _RunningStatistics] = {}
        self._alarmed: dict[tuple[DeviceId, ChannelId], AlarmKind] = {}
        """Which side each channel is currently alarmed on, if any. Fed back
        into :meth:`AlarmBand.evaluate` so the clearing deadband applies."""
        self._streaks: dict[tuple[DeviceId, ChannelId], tuple[AlarmKind, int]] = {}
        """How many consecutive readings have been outside the band, and on
        which side. Keyed per device and channel; the side is kept because
        humidity has two bounds, and drifting from "too dry" to "too damp"
        is a new excursion that must earn its own confirmation."""
        self._alarm_callbacks: list[AlarmCallback] = []
        self._status_callbacks: list[StatusCallback] = []
        self._statistics_callbacks: list[StatisticsCallback] = []

    def subscribe_to(
        self, data_service: DataService, device_id: DeviceId, channel_id: ChannelId
    ) -> str:
        """Convenience: register handle_data_point on data_service for
        device_id/channel_id."""
        return data_service.subscribe(device_id, channel_id, self.handle_data_point)

    def on_alarm(self, callback: AlarmCallback) -> None:
        """Register ``callback`` to be invoked for every future AlarmEvent
        (i.e. only when a threshold is actually violated)."""
        self._alarm_callbacks.append(callback)

    def on_status(self, callback: StatusCallback) -> None:
        """Register ``callback`` to be invoked with a ThresholdStatus for
        every future evaluated point on a channel that has a threshold
        rule -- whether or not it triggers. See ThresholdStatus's
        docstring for why this exists alongside on_alarm."""
        self._status_callbacks.append(callback)

    def on_statistics(self, callback: StatisticsCallback) -> None:
        """Register ``callback`` to be invoked with the fresh
        ChannelStatistics snapshot for every future numeric DataPoint --
        for *any* channel this processor is subscribed to, not just the
        three with a threshold rule (unlike on_status/on_alarm)."""
        self._statistics_callbacks.append(callback)

    def handle_data_point(self, point: DataPoint) -> None:
        """Update statistics and evaluate alarms for one DataPoint.

        Matches service.data_service.DataCallback's signature, so this
        method itself is what gets passed to DataService.subscribe().
        Non-numeric values (including bool, which is technically an int
        subclass but not a meaningful sensor reading) are ignored rather
        than silently coerced into a misleading statistic.
        """
        if isinstance(point.value, bool) or not isinstance(point.value, int | float):
            return
        value = float(point.value)

        key = (point.device_id, point.channel)
        existing = self._statistics.get(key)
        if existing is None:
            existing = _RunningStatistics.start(value)
            self._statistics[key] = existing
        else:
            existing.update(value)

        snapshot = existing.snapshot()
        for stats_callback in self._statistics_callbacks:
            stats_callback(point.device_id, point.channel, snapshot)

        self._evaluate_threshold(point.device_id, point.channel, value)

    def get_statistics(
        self, device_id: DeviceId, channel_id: ChannelId
    ) -> ChannelStatistics:
        """Return the current/min/max/average snapshot for device_id/channel_id.

        Raises NotFoundError if no data point has been processed for that
        (device_id, channel_id) pair yet.
        """
        try:
            return self._statistics[(device_id, channel_id)].snapshot()
        except KeyError as exc:
            raise NotFoundError(
                f"no statistics yet for device {device_id!r} channel {channel_id!r}"
            ) from exc

    def _confirm(
        self,
        device_id: DeviceId,
        channel: ChannelId,
        kind: AlarmKind,
        outside: bool,
    ) -> bool:
        """Turn a single out-of-band reading into a confirmed alarm state.

        Returns True once ``confirm_cycles`` consecutive readings have been
        outside on the same side. A reading back inside clears the count
        immediately, so the next excursion starts from scratch rather than
        resuming one from minutes ago.
        """
        key = (device_id, channel)
        if not outside:
            self._streaks.pop(key, None)
            return False
        if self._alarmed.get(key) is kind:
            # Already alarmed on this side: an ongoing excursion does not
            # re-earn its confirmation on every reading.
            self._streaks[key] = (kind, self._confirm_cycles)
            return True
        previous = self._streaks.get(key)
        streak = 1 if previous is None or previous[0] is not kind else previous[1] + 1
        self._streaks[key] = (kind, streak)
        return streak >= self._confirm_cycles

    def _evaluate_threshold(
        self, device_id: DeviceId, channel: ChannelId, value: float
    ) -> None:
        band = _ALARM_RULES.get(channel)
        if band is None:
            return
        key = (device_id, channel)
        kind, threshold, outside = band.evaluate(value, self._alarmed.get(key))
        triggered = self._confirm(device_id, channel, kind, outside)
        if triggered:
            self._alarmed[key] = kind
        else:
            self._alarmed.pop(key, None)

        status = ThresholdStatus(
            device_id=device_id,
            channel=channel,
            value=value,
            threshold=threshold,
            kind=kind,
            triggered=triggered,
        )
        for status_callback in self._status_callbacks:
            status_callback(status)

        if not triggered:
            return
        event = AlarmEvent(
            device_id=device_id,
            channel=channel,
            value=value,
            threshold=threshold,
            kind=kind,
        )
        for alarm_callback in self._alarm_callbacks:
            alarm_callback(event)
