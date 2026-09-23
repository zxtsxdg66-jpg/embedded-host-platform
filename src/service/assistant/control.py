"""Stage 2b: carry out an instruction, in place of looking something up.

A question and an instruction arrive through the same input box and are
classified by the same stage. From there they diverge: a question goes to
:mod:`service.assistant.retrieval`, and an instruction comes here.

What this module is allowed to do is deliberately tiny -- four actions, all
of them settings on :class:`service.ventilation_controller.VentilationController`:

===========================  =========================================
``FAN_ON`` / ``FAN_OFF``     force the fan on or off (a manual override)
``FAN_AUTO``                 hand control back to the thresholds
``SET_VENT_THRESHOLD``       move one ventilation threshold
===========================  =========================================

Three properties make that safe enough to trigger from a sentence:

**It changes policy, not hardware.** Nothing here builds a Command or
touches a serial port. It writes the same settings the ventilation panel
writes when a human clicks it, and the existing dispatcher turns the
resulting decision into a frame on its next poll -- including waiting for
control ownership if the application does not hold it. So a spoken
instruction cannot reach the device by a path a clicked one could not.

**The number never comes from the model.** For a threshold change the
value is read out of the user's own sentence by :func:`extract_value`. A
model asked to repeat "28" will usually repeat 28, and the one time it
says 38 the system would quietly start ventilating at the wrong point.
Reading the digits from the original text removes that possibility rather
than hoping; the model only ever says *which kind of instruction* this
was. This is the same rule as everywhere else in the assistant -- no
number originates in a model -- applied to input instead of output.

**Every action is reversible and visible.** The fan is the only actuator
involved, the panel shows the resulting state, and any of these can be
undone by saying the opposite. That is why a confirmation is not asked
for on every instruction: four reversible settings do not earn that much
friction. Anything wider -- arbitrary command dispatch, alarm thresholds,
device control ownership -- is deliberately *not* reachable from here, and
would need one.

2026-09-14 加了一道**有条件的**确认：规则与模型对同一句话的理解不一致时
（以及只有模型判成指令时），先反问一句再执行，见
``assistant.Assistant._finish_review``。它守的不是"这个动作危不危险"，
而是"这句话是不是真的在下命令"——前者由上面三条性质兜住，后者兜不住。
两边读法一致时仍然直接执行，没有多问一句。
"""

from __future__ import annotations

import re
from dataclasses import replace

from core.models import ChannelId
from device.sensors.channels import HUMIDITY_CHANNEL, TEMPERATURE_CHANNEL
from service.assistant.models import Facts, Intent, IntentKind
from service.ventilation_controller import FanMode, VentilationController

CONTROL_KINDS = frozenset(
    {
        IntentKind.FAN_ON,
        IntentKind.FAN_OFF,
        IntentKind.FAN_AUTO,
        IntentKind.SET_VENT_THRESHOLD,
    }
)
"""The whitelist, as a set rather than a convention.

Membership is what routes an intent here instead of to retrieval, so an
intent kind that nobody added to this set cannot act on anything -- which
is the desired default for a kind added later by someone reading only the
enum.
"""

_FAN_MODES: dict[IntentKind, FanMode] = {
    IntentKind.FAN_ON: FanMode.MANUAL_ON,
    IntentKind.FAN_OFF: FanMode.MANUAL_OFF,
    IntentKind.FAN_AUTO: FanMode.AUTO,
}

REJECT_NO_CONTROLLER = "no_controller"
REJECT_NO_VALUE = "no_value"
REJECT_NO_CHANNEL = "no_channel"
REJECT_OUT_OF_RANGE = "out_of_range"
"""Refusal codes. Rendered into sentences by the phrasing stage, which is
where all prose lives; see ``models.Facts.rejection``."""

VALUE_RANGES: dict[ChannelId, tuple[float, float]] = {
    TEMPERATURE_CHANNEL: (0.0, 50.0),
    HUMIDITY_CHANNEL: (0.0, 100.0),
}
"""Accepted ventilation thresholds per channel, matching the sensors'
measurement ranges. A threshold outside the range the
sensor can report is not a demanding setting, it is an unreachable one:
"通风阈值调到 300 度" would silently mean "never ventilate"."""

_VALUE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)")

_CHANNEL_UNITS: dict[ChannelId, str] = {
    TEMPERATURE_CHANNEL: "℃",
    HUMIDITY_CHANNEL: "%RH",
}

_CHANNEL_LABELS: dict[ChannelId, str] = {
    TEMPERATURE_CHANNEL: "温度",
    HUMIDITY_CHANNEL: "湿度",
}


