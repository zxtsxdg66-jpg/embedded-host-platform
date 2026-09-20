"""Tests for application.answer_dispatcher.

What matters here is mostly what does *not* get sent. The board draws
from its own templates, so anything the platform hands it will be
rendered with full confidence -- which makes "refuse to send" the safe
behaviour and the one worth pinning down.
"""

from __future__ import annotations

from application.answer_dispatcher import (
    FLAG_FAN_AUTO,
    FLAG_FAN_RUNNING,
    FLAG_LIMIT_IS_MAXIMUM,
    FLAG_TRIGGERED,
    SOURCE_LOCAL,
    SOURCE_REMOTE,
    AnswerChannel,
    AnswerDispatcher,
    AnswerKind,
    payload_for,
)
from application.runtime import ApplicationRuntime
from communication.loopback import LoopbackChannel
from device.sensors.channels import NOISE_CHANNEL, TEMPERATURE_CHANNEL
from device.simulator import ConstantValueGenerator, SimulatedChannel, SimulatorDevice
from service.assistant.models import Answer, AnswerSource, Facts, Intent, IntentKind

DEVICE_ID = "sim-1"


def _answer(facts: Facts) -> Answer:
    return Answer(
        text="",
        source=AnswerSource.TEMPLATE,
        intent=Intent(kind=facts.kind, channel=facts.channel),
        facts=facts,
    )


def _reading(**overrides: object) -> Facts:
    fields: dict[str, object] = {
        "kind": IntentKind.CURRENT_VALUE,
        "channel": TEMPERATURE_CHANNEL,
        "unit": "℃",
        "value": 24.7,
        "threshold": 35.0,
        "triggered": False,
    }
    fields.update(overrides)
    return Facts(**fields)  # type: ignore[arg-type]


# -- what travels -------------------------------------------------------------


def test_a_reading_travels_as_fixed_point() -> None:
    """There is no float parser on the board: 24.7 goes as 247."""
    payload = payload_for(_answer(_reading()))

    assert payload is not None
    assert payload["kind"] == AnswerKind.CURRENT
    assert payload["channel"] == AnswerChannel.TEMPERATURE
    assert payload["value"] == 247
    assert payload["limit"] == 350


def test_each_statistic_sends_its_own_number() -> None:
    """The kind tells the board which sentence to draw; the value must be
    the number that sentence is about, not always the current reading."""
    facts = _reading(
        kind=IntentKind.MAXIMUM, maximum=31.2, minimum=18.0, average=22.5
    )

    payload = payload_for(_answer(facts))

    assert payload is not None
    assert payload["value"] == 312


def test_an_alarm_state_sets_its_flag() -> None:
    facts = _reading(kind=IntentKind.ALARM_STATE, value=38.4, triggered=True)

    payload = payload_for(_answer(facts))

    assert payload is not None
    assert payload["flags"] & FLAG_TRIGGERED
    assert payload["flags"] & FLAG_LIMIT_IS_MAXIMUM


def test_the_fan_answer_carries_flags_instead_of_a_channel() -> None:
    facts = Facts(kind=IntentKind.FAN_STATE, fan_running=True, fan_mode="AUTO")

    payload = payload_for(_answer(facts))

    assert payload is not None
    assert payload["channel"] == AnswerChannel.NONE
    assert payload["flags"] & FLAG_FAN_RUNNING
    assert payload["flags"] & FLAG_FAN_AUTO


def test_who_asked_travels_with_the_answer() -> None:
    """The board is a fixed display in a public space, so both ends are
    shown -- but a viewer should be able to tell which one asked."""
    local = payload_for(_answer(_reading()))
    remote = payload_for(_answer(_reading()), remote=True)

    assert local is not None and remote is not None
    assert local["source"] == SOURCE_LOCAL
    assert remote["source"] == SOURCE_REMOTE


# -- what does not travel -----------------------------------------------------


def test_the_help_text_is_never_displayed() -> None:
    """It is a menu of what can be asked -- useful in a chat box, useless
    on a wall display, and the board has no template for it."""
    assert payload_for(_answer(Facts(kind=IntentKind.HELP))) is None


