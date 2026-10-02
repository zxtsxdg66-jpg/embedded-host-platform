"""Sentences that name something this system does not have.

Added 2026-09-26 after the external test bank (Home Assistant's Chinese
test sentences plus mixed sentences in the HomeBench style). Two failures
are pinned here: the rules reading the *other* device's verb as the fan's
("开风扇，顺便把灯关了" was taken as switching the fan off), and the
unsupported half never being mentioned at all.
"""

from device.sensors.channels import (
    HUMIDITY_CHANNEL,
    NOISE_CHANNEL,
    TEMPERATURE_CHANNEL,
)
from service.assistant import intent as rules
from service.assistant import phrasing
from service.assistant.assistant import Assistant
from service.assistant.models import AnswerSource, StepKind
from service.data_models import DataPoint
from service.sensor_data_processor import SensorDataProcessor
from service.ventilation_controller import FanMode, VentilationController


class _Llm:
    """Returns the next scripted reply for each submit and keeps the prompts."""

    def __init__(self, *replies: str) -> None:
        self._replies = list(replies)
        self._pending: list[str] = []
        self._busy = False
        self.prompts: list[str] = []

    def submit(self, prompt: str, system: str = "") -> bool:
        if self._busy:
            return False
        self.prompts.append(prompt)
        reply = self._replies.pop(0) if self._replies else ""
        self._pending = [reply] if reply else []
        self._busy = True
        return True

    def poll(self) -> str | None:
        if not self._busy:
            return None
        if self._pending:
            return self._pending.pop(0)
        self._busy = False
        return ""

    def is_busy(self) -> bool:
        return self._busy

    def cancel(self) -> None:
        self._busy = False
        self._pending = []


def _assistant(llm: object | None = None) -> tuple[Assistant, VentilationController]:
    processor = SensorDataProcessor()
    for channel, value in (
        (TEMPERATURE_CHANNEL, 26.6),
        (HUMIDITY_CHANNEL, 58.8),
        (NOISE_CHANNEL, 49.5),
    ):
        processor.handle_data_point(
            DataPoint(device_id="dev-1", channel=channel, value=value)
        )
    ventilation = VentilationController()
    assistant = Assistant(
        processor, lambda: ["dev-1"], ventilation=ventilation,
        llm=llm,  # type: ignore[arg-type]
    )
    return assistant, ventilation


def _late(assistant: Assistant) -> object | None:
    for _ in range(20):
        answer = assistant.poll_rephrasing()
        if answer is not None:
            return answer
    return None


# -- the registry ----------------------------------------------------------------


def test_absent_things_are_named() -> None:
    assert rules.absent_mentions("开风扇，顺便把灯关了") == ["灯"]
    assert rules.absent_mentions("甲醛超标吗") == ["甲醛"]
    assert rules.absent_mentions("现在温度多少") == []


def test_a_doorway_is_not_a_door() -> None:
    assert rules.absent_mentions("现在门口温度多少") == []
    assert rules.absent_mentions("所有门都锁着吗") == ["门和门锁"]


def test_screen_brightness_is_about_the_screen() -> None:
    assert rules.absent_mentions("把屏幕亮度调高") == ["屏幕"]


def test_only_the_segments_about_absent_things_are_dropped() -> None:
    assert rules.strip_absent("开风扇，顺便把灯关了") == "开风扇"
    assert rules.strip_absent("打开风扇并把音乐关掉") == "打开风扇"
    # One segment naming both keeps the verb with the fan.
    assert rules.strip_absent("把风扇和灯都关了") == "把风扇和灯都关了"
    assert rules.strip_absent("把灯关掉") == ""


# -- mixed sentences: the fan half is read on its own ----------------------------


def test_the_other_devices_verb_does_not_reach_the_fan() -> None:
    assistant, ventilation = _assistant()
    answer = assistant.ask("开风扇，顺便把灯关了")
    assert ventilation.settings.mode is FanMode.MANUAL_ON
    assert "灯" in answer.text


def test_an_air_conditioner_setting_is_not_a_threshold() -> None:
    assistant, ventilation = _assistant()
    before = ventilation.settings.temperature_max
    answer = assistant.ask("把风扇打开，再把空调调到24度")
    assert ventilation.settings.mode is FanMode.MANUAL_ON
    assert ventilation.settings.temperature_max == before
    assert "空调" in answer.text


def test_a_connective_inside_one_clause_splits_it() -> None:
    assistant, ventilation = _assistant()
    assistant.ask("打开风扇并把音乐关掉")
    assert ventilation.settings.mode is FanMode.MANUAL_ON


