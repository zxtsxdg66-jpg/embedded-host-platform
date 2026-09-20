"""VentilationController: threshold-driven fan (ventilation) decisions.

Structurally parallel to service.sensor_data_processor.SensorDataProcessor:
``handle_data_point`` matches ``service.data_service.DataCallback`` exactly,
so an instance registers as an ordinary DataService subscriber and needs no
change to DataService/ApiInterface/ui for data to reach it.

Why this is a separate component rather than more rules inside
SensorDataProcessor
-------------------------------------------------------------------
The two answer different questions and must be able to move independently:

- ``SensorDataProcessor`` answers *"should a human be warned?"*. Its
  thresholds (temperature > 35 °C, humidity < 30 %RH, noise > 80 dB(A))
  are the ones argued from GB 37488-2019 in the thesis, and they are
  deliberately **fixed** -- changing them would invalidate that argument.
- This module answers *"should the fan run?"*. Its thresholds are a
  separate, **runtime-adjustable** set with different semantics, and one
  of them points the other way round: the alarm rule for humidity is
  BELOW_MIN (too dry), but blowing air at air that is too dry accomplishes
  nothing -- ventilation is what you want when humidity is too *high*.
  (Measured humidity on the real hardware stayed in 69~95 %RH, so the
  BELOW_MIN alarm rule never fires in practice; see
  docs/05_Test/Project_Status_Context.md section 5.9.)

Keeping them apart means the thesis's alarm argument stays untouched while
ventilation gets thresholds that are both physically sensible and tunable
for a live demonstration.

Scope boundary: this module **decides**, it does not **act**. It never
builds a Command, never touches ControlService, and never imports
``application``/``communication``/``protocol`` -- exactly like
SensorDataProcessor, which raises alarms without knowing what a UI is.
Turning a :class:`FanDecision` into an actual command dispatched to a
device is the composition root's job (application/runtime.py).

Emission model: :meth:`on_decision` callbacks fire on *every* evaluated
data point, not only on transitions -- the same choice
``SensorDataProcessor.on_status`` makes, and for the same reason. A
consumer that only cares about changes can dedupe trivially; a consumer
that wants to display the current desired state continuously (a UI panel)
would otherwise have nothing to read. Deduplicating command dispatch is
therefore the caller's responsibility, which also gives it a natural
retry: if a dispatch fails, the caller simply leaves its "last applied"
state unchanged and the next data point re-offers the same decision.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto

from core.models import ChannelId, DeviceId
from device.sensors.channels import HUMIDITY_CHANNEL, TEMPERATURE_CHANNEL
from service.data_models import DataPoint
from service.data_service import DataService

DEFAULT_TEMPERATURE_VENTILATION_MAX = 30.0
"""Default temperature (°C) above which ventilation is requested.

Deliberately lower than SensorDataProcessor's 35 °C alarm threshold:
ventilation is a mitigation that should start *before* the condition is
bad enough to warrant alarming a human.
"""

DEFAULT_HUMIDITY_VENTILATION_MAX = 80.0
"""Default relative humidity (%RH) above which ventilation is requested.

Chosen against the measured range on the real hardware (69~95 %RH): high
enough that the fan is not running permanently, low enough that it can
actually be reached during a demonstration.
"""


class FanMode(Enum):
    """Who decides whether the fan runs."""

    AUTO = auto()
    """Follow the ventilation thresholds."""

    MANUAL_ON = auto()
    """Force the fan on, ignoring thresholds."""

    MANUAL_OFF = auto()
    """Force the fan off, ignoring thresholds."""


@dataclass(frozen=True)
class VentilationSettings:
    """Immutable snapshot of this controller's configuration."""

    temperature_max: float
    humidity_max: float
    mode: FanMode


@dataclass(frozen=True)
class FanDecision:
    """The fan state this controller currently wants, and why.

    ``reason`` is a short human-readable explanation intended for a UI
    activity log or an on-screen label. It is presentation *text*, not a
    machine-readable code -- callers must not branch on its content.
    """

    should_run: bool
    reason: str
    mode: FanMode


FanDecisionCallback = Callable[[FanDecision], None]

_VENTILATION_CHANNELS: tuple[ChannelId, ...] = (
    TEMPERATURE_CHANNEL,
    HUMIDITY_CHANNEL,
)
"""Channels that can request ventilation. Noise deliberately excluded: a
fan does not reduce sound, and running one would make it worse."""


