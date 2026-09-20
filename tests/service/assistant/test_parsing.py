"""What a model is allowed to say, and what happens when it says something else.

The parsing stage is the one place a model's output steers the system, so
these tests are mostly about *refusing* it. The rule they encode: an
ambiguous or malformed reply is worth nothing, because the fallback --
the help text already on screen -- costs nothing.
"""

from device.sensors.channels import (
    HUMIDITY_CHANNEL,
    NOISE_CHANNEL,
    TEMPERATURE_CHANNEL,
)
from service.assistant.models import IntentKind
from service.assistant.parsing import (
    MODEL_INTENT_CONFIDENCE,
    build_prompt,
    parse_reply,
)


def test_a_clean_reply_becomes_an_intent() -> None:
    intent = parse_reply("current_value temperature")

    assert intent is not None
    assert intent.kind is IntentKind.CURRENT_VALUE
    assert intent.channel == TEMPERATURE_CHANNEL


def test_formatting_around_the_label_is_irrelevant() -> None:
    """Scanning for tokens rather than parsing a format is what makes a
    4B model's output usable: markdown, quotes and a trailing sentence all
    carry the same answer."""
    replies = (
        "```\nmaximum noise\n```",
        '"maximum" "noise"',
        "标签：maximum，通道：noise。",
        "MAXIMUM NOISE",
    )
    for reply in replies:
        intent = parse_reply(reply)
        assert intent is not None, reply
        assert intent.kind is IntentKind.MAXIMUM
        assert intent.channel == NOISE_CHANNEL


def test_a_model_derived_intent_records_lower_confidence() -> None:
    """Provenance that cannot be reconstructed afterwards: a rule match
    scores 1.0, this does not."""
    intent = parse_reply("average humidity")

    assert intent is not None
    assert intent.channel == HUMIDITY_CHANNEL
    assert intent.confidence == MODEL_INTENT_CONFIDENCE
    assert intent.confidence < 1.0


def test_declining_is_respected() -> None:
    assert parse_reply("unknown") is None
    assert parse_reply("") is None
    assert parse_reply("   \n ") is None


def test_a_hedged_reply_is_rejected_rather_than_resolved() -> None:
    """The failure this exists for: a model that lists the menu instead of
    choosing from it. Taking whichever label appears first would answer a
    question nobody asked."""
    assert parse_reply("可能是 current_value 或者 maximum") is None
    assert parse_reply("current_value / average / minimum") is None


def test_a_hedge_between_a_label_and_unknown_is_rejected() -> None:
    assert parse_reply("current_value temperature 也可能是 unknown") is None


def test_two_channels_are_as_bad_as_none() -> None:
    """Picking either would be a coin toss, and the two answers differ."""
    assert parse_reply("current_value temperature humidity") is None


def test_a_channel_question_without_a_channel_is_rejected() -> None:
    """Retrieval refuses to guess a channel, so accepting this would swap
    the help text for a worse message -- "没有可用的数据" for a question the
    system never understood."""
    for label in ("current_value", "maximum", "alarm_state", "threshold_info"):
        assert parse_reply(label) is None, label


def test_whole_system_questions_need_no_channel() -> None:
    for label, kind in (
        ("fan_state", IntentKind.FAN_STATE),
        ("device_list", IntentKind.DEVICE_LIST),
    ):
        intent = parse_reply(label)
        assert intent is not None, label
        assert intent.kind is kind
        assert intent.channel is None


def test_the_prompt_is_the_question_and_nothing_else() -> None:
    """Nothing about the system's state is sent -- there is no reading,
    threshold or device in the request the model sees."""
    assert build_prompt("  现在温度多少  ") == "现在温度多少"
    assert build_prompt("   ") == ""
