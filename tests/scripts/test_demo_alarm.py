"""The alarm demo: thresholds lowered for a while, then put back.

The demo must not change any source file, must lower the threshold in both
places that know it (the alarm judgement and the assistant's facts, so the
screen and the answer agree), and must restore the originals exactly.
"""

from __future__ import annotations

from device.sensors.channels import HUMIDITY_CHANNEL, NOISE_CHANNEL, TEMPERATURE_CHANNEL
from scripts import demo_alarm
from service import sensor_data_processor as processor
from service.assistant import retrieval
from service.data_models import DataPoint
from service.sensor_data_processor import SensorDataProcessor


def _reading(value: float) -> DataPoint:
    return DataPoint(device_id="mcu-1", channel=TEMPERATURE_CHANNEL, value=value)


def test_arguments_split_into_the_demo_and_the_launcher() -> None:
    demo, launcher = demo_alarm.parse_args(
        ["--temperature-max", "20", "--for", "45",
         "--mode", "hardware", "--port-serial", "COM9"]
    )
    assert demo.temperature_max == 20.0 and demo.seconds == 45.0
    assert launcher == ["--mode", "hardware", "--port-serial", "COM9"]


def test_at_least_one_threshold_is_required() -> None:
    try:
        demo_alarm.parse_args(["--mode", "hardware", "--port-serial", "COM9"])
    except SystemExit:
        return
    raise AssertionError("expected the demo to refuse running with nothing lowered")


def test_both_copies_are_lowered_and_then_restored_exactly() -> None:
    before = (
        dict(processor._ALARM_RULES),
        dict(retrieval._ALARM_RULES),
    )
    restore = demo_alarm.lower_thresholds({TEMPERATURE_CHANNEL: 20.0})
    try:
        assert processor._ALARM_RULES[TEMPERATURE_CHANNEL].maximum == 20.0
        assert retrieval._ALARM_RULES[TEMPERATURE_CHANNEL].maximum == 20.0
        # Other channels are untouched.
        assert processor._ALARM_RULES[NOISE_CHANNEL] == before[0][NOISE_CHANNEL]
        assert processor._ALARM_RULES[HUMIDITY_CHANNEL] == before[0][HUMIDITY_CHANNEL]
    finally:
        restore()
    assert dict(processor._ALARM_RULES) == before[0]
    assert dict(retrieval._ALARM_RULES) == before[1]


def test_a_live_processor_raises_the_alarm_and_clears_it_on_restore() -> None:
    statuses = []
    live = SensorDataProcessor(confirm_cycles=1)
    live.on_status(statuses.append)

    live.handle_data_point(_reading(24.0))
    assert statuses[-1].triggered is False

    restore = demo_alarm.lower_thresholds({TEMPERATURE_CHANNEL: 20.0})
    try:
        live.handle_data_point(_reading(24.0))
        assert statuses[-1].triggered is True
    finally:
        restore()
    live.handle_data_point(_reading(24.0))
    assert statuses[-1].triggered is False