def test_an_unanswerable_question_is_not_displayed() -> None:
    facts = _reading(available=False)

    assert payload_for(_answer(facts)) is None


def test_a_clarification_is_not_displayed() -> None:
    """"你问的是温度、湿度还是噪声" is addressed to whoever typed it.
    Nobody at the board can answer it."""
    facts = Facts(kind=IntentKind.ALARM_STATE, available=False, needs_channel=True)

    assert payload_for(_answer(facts)) is None


def test_an_instruction_is_not_displayed() -> None:
    """Its outcome is already on the screen as the fan row and the alarm
    bitmap; a sentence beside a live indicator only goes stale."""
    facts = Facts(kind=IntentKind.FAN_ON, applied=True, fan_running=True)

    assert payload_for(_answer(facts)) is None


def test_a_negative_reading_is_refused_rather_than_wrapped() -> None:
    """The field is unsigned on the firmware side. -2.0 ℃ would arrive as
    a large positive number and be drawn with full confidence."""
    facts = _reading(value=-2.0)

    assert payload_for(_answer(facts)) is None


# -- dispatching --------------------------------------------------------------


def _runtime() -> ApplicationRuntime:
    runtime = ApplicationRuntime()
    device = SimulatorDevice(
        device_id=DEVICE_ID,
        channels=[
            SimulatedChannel(
                channel_id=TEMPERATURE_CHANNEL, generator=ConstantValueGenerator(21.0)
            )
        ],
    )
    runtime.register_device(
        device, LoopbackChannel(), accepted_commands=("ANSWER_SHOW",)
    )
    return runtime


def test_recording_sends_nothing_until_the_poll_loop_runs() -> None:
    """A late model answer is recorded from inside the poll loop's own
    callback. Sending there would re-enter the serial port mid-cycle --
    the rule this codebase settled on after the fan dispatcher hit it."""
    runtime = _runtime()
    dispatcher = AnswerDispatcher(runtime.control_service, DEVICE_ID)

    dispatcher.record(_answer(_reading()))

    assert dispatcher.pending is not None
    assert dispatcher.applied is None
    assert dispatcher.dispatch_count == 0


def test_dispatching_sends_the_recorded_answer() -> None:
    runtime = _runtime()
    dispatcher = AnswerDispatcher(runtime.control_service, DEVICE_ID)

    dispatcher.record(_answer(_reading()))
    dispatcher.dispatch_pending()

    assert dispatcher.dispatch_count == 1
    assert dispatcher.applied == dispatcher.pending


def test_the_same_answer_is_not_sent_twice() -> None:
    """Asking the same question again should not spend a frame redrawing
    a screen that already says it."""
    runtime = _runtime()
    dispatcher = AnswerDispatcher(runtime.control_service, DEVICE_ID)

    dispatcher.record(_answer(_reading()))
    dispatcher.dispatch_pending()
    dispatcher.record(_answer(_reading()))
    dispatcher.dispatch_pending()

    assert dispatcher.dispatch_count == 1


def test_an_undisplayable_answer_leaves_the_previous_page_alone() -> None:
    """A screen that blanked whenever someone asked "你能干什么" would be
    worse than one showing a slightly older answer."""
    runtime = _runtime()
    dispatcher = AnswerDispatcher(runtime.control_service, DEVICE_ID)

    dispatcher.record(_answer(_reading()))
    dispatcher.dispatch_pending()
    dispatcher.record(_answer(Facts(kind=IntentKind.HELP)))

    assert dispatcher.pending is not None
    assert dispatcher.pending["kind"] == AnswerKind.CURRENT


def test_a_device_held_by_someone_else_defers_rather_than_fails() -> None:
    """A human client holding the device is normal, not an error. The
    screen waits a cycle."""
    runtime = _runtime()
    dispatcher = AnswerDispatcher(runtime.control_service, DEVICE_ID)
    runtime.control_service.acquire(DEVICE_ID, "a-person")

    dispatcher.record(_answer(_reading(channel=NOISE_CHANNEL, unit="dB")))
    dispatcher.dispatch_pending()

    assert dispatcher.deferred_count == 1
    assert dispatcher.dispatch_count == 0