class VentilationController:
    """Decides whether the ventilation fan should run, from temperature and
    humidity readings plus a manual override."""

    def __init__(
        self,
        temperature_max: float = DEFAULT_TEMPERATURE_VENTILATION_MAX,
        humidity_max: float = DEFAULT_HUMIDITY_VENTILATION_MAX,
    ) -> None:
        self._temperature_max = temperature_max
        self._humidity_max = humidity_max
        self._mode = FanMode.AUTO
        self._latest: dict[tuple[DeviceId, ChannelId], float] = {}
        self._decision_callbacks: list[FanDecisionCallback] = []

    # -- wiring -----------------------------------------------------------

    def subscribe_to(
        self, data_service: DataService, device_id: DeviceId, channel_id: ChannelId
    ) -> str:
        """Convenience: register handle_data_point on data_service for
        device_id/channel_id. Mirrors SensorDataProcessor.subscribe_to."""
        return data_service.subscribe(device_id, channel_id, self.handle_data_point)

    def on_decision(self, callback: FanDecisionCallback) -> None:
        """Register ``callback`` for every future FanDecision.

        Fires on every evaluated reading and on every settings change, not
        only on transitions -- see the module docstring for why.
        """
        self._decision_callbacks.append(callback)

    # -- configuration ----------------------------------------------------

    @property
    def settings(self) -> VentilationSettings:
        """Current thresholds and mode."""
        return VentilationSettings(
            temperature_max=self._temperature_max,
            humidity_max=self._humidity_max,
            mode=self._mode,
        )

    def set_thresholds(
        self, temperature_max: float | None = None, humidity_max: float | None = None
    ) -> None:
        """Update either or both ventilation thresholds, then re-evaluate.

        ``None`` leaves that threshold unchanged, so a caller can adjust
        one without having to know the other. Re-evaluates immediately
        rather than waiting for the next reading, so a UI slider produces
        visible feedback at once.
        """
        if temperature_max is not None:
            self._temperature_max = temperature_max
        if humidity_max is not None:
            self._humidity_max = humidity_max
        self._emit(self.evaluate())

    def set_mode(self, mode: FanMode) -> None:
        """Switch between automatic control and a manual override, then
        re-evaluate immediately (same reasoning as set_thresholds)."""
        self._mode = mode
        self._emit(self.evaluate())

    # -- data path --------------------------------------------------------

    def handle_data_point(self, point: DataPoint) -> None:
        """Record one reading and re-evaluate.

        Matches service.data_service.DataCallback's signature, so this
        method itself is what gets passed to DataService.subscribe().

        Ignores readings that cannot contribute to a ventilation decision:
        channels other than temperature/humidity, points flagged
        ``valid=False`` (Hardware mode reports a channel that way when its
        sensor read failed -- acting on a failed read would be worse than
        keeping the previous value), and non-numeric values. ``bool`` is
        excluded explicitly because it is an ``int`` subclass but never a
        meaningful sensor reading -- same guard as SensorDataProcessor.
        """
        if point.channel not in _VENTILATION_CHANNELS:
            return
        if not point.valid:
            return
        if isinstance(point.value, bool) or not isinstance(point.value, int | float):
            return

        self._latest[(point.device_id, point.channel)] = float(point.value)
        self._emit(self.evaluate())

    def evaluate(self) -> FanDecision:
        """Compute the currently desired fan state without emitting it.

        Exposed separately from the callback path so a caller can query
        the current decision on demand (e.g. to render an initial UI state
        before any reading has arrived).
        """
        if self._mode is FanMode.MANUAL_ON:
            return FanDecision(True, "手动开启", self._mode)
        if self._mode is FanMode.MANUAL_OFF:
            return FanDecision(False, "手动关闭", self._mode)

        reasons = self._exceeded_reasons()
        if reasons:
            return FanDecision(True, "、".join(reasons), self._mode)
        return FanDecision(False, "温湿度均在通风阈值以内", self._mode)

    def _exceeded_reasons(self) -> list[str]:
        """Human-readable reasons for every channel currently over its
        ventilation threshold, in a stable order (temperature first).

        Every exceeding channel is reported, not just the first one, so a
        UI can show that both conditions are active at once.
        """
        reasons: list[str] = []
        for channel, threshold, label, unit in (
            (TEMPERATURE_CHANNEL, self._temperature_max, "温度", "℃"),
            (HUMIDITY_CHANNEL, self._humidity_max, "湿度", "%RH"),
        ):
            worst = self._worst_value(channel)
            if worst is not None and worst > threshold:
                reasons.append(
                    f"{label} {worst:.1f}{unit} 高于通风阈值 {threshold:g}{unit}"
                )
        return reasons

    def _worst_value(self, channel: ChannelId) -> float | None:
        """Highest recorded value on ``channel`` across all devices, or None.

        Aggregating across devices (rather than tracking a single device)
        is what lets one controller serve both runtime modes unchanged:
        Hardware mode reports temperature and humidity from one device,
        Simulator mode from two separate ones. "Any device reporting an
        over-threshold value should start ventilation" is the behaviour
        that reads correctly in both.
        """
        values = [
            value
            for (_, recorded_channel), value in self._latest.items()
            if recorded_channel == channel
        ]
        return max(values) if values else None

    def _emit(self, decision: FanDecision) -> None:
        for callback in self._decision_callbacks:
            callback(decision)
