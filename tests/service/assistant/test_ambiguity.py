"""Several channels in one sentence, the record count, and asking back.

Added 2026-09-26 (docs/decisions/03-intent.md). The failure
all of this exists to remove is the *silent partial answer*: "现在温度湿度
噪声是多少" came back as the temperature alone, every number correct and
two thirds of the question dropped without a word.
"""

from device.sensors.channels import (
    HUMIDITY_CHANNEL,
    NOISE_CHANNEL,
    TEMPERATURE_CHANNEL,
)
from service.assistant import intent as rules
from service.assistant import parsing, phrasing
from service.assistant.assistant import Assistant
from service.assistant.models import AnswerSource, Intent, IntentKind, StepKind
from service.data_models import DataPoint
from service.sensor_data_processor import SensorDataProcessor
from service.ventilation_controller import FanMode, VentilationController


class _Llm:
    """Returns the next scripted reply for each submit."""

    def __init__(self, *replies: str) -> None:
        self._replies = list(replies)
        self._pending: list[str] = []
        self._busy = False

    def submit(self, prompt: str, system: str = "") -> bool:
        if self._busy:
            return False
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
        for _ in range(3):
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


# -- ① several channels named in one clause --------------------------------------


def test_every_named_channel_is_answered() -> None:
    assistant, _ = _assistant()
    text = assistant.ask("现在温度湿度噪声是多少").text
    assert "26.6" in text and "58.8" in text and "49.5" in text


def test_the_question_kind_is_kept_for_each_channel() -> None:
    assistant, _ = _assistant()
    text = assistant.ask("温度湿度最高多少").text
    assert text.count("最高值") == 2


def test_an_elliptical_follow_up_naming_two_channels() -> None:
    assistant, _ = _assistant()
    text = assistant.ask("温度和湿度呢").text
    assert "温度" in text and "湿度" in text


def test_only_proper_channel_names_count() -> None:
    # 影响 contains 响 (a noise word); counting colloquial words would turn
    # this into three readings.
    assert rules.named_channels("湿度会影响温度吗") == [
        HUMIDITY_CHANNEL, TEMPERATURE_CHANNEL
    ]
    assert rules.named_channels("又热又闷又吵") == []


def test_the_abbreviation_wenshidu_names_both_channels() -> None:
    # 2026-09-29: "温湿度" holds only one whole channel word (湿度), so the
    # rules answered humidity alone while the model, asked on its own,
    # read temperature and humidity three times out of three.
    assert rules.named_channels("温湿度多少") == [
        TEMPERATURE_CHANNEL, HUMIDITY_CHANNEL
    ]
    assistant, _ = _assistant()
    text = assistant.ask("现在温湿度是多少").text
    assert "26.6" in text and "58.8" in text


def test_an_instruction_on_wenshidu_asks_which_channel() -> None:
    assistant, ventilation = _assistant()
    before = ventilation.settings
    answer = assistant.ask("温湿度通风阈值调到30度")
    assert "温度还是湿度" in answer.text
    assert ventilation.settings == before


def test_an_expanded_answer_is_not_sent_for_rewording() -> None:
    llm = _Llm("随便改写")
    assistant, _ = _assistant(llm)
    answer = assistant.ask("温度湿度现在多少")
    assert answer.source is AnswerSource.TEMPLATE
    assert StepKind.MODEL_SUBMIT not in [s.kind for s in assistant.drain_steps()]


def test_a_clause_naming_two_channels_inside_a_compound_sentence() -> None:
    assistant, _ = _assistant()
    text = assistant.ask("温度、湿度超标了吗，噪声呢").text
    assert text.count("一切正常") == 3


# -- ② all three -------------------------------------------------------------------


def test_asking_for_all_three_answers_all_three() -> None:
    assistant, _ = _assistant()
    text = assistant.ask("三个读数都说一下").text
    assert "温度" in text and "湿度" in text and "噪声" in text


def test_all_three_carries_the_previous_question_kind() -> None:
    assistant, _ = _assistant()
    assistant.ask("温度最高多少")
    text = assistant.ask("把三个都告诉我").text
    assert text.count("最高值") == 3


def test_all_does_not_override_a_sentence_that_names_its_channel() -> None:
    # 边界题库里的一句：这里的"都"说的是站点，不是通道。
    assistant, _ = _assistant()
    text = assistant.ask("所有站点的噪声都报一下").text
    assert "噪声" in text and "温度" not in text


