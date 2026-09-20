"""Stage 2: turn an :class:`Intent` into :class:`Facts`. No model involved.

This is the only stage that produces numbers, and it produces them by
reading the same objects the rest of the platform reads --
``SensorDataProcessor`` for readings, statistics and thresholds,
``VentilationController`` for the fan. There is deliberately no second
copy of anything: the alarm thresholds argued from GB 37488-2019 stay in
``service.sensor_data_processor`` alone, exactly as they are kept out of
the firmware (see docs/03_Communication/Protocol_Design.md, ALERT_STATE).

Aggregation across devices matches ``VentilationController._worst_value``:
when several devices report the same channel, the highest value wins for
an "above maximum" rule. A single over-threshold sensor is the condition
that matters; averaging it away with compliant ones would hide it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from core.exceptions import NotFoundError
from core.models import ChannelId, DeviceId
from device.sensors.channels import (
    HUMIDITY_CHANNEL,
    NOISE_CHANNEL,
    TEMPERATURE_CHANNEL,
)
from service.assistant.export_status_port import ExportStatus
from service.assistant.models import Facts, Intent, IntentKind
from service.sensor_data_processor import (
    HUMIDITY_ALARM_MAX,
    HUMIDITY_ALARM_MIN,
    NOISE_ALARM_MAX,
    TEMPERATURE_ALARM_MAX,
    AlarmBand,
    AlarmKind,
    ChannelStatistics,
    SensorDataProcessor,
)
from service.ventilation_controller import VentilationController

CHANNEL_LABELS: dict[ChannelId, str] = {
    TEMPERATURE_CHANNEL: "温度",
    HUMIDITY_CHANNEL: "湿度",
    NOISE_CHANNEL: "噪声",
}

CHANNEL_CITATIONS: dict[ChannelId, str] = {
    NOISE_CHANNEL: "GB 37488—2019",
}
"""Where a channel's alarm threshold is argued from, when it is a
published standard. Temperature and humidity are engineering choices with
no citable source, so they have none -- and the template simply omits the
clause rather than inventing an authority."""

CHANNEL_UNITS: dict[ChannelId, str] = {
    TEMPERATURE_CHANNEL: "℃",
    HUMIDITY_CHANNEL: "%RH",
    NOISE_CHANNEL: "dB",
}

_ALARM_RULES: dict[ChannelId, AlarmBand] = {
    TEMPERATURE_CHANNEL: AlarmBand(maximum=TEMPERATURE_ALARM_MAX),
    HUMIDITY_CHANNEL: AlarmBand(
        minimum=HUMIDITY_ALARM_MIN, maximum=HUMIDITY_ALARM_MAX
    ),
    NOISE_CHANNEL: AlarmBand(maximum=NOISE_ALARM_MAX),
}
"""Mirrors ``sensor_data_processor``'s private rule table.

