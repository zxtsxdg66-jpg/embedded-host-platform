"""AnswerDispatcher: puts the last answer on the board's second page.

Mirrors :mod:`application.alarm_state_dispatcher` in shape -- record in
the callback, send from the poll loop -- and differs from it in one
decision worth stating up front.

**The board is not sent text.** Its font is a 34-glyph subset generated
from the literals in ``ui_screen.c`` (a full GBK table would need external
SPI Flash, whose bus occupies the JTAG pins), so an arbitrary Chinese
sentence cannot be drawn at all. What travels instead is *which kind of
answer* plus its numbers, and the board renders from its own templates.

Three things follow from that, all of them wanted:

- The wire payload is small and needs no encoding negotiation.
- A model rephrasing cannot change what the screen shows. The screen
  displays facts, which is the same split the whole assistant is built
  on -- the model owns wording, the system owns numbers.
- The board only ever shows answers the platform has a template for.
  Anything else is simply not sent, so the screen cannot display a
  sentence the system would not stand behind.

Answers from the desktop and from a phone are treated identically and
tagged with where they came from: the board is a fixed display in a
public space, not anyone's private conversation, and "who asked" is worth
one byte for the same reason the desktop activity log records it.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import IntEnum

from core.models import ClientId, DeviceId
from device.sensors.channels import HUMIDITY_CHANNEL, NOISE_CHANNEL, TEMPERATURE_CHANNEL
from service.assistant.models import Answer, Facts, IntentKind
from service.command_models import Command, CommandStatus, CommandType
from service.control_service import ControlService

ANSWER_SHOW_COMMAND: CommandType = "ANSWER_SHOW"
DEFAULT_ANSWER_CLIENT_ID: ClientId = "answer-dispatcher"


class AnswerKind(IntEnum):
    """What the board should draw. Pinned values: the firmware switches on
    these, so they are a wire contract and may never be renumbered."""

    CURRENT = 1
    MAXIMUM = 2
    MINIMUM = 3
    AVERAGE = 4
    ALARM = 5
    THRESHOLD = 6
    FAN = 7


class AnswerChannel(IntEnum):
    """Channel column of the payload. ``NONE`` is for whole-system answers
    (the fan), which belong to no channel."""

    TEMPERATURE = 0
    HUMIDITY = 1
    NOISE = 2
    NONE = 255


_KINDS: dict[IntentKind, AnswerKind] = {
    IntentKind.CURRENT_VALUE: AnswerKind.CURRENT,
    IntentKind.MAXIMUM: AnswerKind.MAXIMUM,
    IntentKind.MINIMUM: AnswerKind.MINIMUM,
    IntentKind.AVERAGE: AnswerKind.AVERAGE,
    IntentKind.ALARM_STATE: AnswerKind.ALARM,
    IntentKind.THRESHOLD_INFO: AnswerKind.THRESHOLD,
    IntentKind.FAN_STATE: AnswerKind.FAN,
}
"""Answers the board has a template for.

Everything absent here is simply not displayed: the help text, a question
the rules could not place, a clarification, and every instruction. The
last one is deliberate -- an instruction's outcome is already visible on
the screen as the fan row and the alarm bitmap, and echoing "已把风扇打开"
would put a stale sentence beside a live indicator.
"""

_CHANNELS = {
    TEMPERATURE_CHANNEL: AnswerChannel.TEMPERATURE,
    HUMIDITY_CHANNEL: AnswerChannel.HUMIDITY,
    NOISE_CHANNEL: AnswerChannel.NOISE,
}

KIND_PARAMETER = "kind"
CHANNEL_PARAMETER = "channel"
VALUE_PARAMETER = "value"
LIMIT_PARAMETER = "limit"
FLAGS_PARAMETER = "flags"
SOURCE_PARAMETER = "source"

SCALE = 10
"""Fixed-point factor for the two numeric fields.