def test_all_does_not_touch_the_device_list() -> None:
    assistant, _ = _assistant()
    answer = assistant.ask("有三个设备吗")
    assert answer.intent is not None
    assert answer.intent.kind is IntentKind.DEVICE_LIST


# -- instructions naming two channels ask instead of half-executing ------------


def test_an_instruction_naming_two_channels_asks_which() -> None:
    assistant, ventilation = _assistant()
    before = ventilation.settings
    answer = assistant.ask("温度和湿度通风阈值都调到30度")
    assert "温度还是湿度" in answer.text
    assert ventilation.settings == before
    assistant.ask("湿度")
    assert ventilation.settings.humidity_max == 30.0
    assert ventilation.settings.temperature_max == before.temperature_max


# -- ⑥ record count ------------------------------------------------------------


def test_record_count_without_a_channel_covers_all_three() -> None:
    assistant, _ = _assistant()
    answer = assistant.ask("现在记录了多少个数据")
    assert answer.text.count("记录了 3 个读数") == 3
    assert answer.intent is not None
    assert answer.intent.kind is IntentKind.SAMPLE_COUNT


def test_record_count_for_one_channel() -> None:
    assistant, _ = _assistant()
    assert rules.recognise("噪声记录了多少个点").kind is IntentKind.SAMPLE_COUNT
    text = assistant.ask("噪声记录了多少个点").text
    assert text == "噪声本次启动以来记录了 3 个读数。"


def test_record_count_is_grounded() -> None:
    assistant, _ = _assistant()
    answer = assistant.ask("噪声记录了多少个点")
    assert phrasing.numbers_are_grounded(answer.text, answer.facts)


# -- ③ the model naming several channels -----------------------------------------


def test_a_question_label_with_several_channels_is_kept() -> None:
    got = parsing.parse_candidates("current_value temperature humidity noise")
    assert [(g.kind, g.channel) for g in got] == [
        (IntentKind.CURRENT_VALUE, TEMPERATURE_CHANNEL),
        (IntentKind.CURRENT_VALUE, HUMIDITY_CHANNEL),
        (IntentKind.CURRENT_VALUE, NOISE_CHANNEL),
    ]


def test_an_instruction_label_with_several_channels_is_still_refused() -> None:
    assert parsing.parse_candidates("set_vent_threshold temperature humidity") == ()


def test_single_labels_parse_as_before() -> None:
    for reply in ("maximum noise", "fan_state", "unknown", "", "current_value"):
        single = parsing.parse_reply(reply)
        assert parsing.parse_candidates(reply) == (() if single is None else (single,))


def test_the_model_reading_all_three_answers_all_three() -> None:
    assistant, _ = _assistant(_Llm("current_value temperature humidity noise"))
    first = assistant.ask("现在环境怎么样")
    assert first.text == phrasing.THINKING_TEXT
    late = _late(assistant)
    assert late is not None
    text = late.text  # type: ignore[attr-defined]
    assert "26.6" in text and "58.8" in text and "49.5" in text
    assert text.startswith("我理解你问的是「温度、湿度、噪声的当前读数」")


# -- ④ the interpretation is stated --------------------------------------------


def test_a_model_classified_answer_says_how_it_was_understood() -> None:
    assistant, _ = _assistant(_Llm("device_list"))
    assistant.ask("地铁几点收班")
    late = _late(assistant)
    assert late is not None
    assert late.text.startswith("我理解你问的是「在线设备数量」：")  # type: ignore[attr-defined]
    assert late.source is AnswerSource.MODEL_INTENT  # type: ignore[attr-defined]


def test_the_model_can_now_name_the_record_count() -> None:
    assistant, _ = _assistant(_Llm("sample_count"))
    assistant.ask("这套系统攒了多少东西")
    late = _late(assistant)
    assert late is not None
    assert late.text.count("记录了 3 个读数") == 3  # type: ignore[attr-defined]


# -- ⑤ asking back when the model is unsure ----------------------------------------


def _asked(options: str) -> Assistant:
    assistant, _ = _assistant(_Llm(options))
    assistant.ask("那个数怎么样")
    late = _late(assistant)
    assert late is not None
    assert late.text.startswith("这句我拿不准")  # type: ignore[attr-defined]
    return assistant