Read from that module's public threshold constants rather than
re-declaring the numbers, so the values cannot drift; only the
channel-to-rule mapping is restated, because the processor keeps its own
copy private.
"""

DeviceLister = Callable[[], Sequence[DeviceId]]


def _excursion(band: AlarmBand | None, value: float) -> float:
    """How far ``value`` sits outside ``band`` -- negative when inside.

    Ranks the readings of several devices so the worst one answers the
    question. With no band configured every reading ranks alike and the
    first device wins, which is what such channels did before.
    """
    if band is None:
        return 0.0
    distances = []
    if band.maximum is not None:
        distances.append(value - band.maximum)
    if band.minimum is not None:
        distances.append(band.minimum - value)
    return max(distances)


class FactRetriever:
    """Answers an :class:`Intent` with numbers read from the data layer."""

    def __init__(
        self,
        processor: SensorDataProcessor,
        devices: DeviceLister,
        ventilation: VentilationController | None = None,
        exports: ExportStatus | None = None,
    ) -> None:
        self._processor = processor
        self._devices = devices
        self._ventilation = ventilation
        self._exports = exports
        """待传时段的来源，由组合根注入（见 ``export_status_port``）。
        缺省 ``None``：没接台账时助手照常工作，只是答不出还有多少没传。"""

    def retrieve(self, intent: Intent) -> Facts:
        """Never raises: a question with no data yields ``available=False``."""
        if intent.kind is IntentKind.FAN_STATE:
            return self._fan_facts()
        if intent.kind is IntentKind.DEVICE_LIST:
            return self._device_facts()
        if intent.kind is IntentKind.HELP:
            return Facts(kind=IntentKind.HELP)
        if intent.kind is IntentKind.BARE_SWITCH:
            return Facts(kind=IntentKind.BARE_SWITCH)
        if intent.kind is IntentKind.ANNOUNCE_REQUEST:
            # Nothing to look up: the answer is a statement about what the
            # system does, and it carries no number by design.
            return Facts(kind=IntentKind.ANNOUNCE_REQUEST)
        if intent.kind is IntentKind.CLOUD_SYNC_HINT:
            return self._cloud_sync_facts()
        if intent.kind is IntentKind.CLOUD_VIEW_HINT:
            # 不查任何东西：云上有什么要连上 OSS 才知道，而那是按钮背后
            # 那个脚本的事。这里只负责说"可以去看"，不替它把话说满。
            return Facts(kind=IntentKind.CLOUD_VIEW_HINT)
        if intent.kind is IntentKind.DELETE_REQUEST:
            # Same shape, same reason. Deliberately does not look up how
            # many rows or files exist: a count would invite the reply
            # "delete those 8400 then", and the answer is no regardless.
            return Facts(kind=IntentKind.DELETE_REQUEST)
        if intent.channel is None:
            # A channel question with no channel identified -- a bare
            # "超标了吗". Answering for one arbitrary channel would be
            # misleading, and saying "no reading yet" would be answering a
            # question nobody asked. Both are worse than asking back.
            return Facts(kind=intent.kind, available=False, needs_channel=True)
        if intent.kind is IntentKind.THRESHOLD_INFO:
            return self._threshold_facts(intent.channel)
        return self._channel_facts(intent)

    # -- per-channel ------------------------------------------------------

    def _statistics(self, channel: ChannelId) -> ChannelStatistics | None:
        """Worst-case statistics for ``channel`` across every device.

        "Worst" follows the channel's own alarm band: the reading sitting
        furthest outside it, or -- when every device is inside -- the one
        closest to a bound. Picking by the band rather than always taking
        the maximum is what makes the humidity channel, which has a floor
        as well as a ceiling, answer sensibly.
        """
        band = _ALARM_RULES.get(channel)

        best: ChannelStatistics | None = None
        best_score = float("-inf")
        for device_id in self._devices():
            try:
                stats = self._processor.get_statistics(device_id, channel)
            except NotFoundError:
                continue
            score = _excursion(band, stats.current)
            if best is None or score > best_score:
                best, best_score = stats, score
        return best

    def _channel_facts(self, intent: Intent) -> Facts:
        channel = intent.channel
        assert channel is not None  # guarded by retrieve()
        stats = self._statistics(channel)
        base = self._threshold_facts(channel)

        if stats is None:
            return Facts(
                kind=intent.kind,
                available=False,
                channel=channel,
                channel_label=base.channel_label,
                unit=base.unit,
                threshold=base.threshold,
                citation=base.citation,
                threshold_is_maximum=base.threshold_is_maximum,
            )

        band = _ALARM_RULES.get(channel)
        triggered: bool | None = None
        margin: float | None = None
        threshold = base.threshold
        threshold_is_maximum = base.threshold_is_maximum
        if band is not None:
            # Evaluated against this reading rather than reusing the bound
            # _threshold_facts picked: for a two-sided band the side that
            # matters is the one the value is actually near, or over.
            kind, threshold, triggered = band.evaluate(stats.current)
            threshold_is_maximum = kind is AlarmKind.ABOVE_MAX
            margin = (
                threshold - stats.current
                if threshold_is_maximum
                else stats.current - threshold
            )

        return Facts(
            kind=intent.kind,
            channel=channel,
            channel_label=base.channel_label,
            unit=base.unit,
            value=stats.current,
            minimum=stats.minimum,
            maximum=stats.maximum,
            average=stats.average,
            sample_count=stats.sample_count,
            threshold=threshold,
            citation=base.citation,
            threshold_is_maximum=threshold_is_maximum,
            threshold_low=base.threshold_low,
            threshold_high=base.threshold_high,
            triggered=triggered,
            margin=margin,
            margin_requested=intent.wants_margin,
            past_scoped=intent.past_scoped,
        )

    def _threshold_facts(self, channel: ChannelId) -> Facts:
        """The channel's band, with no reading involved.

        ``threshold`` names the upper bound where there is one: a
        single-bound answer has to pick a side, and on every channel here
        the ceiling is the side an asker means. The whole band travels in
        ``threshold_low``/``threshold_high``.
        """
        band = _ALARM_RULES.get(channel)
        if band is None:
            return Facts(
                kind=IntentKind.THRESHOLD_INFO,
                available=False,
                channel=channel,
                channel_label=CHANNEL_LABELS.get(channel, str(channel)),
                unit=CHANNEL_UNITS.get(channel, ""),
                citation=CHANNEL_CITATIONS.get(channel, ""),
            )
        return Facts(
            kind=IntentKind.THRESHOLD_INFO,
            channel=channel,
            channel_label=CHANNEL_LABELS.get(channel, str(channel)),
            unit=CHANNEL_UNITS.get(channel, ""),
            threshold=band.maximum if band.maximum is not None else band.minimum,
            citation=CHANNEL_CITATIONS.get(channel, ""),
            threshold_is_maximum=band.maximum is not None,
            threshold_low=band.minimum,
            threshold_high=band.maximum,
        )

    # -- whole-system -----------------------------------------------------

    def _fan_facts(self) -> Facts:
        if self._ventilation is None:
            return Facts(kind=IntentKind.FAN_STATE, available=False)
        decision = self._ventilation.evaluate()
        settings = self._ventilation.settings
        readings: list[tuple[str, float, str]] = []
        for channel in (TEMPERATURE_CHANNEL, HUMIDITY_CHANNEL):
            stats = self._statistics(channel)
            if stats is not None:
                readings.append(
                    (
                        CHANNEL_LABELS[channel],
                        stats.current,
                        CHANNEL_UNITS[channel],
                    )
                )
        return Facts(
            kind=IntentKind.FAN_STATE,
            fan_running=decision.should_run,
            fan_reason=decision.reason,
            vent_temperature_max=settings.temperature_max,
            vent_humidity_max=settings.humidity_max,
            readings=tuple(readings),
            # ``.name``, not ``.value``: FanMode uses enum.auto(), so value
            # is an opaque int that would be meaningless downstream.
            fan_mode=decision.mode.name,
        )

    def _device_facts(self) -> Facts:
        return Facts(
            kind=IntentKind.DEVICE_LIST,
            device_ids=tuple(self._devices()),
        )

    def _cloud_sync_facts(self) -> Facts:
        """How many exported hours are still waiting to be uploaded.

        The only fact this kind needs, and the reason it is a fact rather
        than something the template counts for itself: the number ends up
        in the sentence, and anything in a sentence has to be in Facts or
        the grounding check rejects the model's rephrasing of it.

        With no ledger attached, ``pending_uploads`` stays ``None`` --
        "I cannot tell", which the template says plainly. It is not
        collapsed into 0, because 0 means "everything is up" and would
        offer the user a button with nothing behind it.
        """
        if self._exports is None:
            return Facts(kind=IntentKind.CLOUD_SYNC_HINT)
        try:
            pending = self._exports.pending_upload_count()
        except Exception:  # noqa: BLE001 -- 见下
            # The port's contract says implementations never raise, but a
            # question must not fail because a ledger file went missing:
            # answering "不知道还有多少" is always better than an error
            # dialog on top of a chat panel.
            return Facts(kind=IntentKind.CLOUD_SYNC_HINT)
        return Facts(kind=IntentKind.CLOUD_SYNC_HINT, pending_uploads=pending)