The firmware reads payload integers with a small key scan
(``protocol_payload_get_uint``) and has no float parser, so 24.7 travels
as 247 and the board divides. One decimal is what the desktop metric
cards show, so the two ends read alike.
"""

FLAG_TRIGGERED = 0x01
FLAG_FAN_RUNNING = 0x02
FLAG_FAN_AUTO = 0x04
FLAG_LIMIT_IS_MAXIMUM = 0x08

SOURCE_LOCAL = 0
SOURCE_REMOTE = 1


def _scaled(value: float | None) -> int | None:
    """``value`` as a fixed-point integer, or None if it cannot travel.

    Negative readings are refused rather than wrapped: the payload field
    is unsigned on the firmware side, and a temperature below zero would
    arrive as a large positive number -- a wrong reading displayed with
    full confidence, which is the one outcome this whole design exists to
    prevent. The board keeps its previous page instead.
    """
    if value is None:
        return None
    scaled = round(value * SCALE)
    if scaled < 0:
        return None
    return int(scaled)


def _displayed_value(facts: Facts, kind: AnswerKind) -> float | None:
    """Which of the statistics this answer kind is about."""
    if kind is AnswerKind.MAXIMUM:
        return facts.maximum
    if kind is AnswerKind.MINIMUM:
        return facts.minimum
    if kind is AnswerKind.AVERAGE:
        return facts.average
    if kind is AnswerKind.THRESHOLD:
        return facts.threshold
    return facts.value


def payload_for(answer: Answer, remote: bool = False) -> dict[str, int] | None:
    """The board payload for ``answer``, or None if it is not displayable.

    None is the normal outcome for most answers -- see :data:`_KINDS`.
    """
    facts = answer.facts
    if facts is None or not facts.available:
        return None
    kind = _KINDS.get(facts.kind)
    if kind is None:
        return None
    if facts.applied is not None:
        # An instruction, not a question.
        return None

    flags = 0
    if facts.triggered:
        flags |= FLAG_TRIGGERED
    if facts.threshold_is_maximum:
        flags |= FLAG_LIMIT_IS_MAXIMUM

    value: int | None
    if kind is AnswerKind.FAN:
        if facts.fan_running is None:
            return None
        if facts.fan_running:
            flags |= FLAG_FAN_RUNNING
        if facts.fan_mode == "AUTO":
            flags |= FLAG_FAN_AUTO
        value = 0
        limit = 0
        channel = AnswerChannel.NONE
    else:
        channel_code = _CHANNELS.get(facts.channel) if facts.channel else None
        if channel_code is None:
            return None
        channel = channel_code
        value = _scaled(_displayed_value(facts, kind))
        if value is None:
            return None
        limit = _scaled(facts.threshold) or 0

    return {
        KIND_PARAMETER: int(kind),
        CHANNEL_PARAMETER: int(channel),
        VALUE_PARAMETER: value,
        LIMIT_PARAMETER: limit,
        FLAGS_PARAMETER: flags,
        SOURCE_PARAMETER: SOURCE_REMOTE if remote else SOURCE_LOCAL,
    }


class AnswerDispatcher:
    """Shows the last displayable answer on one device's second page."""

    def __init__(
        self,
        control_service: ControlService,
        device_id: DeviceId,
        client_id: ClientId = DEFAULT_ANSWER_CLIENT_ID,
        command_type: CommandType = ANSWER_SHOW_COMMAND,
    ) -> None:
        self._control_service = control_service
        self._device_id = device_id
        self._client_id = client_id
        self._command_type = command_type
        self._pending: dict[str, int] | None = None
        self._applied: dict[str, int] | None = None
        self.dispatch_count = 0
        self.deferred_count = 0
        self.failure_count = 0
        self.last_error: Exception | None = None

    @property
    def device_id(self) -> DeviceId:
        return self._device_id

    @property
    def pending(self) -> dict[str, int] | None:
        """Payload the platform wants displayed, sent or not."""
        return self._pending

    @property
    def applied(self) -> dict[str, int] | None:
        """Payload currently believed to be on the screen."""
        return self._applied

    def record(self, answer: Answer, remote: bool | None = None) -> None:
        """Note an answer. Sends nothing.

        Called from wherever an answer is produced -- which for a late
        model result is inside the poll loop's own callback. Sending from
        there would re-enter the serial port mid-cycle, the re-entrancy
        rule this codebase settled on after the fan dispatcher hit it:
        record here, send in :meth:`dispatch_pending`.

        ``remote`` says who asked. ``None`` means "the same end as last
        time", which is what a late model result needs: the assistant does
        not track who asked, and a rephrasing belongs to whoever the
        question did. A wrong tag here would be a small lie on a public
        screen, so inheriting beats guessing.
        """
        if remote is None:
            previous = self._pending
            remote = (
                previous is not None
                and previous[SOURCE_PARAMETER] == SOURCE_REMOTE
            )
        payload = payload_for(answer, remote=remote)
        if payload is None:
            # Not displayable. The previous page stays -- a screen that
            # blanked whenever someone asked "你能干什么" would be worse
            # than one showing a slightly old answer.
            return
        self._pending = payload

    def dispatch_pending(self) -> None:
        """Send the pending payload if it differs from what is displayed.

        Never raises: a screen update is not worth taking the poll loop
        down for.
        """
        if self._pending is None or self._pending == self._applied:
            return
        desired = self._pending
        if not self._control_service.acquire(self._device_id, self._client_id):
            # A human client holds the device; the screen can wait a cycle.
            self.deferred_count += 1
            return
        try:
            result = self._control_service.submit_command(
                Command(
                    device_id=self._device_id,
                    command_type=self._command_type,
                    origin=self._client_id,
                    parameters=dict(desired),
                )
            )
        except Exception as exc:  # noqa: BLE001 -- see module docstring
            self.failure_count += 1
            self.last_error = exc
            return
        finally:
            self._control_service.release(self._device_id, self._client_id)

        self.dispatch_count += 1
        if result.status is CommandStatus.SUCCESS:
            self._applied = desired
        else:
            # Leaves _applied alone so the next cycle retries.
            self.failure_count += 1


AnswerObserver = Callable[[Answer], None]
