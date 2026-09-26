"""Tests for gateway.events -- pure serialization, no server needed.

Verifies the wire messages carry exactly the fields taken from the
existing PC-side types (DataPoint / ThresholdStatus / ChannelStatistics),
plus the additive ``unit`` field.
"""

from __future__ import annotations

from datetime import datetime, timezone

from gateway.events import (
    MESSAGE_TYPE_ALARM_STATUS,
    MESSAGE_TYPE_DATA,
    MESSAGE_TYPE_STATISTICS,
    alarm_status_message,
    data_point_message,
    statistics_message,
)
from service.data_models import DataPoint
from service.sensor_data_processor import (
    AlarmKind,
    ChannelStatistics,
    ThresholdStatus,
)


def test_data_point_message_carries_datapoint_fields() -> None:
    point = DataPoint(
        device_id="mcu-1",
        channel="temperature",
        value=23.5,
        timestamp=datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc),
        valid=True,
    )

    message = data_point_message(point)

    assert message["type"] == MESSAGE_TYPE_DATA
    assert message["device_id"] == "mcu-1"
    assert message["channel"] == "temperature"
    assert message["value"] == 23.5
    assert message["valid"] is True
    assert message["timestamp"].startswith("2026-08-14T10:00:00")


def test_data_point_message_attaches_unit_for_known_channels() -> None:
    for channel, expected_unit in (
        ("temperature", "°C"),
        ("humidity", "%"),
        ("noise", "dB"),
    ):
        point = DataPoint(device_id="mcu-1", channel=channel, value=1.0)
        assert data_point_message(point)["unit"] == expected_unit


def test_data_point_message_unit_is_empty_for_unknown_channel() -> None:
    """Unknown channels must not raise -- the platform stays channel-agnostic."""
    point = DataPoint(device_id="mcu-1", channel="pressure", value=1.0)

    assert data_point_message(point)["unit"] == ""


def test_alarm_status_message_sends_kind_as_stable_string() -> None:
    status = ThresholdStatus(
        device_id="mcu-1",
        channel="noise",
        value=85.2,
        threshold=80.0,
        kind=AlarmKind.ABOVE_MAX,
        triggered=True,
    )

    message = alarm_status_message(status)

    assert message["type"] == MESSAGE_TYPE_ALARM_STATUS
    assert message["kind"] == "ABOVE_MAX"  # not a Python enum repr
    assert message["triggered"] is True
    assert message["threshold"] == 80.0
    assert message["unit"] == "dB"


def test_alarm_status_message_reports_recovery() -> None:
    """triggered=False must survive serialization -- it is how a client
    learns a channel returned to normal."""
    status = ThresholdStatus(
        device_id="mcu-1",
        channel="noise",
        value=45.0,
        threshold=80.0,
        kind=AlarmKind.ABOVE_MAX,
        triggered=False,
    )

    assert alarm_status_message(status)["triggered"] is False


def test_statistics_message_carries_all_snapshot_fields() -> None:
    stats = ChannelStatistics(
        current=23.5, minimum=20.1, maximum=25.3, average=22.7, sample_count=128
    )

    message = statistics_message("mcu-1", "temperature", stats)

    assert message["type"] == MESSAGE_TYPE_STATISTICS
    assert message["device_id"] == "mcu-1"
    assert message["channel"] == "temperature"
    assert message["current"] == 23.5
    assert message["minimum"] == 20.1
    assert message["maximum"] == 25.3
    assert message["average"] == 22.7
    assert message["sample_count"] == 128
    assert message["unit"] == "°C"


def test_assistant_step_message_serialises_every_field() -> None:
    from gateway.events import assistant_step_message
    from service.assistant.models import (
        AnswerSource,
        AnswerStep,
        CheckResult,
        CheckVerdict,
        Intent,
        IntentKind,
        StepKind,
    )

    step = AnswerStep(
        question_id=3,
        seq=7,
        at_ms=3410,
        kind=StepKind.CHECKS,
        text="温度 27.1℃，请注意保暖。",
        job="rephrase",
        intent=Intent(kind=IntentKind.CURRENT_VALUE, channel="temperature"),
        source=AnswerSource.TEMPLATE,
        checks=(
            CheckResult("grounding", False, "27.1"),
            CheckResult("advice", False, "请注意"),
        ),
        verdict=CheckVerdict.UNGROUNDED_NUMBER,
    )
    message = assistant_step_message(step)
    assert message["type"] == "assistant_step"
    assert (message["question_id"], message["seq"], message["at_ms"]) == (3, 7, 3410)
    assert message["kind"] == "checks"
    assert message["intent"] == {"kind": "CURRENT_VALUE", "channel": "temperature"}
    assert message["source"] == "template"
    assert message["verdict"] == "ungrounded_number"
    assert message["checks"][0] == {
        "name": "grounding", "passed": False, "detail": "27.1"
    }
    assert message["facts"] is None
    assert message["final"] is False