def extract_value(question: str) -> float | None:
    """Read the number the user typed, or None if they typed none.

    Takes the **first** number in the sentence. With one number present
    (the ordinary case) that is the right one; with several -- "把温度
    阈值从 30 调到 28" -- it is the wrong one, so this deliberately does
    not try: the caller refuses instead of acting on a guess. Refusing is
    cheap here because the user is right there and can rephrase.
    """
    matches = _VALUE_PATTERN.findall(question)
    if len(matches) != 1:
        return None
    return float(matches[0])


class ControlExecutor:
    """Applies a control intent, and reports what happened as :class:`Facts`.

    Holds the same :class:`VentilationController` instance the rest of the
    application holds -- not a copy of its settings -- so an instruction
    given here and a click in the panel are the same write.
    """

    def __init__(self, ventilation: VentilationController | None = None) -> None:
        self._ventilation = ventilation

    def execute(self, intent: Intent, question: str) -> Facts:
        """Carry out ``intent``. Never raises; a refusal is a normal result.

        ``question`` is the user's original sentence, needed because a
        threshold's value is read from it rather than from anything the
        model produced.
        """
        if intent.kind not in CONTROL_KINDS:
            # Unreachable through the assistant, which routes on
            # CONTROL_KINDS -- but this class is the thing that must not be
            # talked into acting on something outside the whitelist.
            return self._refuse(intent, REJECT_NO_CONTROLLER)
        if self._ventilation is None:
            return self._refuse(intent, REJECT_NO_CONTROLLER)
        if intent.kind is IntentKind.SET_VENT_THRESHOLD:
            return self._set_threshold(intent, question)
        return self._set_mode(intent)

    # -- actions -----------------------------------------------------------

    def _set_mode(self, intent: Intent) -> Facts:
        assert self._ventilation is not None  # guarded by execute()
        self._ventilation.set_mode(_FAN_MODES[intent.kind])
        decision = self._ventilation.evaluate()
        return Facts(
            kind=intent.kind,
            applied=True,
            fan_running=decision.should_run,
            fan_reason=decision.reason,
            fan_mode=decision.mode.name,
        )

    def _set_threshold(self, intent: Intent, question: str) -> Facts:
        assert self._ventilation is not None  # guarded by execute()
        channel = intent.channel
        value = extract_value(question)
        if channel is None or channel not in VALUE_RANGES:
            # Missing the *object*, which is a question worth asking back.
            # Only when the value is already present, though: with both
            # halves missing there is nothing a one-word reply can complete,
            # and holding an instruction open to collect two answers is how
            # a stale reply ends up writing a setting nobody asked for.
            facts = self._refuse(intent, REJECT_NO_CHANNEL)
            if value is None:
                return facts
            return replace(facts, needs_channel=True, echo_question=question)

        if value is None:
            return self._refuse(intent, REJECT_NO_VALUE, channel)

        low, high = VALUE_RANGES[channel]
        if not low <= value <= high:
            return self._refuse(intent, REJECT_OUT_OF_RANGE, channel, value)

        if channel == TEMPERATURE_CHANNEL:
            self._ventilation.set_thresholds(temperature_max=value)
        else:
            self._ventilation.set_thresholds(humidity_max=value)

        decision = self._ventilation.evaluate()
        return Facts(
            kind=intent.kind,
            applied=True,
            channel=channel,
            channel_label=_CHANNEL_LABELS[channel],
            unit=_CHANNEL_UNITS[channel],
            threshold=value,
            fan_running=decision.should_run,
            fan_reason=decision.reason,
            fan_mode=decision.mode.name,
        )

    # -- refusals ----------------------------------------------------------

    def _refuse(
        self,
        intent: Intent,
        code: str,
        channel: ChannelId | None = None,
        value: float | None = None,
    ) -> Facts:
        """Build the Facts for an instruction that was not carried out.

        ``value`` is carried through for the out-of-range case so the
        answer can quote what was asked for -- and so it survives the
        grounding check, which would otherwise reject the very number the
        sentence is about.
        """
        return Facts(
            kind=intent.kind,
            applied=False,
            rejection=code,
            channel=channel,
            channel_label="" if channel is None else _CHANNEL_LABELS[channel],
            unit="" if channel is None else _CHANNEL_UNITS[channel],
            value=value,
        )


__all__ = [
    "CONTROL_KINDS",
    "REJECT_NO_CHANNEL",
    "REJECT_NO_CONTROLLER",
    "REJECT_NO_VALUE",
    "REJECT_OUT_OF_RANGE",
    "VALUE_RANGES",
    "ControlExecutor",
    "extract_value",
]