def test_two_labels_become_a_question_with_two_options() -> None:
    assistant, _ = _assistant(_Llm("device_list sample_count"))
    assistant.ask("那个数怎么样")
    late = _late(assistant)
    assert late is not None
    assert late.text == (  # type: ignore[attr-defined]
        "这句我拿不准。你是想问「在线设备数量」，还是「记录了多少个读数」？回个序号就行。"
    )


def test_more_than_three_labels_is_still_a_menu_echo() -> None:
    reply = "current_value maximum minimum average"
    assert parsing.parse_candidates(reply) == ()


def test_answering_with_a_number_picks_that_option() -> None:
    assistant = _asked("device_list sample_count")
    text = assistant.ask("2").text
    assert text.count("记录了 3 个读数") == 3


def test_answering_with_an_ordinal_word() -> None:
    assistant = _asked("device_list sample_count")
    assert "设备在线" in assistant.ask("第一个").text


def test_answering_by_meaning_picks_the_matching_option() -> None:
    assistant = _asked("device_list sample_count")
    assert "设备在线" in assistant.ask("设备").text


def test_answering_both() -> None:
    assistant = _asked("maximum minimum temperature")
    text = assistant.ask("都要").text
    assert "最高值" in text and "最低值" in text


def test_declining_cancels_the_question() -> None:
    assistant = _asked("device_list sample_count")
    assert assistant.ask("都不是").text == phrasing.CHOICE_CANCELLED_TEXT


def test_a_new_question_drops_the_options() -> None:
    assistant = _asked("device_list sample_count")
    assert "湿度" in assistant.ask("现在湿度多少").text
    # the options are gone: a bare "2" no longer picks anything
    assert "记录了" not in assistant.ask("2").text


def test_picking_an_instruction_executes_it() -> None:
    assistant, ventilation = _assistant(_Llm("fan_state fan_on"))
    assistant.ask("风那边弄一下")
    assert _late(assistant) is not None
    assistant.ask("第二个")
    assert ventilation.settings.mode is FanMode.MANUAL_ON


def test_options_only_name_real_capabilities() -> None:
    every = [Intent(kind=k) for k in (
        IntentKind.CURRENT_VALUE, IntentKind.DEVICE_LIST, IntentKind.FAN_ON
    )]
    text = phrasing.choice_text(every)
    assert "当前读数" in text and "在线设备数量" in text and "手动常开" in text


def test_the_choice_is_recorded_as_a_step() -> None:
    assistant = _asked("device_list sample_count")
    assistant.drain_steps()
    assistant.ask("1")
    choice = next(s for s in assistant.drain_steps() if s.kind is StepKind.CHOICE)
    assert choice.note == "picked:1"


def test_a_channel_clarification_is_not_replaced_by_a_choice() -> None:
    # 规则已经反问过通道的，模型再拿不准也不叠一句不同的反问。
    assistant, _ = _assistant(_Llm("maximum minimum"))
    first = assistant.ask("最高是多少")
    assert "温度、湿度还是噪声" in first.text
    assert _late(assistant) is None


def test_choice_index_reads_short_replies_only() -> None:
    assert rules.choice_index("2") == 1
    assert rules.choice_index("选第一个吧") == 0
    assert rules.choice_index("后者") == 1
    assert rules.choice_index("一下温度多少") is None
    assert rules.choice_index("二氧化碳") is None


# -- a request-shaped second half (2026-09-27) ------------------------------------


def test_a_request_shaped_clause_is_answered_too() -> None:
    # "湿度也告诉我" carries no question marker; it used to be dropped as
    # filler and the temperature half went with the whole-sentence match.
    for sentence in (
        "现在是多少度 湿度也告诉我",
        "现在是多少度，湿度也告诉我",
        "现在是多少度湿度也告诉我",
    ):
        assistant, _ = _assistant()
        text = assistant.ask(sentence).text
        assert "26.6" in text and "58.8" in text, sentence


def test_how_many_degrees_names_the_temperature() -> None:
    assert rules.named_channels("现在是多少度湿度也告诉我") == [
        TEMPERATURE_CHANNEL, HUMIDITY_CHANNEL
    ]
    assert rules.named_channels("湿度多少") == [HUMIDITY_CHANNEL]