def test_a_threshold_next_to_a_window_is_still_set() -> None:
    assistant, ventilation = _assistant()
    answer = assistant.ask("通风温度阈值调到28度，另外把窗户关上")
    assert ventilation.settings.temperature_max == 28
    assert answer.text.startswith("这一半我做不了：系统里没有窗户")


def test_the_review_sees_only_the_fan_half_and_the_notice_survives() -> None:
    llm = _Llm("fan_on")
    assistant, ventilation = _assistant(llm)
    first = assistant.ask("开风扇，顺便把灯关了")
    assert first.source is AnswerSource.PENDING
    assert "灯" not in llm.prompts[0]
    late = _late(assistant)
    assert late is not None
    assert ventilation.settings.mode is FanMode.MANUAL_ON
    assert late.text.startswith("这一半我做不了：系统里没有灯")  # type: ignore[attr-defined]


# -- nothing left that the system can do -----------------------------------------


def test_an_absent_device_alone_gets_the_notice_and_no_model() -> None:
    llm = _Llm("fan_off")
    assistant, ventilation = _assistant(llm)
    answer = assistant.ask("把灯关掉")
    assert answer.source is AnswerSource.TEMPLATE
    assert answer.text == phrasing.absent_notice(["灯"], [], partial=False)
    assert llm.prompts == []
    assert ventilation.settings.mode is FanMode.AUTO


def test_an_absent_measurement_is_named_and_given_no_number() -> None:
    assistant, _ = _assistant()
    text = assistant.ask("甲醛超标吗").text
    assert "甲醛" in text and "26.6" not in text


def test_outdoor_temperature_is_not_answered_with_the_station_reading() -> None:
    assistant, _ = _assistant()
    text = assistant.ask("室外温度是多少").text
    assert "室外" in text and "26.6" not in text


def test_a_question_about_an_absent_device_gets_the_station_reading() -> None:
    assistant, _ = _assistant()
    text = assistant.ask("空调现在几度").text
    assert text.startswith("这个系统里没有空调，下面是站内的读数")
    assert "26.6" in text


def test_an_instruction_to_an_absent_device_is_not_answered_with_a_reading() -> None:
    assistant, _ = _assistant()
    text = assistant.ask("空调温度调到 26 度").text
    assert "26.6" not in text and "空调" in text


def test_the_step_log_records_what_was_left() -> None:
    assistant, _ = _assistant()
    assistant.ask("开风扇，顺便把灯关了")
    steps = [s for s in assistant.drain_steps() if s.kind is StepKind.ABSENT]
    assert len(steps) == 1
    assert steps[0].note == "灯" and steps[0].text == "开风扇"


# -- fan names and fan speed -----------------------------------------------------


def test_a_ceiling_fan_is_the_fan() -> None:
    assistant, ventilation = _assistant()
    assistant.ask("把吊扇打开")
    assert ventilation.settings.mode is FanMode.MANUAL_ON


def test_fan_speed_is_refused_rather_than_read_as_a_threshold() -> None:
    # "速度" ends in 度, which used to be taken as a temperature unit: this
    # sentence set the temperature threshold to 50.
    for sentence in ("风扇速度调到50", "吊扇速度调到50", "把风扇风速设置为百分之五十"):
        assistant, ventilation = _assistant()
        answer = assistant.ask(sentence)
        assert ventilation.settings.temperature_max != 50, sentence
        assert ventilation.settings.mode is FanMode.AUTO, sentence
        assert answer.text == phrasing.FAN_SPEED_TEXT, sentence


def test_ordinary_sentences_are_untouched() -> None:
    assistant, _ = _assistant()
    assert assistant.ask("现在门口温度多少").text == "温度现在是 26.6℃。"


def test_requests_to_devices_the_system_lacks_are_explained() -> None:
    # 2026-09-27: "声音" is a noise word, so this came back as a noise reading.
    for sentence, name in (
        ("站台的广播声音能调小吗", "站台广播"), ("把广播关了", "站台广播"),
        ("开门", "门和门锁"), ("关灯", "灯"),
    ):
        assistant, _ = _assistant()
        text = assistant.ask(sentence).text
        assert text.startswith(phrasing.REFUSAL_OPENER), sentence
        assert name in text and "49.5" not in text, sentence


def test_the_station_reading_is_for_questions_not_requests() -> None:
    assistant, _ = _assistant()
    assert "26.6" in assistant.ask("空调现在几度").text
    assistant, _ = _assistant()
    assert "26.6" not in assistant.ask("把空调温度调低一点").text
