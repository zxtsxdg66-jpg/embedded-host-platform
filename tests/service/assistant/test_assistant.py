"""The facade, and the guarantee it exists to enforce.

The tests that matter most here are the ones proving a model can never
put a number in front of a user: it is never given the readings, and
anything it returns is checked against the facts before being shown.
"""

from device.sensors.channels import (
    HUMIDITY_CHANNEL,
    NOISE_CHANNEL,
    TEMPERATURE_CHANNEL,
)
from service.assistant import phrasing
from service.assistant.assistant import (
    CHANNEL_MEMORY_SECONDS,
    CLARIFY_SECONDS,
    EXPLAIN_SYSTEM_PROMPT,
    REPHRASE_RETRY_SYSTEM_PROMPT,
    REPHRASE_SYSTEM_PROMPT,
    Assistant,
)
from service.assistant.llm_port import NullLlmClient
from service.assistant.models import Answer, AnswerSource, IntentKind
from service.assistant.parsing import PARSE_SYSTEM_PROMPT
from service.data_models import DataPoint
from service.sensor_data_processor import SensorDataProcessor
from service.ventilation_controller import FanMode, VentilationController


class _ScriptedLlm:
    """A model client that streams ``reply`` back in ``chunks`` pieces.

    Modelled on how a real streaming client behaves rather than on the
    simplest thing that passes: it stays busy until every chunk has been
    handed over, which is what caught the facade keeping only the final
    fragment instead of accumulating.
    """

    def __init__(
        self, reply: str | None, chunks: int = 1, then: str | None = None
    ) -> None:
        self._reply = reply
        self._then = then
        """第二次 submit 时改用这份回复，用来演练"被退回后重写一次"。"""
        self._chunk_count = max(1, chunks)
        self._pending: list[str] = []
        self._busy = False
        self.prompts: list[str] = []
        self.systems: list[str] = []
        self.submit_count = 0

    def _split(self) -> list[str]:
        if not self._reply:
            return []
        size = max(1, len(self._reply) // self._chunk_count + 1)
        return [
            self._reply[i : i + size] for i in range(0, len(self._reply), size)
        ]

    def submit(self, prompt: str, system: str = "") -> bool:
        if self._busy:
            return False
        if self.submit_count >= 1 and self._then is not None:
            self._reply = self._then
        self.prompts.append(prompt)
        self.systems.append(system)
        self.submit_count += 1
        self._pending = self._split()
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


def _drain(assistant: Assistant, limit: int = 10) -> object | None:
    """Poll until the assistant yields a final answer, or give up."""
    for _ in range(limit):
        result = assistant.poll_rephrasing()
        if result is not None:
            return result
    return None


def _assistant(llm: object | None = None) -> tuple[Assistant, SensorDataProcessor]:
    processor = SensorDataProcessor()
    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel=NOISE_CHANNEL, value=76.3)
    )
    ventilation = VentilationController()
    assistant = Assistant(
        processor,
        lambda: ["dev-1"],
        ventilation=ventilation,
        llm=llm,  # type: ignore[arg-type]
    )
    return assistant, processor


# -- works with no model at all -----------------------------------------------


def test_answers_without_any_model() -> None:
    assistant, _ = _assistant()
    answer = assistant.ask("现在噪声多少")

    assert answer.source is AnswerSource.TEMPLATE
    assert "76.3" in answer.text
    assert isinstance(assistant.llm, NullLlmClient)


def test_unrecognised_question_is_a_fallback_not_an_error() -> None:
    assistant, _ = _assistant()
    answer = assistant.ask("今天星期几")

    assert answer.source is AnswerSource.FALLBACK
    assert "我可以回答" in answer.text


def test_blank_question_still_returns_an_answer() -> None:
    assistant, _ = _assistant()
    assert assistant.ask("   ").source is AnswerSource.FALLBACK


def test_answer_carries_its_intent_and_facts() -> None:
    assistant, _ = _assistant()
    answer = assistant.ask("噪声超标了吗")

    assert answer.intent is not None
    assert answer.intent.kind is IntentKind.ALARM_STATE
    assert answer.facts is not None
    assert answer.facts.value == 76.3


# -- what the model is allowed to see -----------------------------------------


def test_the_model_only_ever_sees_numbers_that_are_already_facts() -> None:
    """The guarantee is not "the model sees little" -- since 2026-09-08 the
    explain job hands it the whole fact list. It is that **every number it
    sees is one the grounding check would accept anyway**: no DataPoints,
    no readings from other channels, nothing it could mine for a figure it
    would then be refused for using."""
    llm = _ScriptedLlm("噪声 76.3dB，正常。")
    assistant, _ = _assistant(llm)

    answer = assistant.ask("现在噪声多少")

    assert len(llm.prompts) == 1
    assert phrasing.numbers_are_grounded(llm.prompts[0], answer.facts)


def test_a_one_number_answer_is_still_only_reworded() -> None:
    """"最高值是多少" holds one number; an explanation of it would be
    padding, so it keeps the old job and the old prompt."""
    llm = _ScriptedLlm("最高 76.3dB。")
    assistant, _ = _assistant(llm)

    assistant.ask("噪声最高多少")

    assert llm.systems == [REPHRASE_SYSTEM_PROMPT]


def test_an_alarm_question_hands_over_every_fact_it_has() -> None:
    """The complaint this answers: the facts held the range, the average,
    the sample count and the distance to the limit, and the template
    printed one of them."""
    llm = _ScriptedLlm("好的。")
    assistant, _ = _assistant(llm)

    assistant.ask("噪声超标了吗")

    prompt = llm.prompts[0]
    assert llm.systems == [EXPLAIN_SYSTEM_PROMPT]
    assert "报警阈值" in prompt
    assert "距阈值还有" in prompt


def test_the_most_asked_question_stays_on_the_fast_path() -> None:
    """"现在噪声多少" is the commonest question in the benchmark and its
    template already states the reading and the distance to the limit.
    Explaining it measured 9.7 s against 3.7 s for a rewording, which buys
    a sample count nobody asked for."""
    llm = _ScriptedLlm("好的。")
    assistant, _ = _assistant(llm)

    assistant.ask("现在噪声多少")

    assert llm.systems == [REPHRASE_SYSTEM_PROMPT]


def test_ask_returns_immediately_with_the_template_answer() -> None:
    """Generation takes seconds on CPU; ask() must not wait for it."""
    llm = _ScriptedLlm("改写后的句子。")
    assistant, _ = _assistant(llm)

    answer = assistant.ask("现在噪声多少")

    assert answer.source is AnswerSource.TEMPLATE
    assert "76.3" in answer.text


# -- rephrasing is accepted only when grounded --------------------------------


def test_grounded_rephrasing_is_accepted() -> None:
    llm = _ScriptedLlm("现在的噪声是 76.3dB。")
    assistant, _ = _assistant(llm)
    assistant.ask("现在噪声多少")

    improved = _drain(assistant)

    assert improved is not None
    assert improved.source is AnswerSource.MODEL
    assert improved.text == "现在的噪声是 76.3dB。"


def test_rephrasing_that_invents_a_number_is_discarded() -> None:
    """The whole point: a plausible but unmeasured figure never reaches
    the user, prompt instructions notwithstanding."""
    llm = _ScriptedLlm("噪声现在 76.3dB，比昨天的 71.0dB 高。")
    assistant, _ = _assistant(llm)
    original = assistant.ask("现在噪声多少")

    improved = _drain(assistant)

    assert improved is not None
    assert improved.source is AnswerSource.TEMPLATE
    assert improved.text == original.text


def test_poll_returns_none_while_the_model_is_still_streaming() -> None:
    llm = _ScriptedLlm("现在的噪声是 76.3dB。", chunks=4)
    assistant, _ = _assistant(llm)
    assistant.ask("现在噪声多少")

    assert assistant.poll_rephrasing() is None  # first fragment only


def test_streamed_fragments_are_accumulated_into_one_answer() -> None:
    """A streaming client hands back the text produced since the last
    call; keeping only the final fragment would fail grounding and
    silently disable rephrasing altogether."""
    llm = _ScriptedLlm("现在的噪声是 76.3dB。", chunks=5)
    assistant, _ = _assistant(llm)
    assistant.ask("现在噪声多少")

    improved = _drain(assistant)

    assert improved is not None
    assert improved.text == "现在的噪声是 76.3dB。"


def test_poll_returns_none_when_nothing_was_asked() -> None:
    assistant, _ = _assistant(_ScriptedLlm("x"))
    assert assistant.poll_rephrasing() is None


def test_help_text_is_never_sent_to_the_model() -> None:
    """The capability menu is a promise about what the system can do;
    rewording it risks promising something it cannot.

    An unrecognised question does reach the model -- but as the question
    itself, to be classified, never as the help text to be reworded.
    """
    llm = _ScriptedLlm("unknown")
    assistant, _ = _assistant(llm)

    assistant.ask("今天星期几")

    assert llm.prompts == ["今天星期几"]
    assert llm.systems == [PARSE_SYSTEM_PROMPT]
    assert all(phrasing.HELP_TEXT not in prompt for prompt in llm.prompts)


def test_an_unrecognised_question_is_sent_to_the_model_to_classify() -> None:
    """The rules only know the phrasings they were written for. This is
    the whole point of attaching a model: a question worded outside that
    vocabulary gets answered instead of refused."""
    llm = _ScriptedLlm("maximum noise")
    assistant, _ = _assistant(llm)

    # 例句原为"这半天里最闹腾的时候到底是多少"。2026-09-09 把"闹腾"收进噪声
    # 词表后规则已能直接认出它——那是更好的结果（零延迟且每次一致），于是本
    # 用例改用一句规则仍认不出通道的。这是第三次因为补词表而要换例句：
    # 拿"当前的空缺"当测试样例，空缺一补，样例就失效了。
    first = assistant.ask("这一阵子峰值到底多少")
    # The rules got the statistic but not the channel, so the user is asked
    # back straight away -- and the model is given the sentence anyway.
    assert first.text == phrasing.CLARIFY_TEXT

    answer = _drain(assistant)

    assert isinstance(answer, Answer)
    assert answer.source is AnswerSource.MODEL_INTENT
    assert answer.intent is not None
    assert answer.intent.kind is IntentKind.MAXIMUM
    assert answer.intent.channel == NOISE_CHANNEL
    assert answer.facts is not None
    assert answer.facts.maximum is not None


def test_a_classified_answer_is_composed_by_the_template_not_the_model() -> None:
    """The model chose *which question* was asked; every word and number
    the user then reads is the system's own. Proven by giving the model a
    reply that also contains prose and a fabricated number, and checking
    neither survives."""
    llm = _ScriptedLlm("current_value temperature 大概 999 度吧")
    assistant, _ = _assistant(llm)

    assistant.ask("外面冷不冷")
    answer = _drain(assistant)

    assert isinstance(answer, Answer)
    assert "999" not in answer.text
    assert "大概" not in answer.text
    assert answer.text == phrasing.render(answer.facts)


def test_an_unusable_classification_replaces_the_placeholder() -> None:
    """规则落空时屏幕上是"让我想想…"，模型也认不出就必须换掉它——
    占位句不被替换就会留在那里当最终答复。换上的是一句短的，
    并把能力清单变成一个可以问的问题：刚被误解的人想知道的是自己被误解了，
    而不是读十一条要点。"""
    llm = _ScriptedLlm("unknown")
    assistant, _ = _assistant(llm)

    first = assistant.ask("你觉得我今天该穿什么")
    assert first.source is AnswerSource.PENDING
    assert first.text == phrasing.THINKING_TEXT

    answer = _drain(assistant)
    assert isinstance(answer, Answer)
    assert answer.source is AnswerSource.FALLBACK
    assert answer.text == phrasing.UNKNOWN_TEXT


def test_asking_what_it_can_do_gets_the_list_not_a_placeholder() -> None:
    """"你能干什么"和"规则没认出来"共用 HELP 这一个标签，但它们是两件事：
    前者要的就是那张清单，不该被当成没听懂而挂起。"""
    llm = _ScriptedLlm("unknown")
    assistant, _ = _assistant(llm)

    answer = assistant.ask("你能干什么")

    assert answer.source is AnswerSource.FALLBACK
    assert answer.text == phrasing.HELP_TEXT


def test_without_a_model_the_list_is_still_the_immediate_answer() -> None:
    """没有模型就没有东西会来替换占位句，此时那张清单仍是当下最有用的答复。"""
    assistant, _ = _assistant(None)

    answer = assistant.ask("你觉得我今天该穿什么")

    assert answer.source is AnswerSource.FALLBACK
    assert answer.text == phrasing.HELP_TEXT


def test_a_new_question_abandons_the_rephrasing_still_in_flight() -> None:
    """The user has moved on, so the old rewording is worthless -- and
    delivering it late is worse than worthless: it lands under the *new*
    question, where every number in it is real but answers something the
    user did not ask."""
    llm = _ScriptedLlm("改写。", chunks=5)
    assistant, _ = _assistant(llm)

    assistant.ask("现在噪声多少")
    assistant.poll_rephrasing()  # part-way through the first rewording
    assistant.ask("噪声超标了吗")

    assert llm.submit_count == 2  # the second question gets its own


def test_the_abandoned_rephrasing_is_never_delivered() -> None:
    """Direct cover for the bug this was found through: a stale answer
    overwrote the following question's bubble in the desktop panel."""
    llm = _ScriptedLlm("温度相关的改写。", chunks=5)
    assistant, _ = _assistant(llm)

    assistant.ask("现在温度多少")
    assistant.poll_rephrasing()
    second = assistant.ask("噪声超标了吗")

    improved = _drain(assistant)

    # Whatever comes back belongs to the *second* question.
    assert improved is not None
    assert improved.intent is not None
    assert improved.intent.kind is second.intent.kind  # type: ignore[union-attr]


def test_model_returning_nothing_falls_back_to_the_template() -> None:
    llm = _ScriptedLlm(None)
    assistant, _ = _assistant(llm)
    original = assistant.ask("现在噪声多少")

    result = _drain(assistant)
    assert result is not None
    assert result.source is AnswerSource.TEMPLATE
    assert "76.3" in original.text


# -- data flows through from the processor ------------------------------------


def test_answers_track_new_readings() -> None:
    assistant, processor = _assistant()
    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel=TEMPERATURE_CHANNEL, value=31.5)
    )

    assert "31.5" in assistant.ask("现在温度多少").text


def test_capabilities_lists_the_question_types() -> None:
    assistant, _ = _assistant()
    assert any("噪声" in line for line in assistant.capabilities())


# -- instructions -------------------------------------------------------------


def _assistant_with_fan(
    llm: object | None = None,
) -> tuple[Assistant, VentilationController]:
    processor = SensorDataProcessor()
    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel=TEMPERATURE_CHANNEL, value=24.0)
    )
    ventilation = VentilationController()
    assistant = Assistant(
        processor,
        lambda: ["dev-1"],
        ventilation=ventilation,
        llm=llm,  # type: ignore[arg-type]
    )
    return assistant, ventilation


def test_an_instruction_is_carried_out_without_any_model() -> None:
    """Same rule as everywhere else in this feature: the model is an
    increment, never a dependency. Turning the fan on works with none
    attached."""
    assistant, ventilation = _assistant_with_fan()

    answer = assistant.ask("把风扇打开")

    assert answer.source is AnswerSource.TEMPLATE
    assert answer.facts is not None
    assert answer.facts.applied is True
    assert ventilation.settings.mode is FanMode.MANUAL_ON


def test_an_instruction_is_never_sent_to_the_model_for_rewording() -> None:
    """A confirmation that something changed should read identically every
    time; a model "improving" it only adds a way for the wording to drift
    from what actually happened.

    2026-09-14：指令现在**会**发给模型一次，但那是复核（要一个标签），
    不是改写。本测试守的是原来那条线——模型写的字一个都进不到确认句里：
    这里的回复是一句人话而不是标签，读不出标签即视为分歧，
    于是系统反问，而反问句是模板生成的。"""
    llm = _ScriptedLlm("我已经帮你把风扇开到最大了。")
    assistant, _ = _assistant_with_fan(llm)

    assistant.ask("把风扇打开")

    assert llm.submit_count == 1
    assert llm.systems == [PARSE_SYSTEM_PROMPT]
    answer = _drain(assistant)
    assert isinstance(answer, Answer)
    assert "把风扇开到最大" not in answer.text


def test_a_threshold_instruction_uses_the_number_from_the_sentence() -> None:
    assistant, ventilation = _assistant_with_fan()

    answer = assistant.ask("把通风温度阈值调到 28 度")

    assert ventilation.settings.temperature_max == 28.0
    assert "28" in answer.text


def test_a_model_classified_instruction_is_carried_out_too() -> None:
    """The colloquial phrasing the rules miss. The model supplies only the
    label -- the value still comes from the user's own sentence.

    The example used to be "太闷了，把那个数字弄成 26" -- chosen because 闷
    was the one feeling word no list held. 2026-09-09 added it (a real user
    typed "好闷啊" and got the help text), so the sentence now matches as a
    humidity question and no longer exercises the fallback. Replaced with a
    phrasing the rules still miss rather than removing 闷: a rule that fires
    is better than a model round trip, and this test is about what happens
    when no rule fires at all."""
    llm = _ScriptedLlm("set_vent_threshold temperature")
    assistant, ventilation = _assistant_with_fan(llm)

    first = assistant.ask("黏糊糊的，把那个数弄成 26")
    # 2026-09-09 起规则落空时先回一句占位，而不是甩出整张能力清单——
    # 一段长文本几秒后被换成一句不相干的话，读起来像是第一次答错了。
    assert first.source is AnswerSource.PENDING

    answer = _drain(assistant)

    # 2026-09-14 起这一路不再直接执行：规则认不出、只有模型判成指令时，
    # 没有第二个判断可以跟它对照，所以先反问（裁决表第四行）。
    assert isinstance(answer, Answer)
    assert answer.source is AnswerSource.MODEL_INTENT
    assert ventilation.settings.temperature_max != 26.0
    assert "26" in answer.text

    assistant.ask("是")

    # 数值仍然取自用户自己那句话，不是模型回复里的数字。
    assert ventilation.settings.temperature_max == 26.0


def test_a_number_in_the_model_reply_cannot_become_the_threshold() -> None:
    """The invariant this design turns on: a model that transcribes 26 as
    36 must not be able to change what the system does. The value is read
    from the user's words, so the model's digits are simply ignored."""
    llm = _ScriptedLlm("set_vent_threshold temperature 36")
    assistant, ventilation = _assistant_with_fan(llm)

    assistant.ask("把那个数字弄成 26")
    _drain(assistant)
    assistant.ask("是")

    assert ventilation.settings.temperature_max == 26.0

# -- 指令的模型复核（2026-09-14） ---------------------------------------------


def test_the_model_agreeing_lets_the_instruction_through() -> None:
    """两边独立读出同一个意思，就执行。等待期间设备没有被动过——
    这是复核机制的要点：先不做，等裁决。"""
    llm = _ScriptedLlm("fan_on")
    assistant, ventilation = _assistant_with_fan(llm)

    first = assistant.ask("把风扇打开")

    assert first.source is AnswerSource.PENDING
    assert ventilation.settings.mode is FanMode.AUTO

    answer = _drain(assistant)

    assert isinstance(answer, Answer)
    assert ventilation.settings.mode is FanMode.MANUAL_ON


def test_the_model_disagreeing_asks_instead_of_acting() -> None:
    """规则判成开风扇、模型读成问风扇状态——留出题库里规则自信答错的句子
    几乎都长这样。此时不执行，把话问回去。"""
    llm = _ScriptedLlm("fan_state")
    assistant, ventilation = _assistant_with_fan(llm)

    assistant.ask("把风扇打开")
    answer = _drain(assistant)

    assert isinstance(answer, Answer)
    assert "是想让我" in answer.text
    assert ventilation.settings.mode is FanMode.AUTO

    assistant.ask("是")

    assert ventilation.settings.mode is FanMode.MANUAL_ON


def test_saying_no_to_the_confirmation_leaves_the_fan_alone() -> None:
    llm = _ScriptedLlm("fan_state")
    assistant, ventilation = _assistant_with_fan(llm)

    assistant.ask("把风扇打开")
    _drain(assistant)
    answer = assistant.ask("不用")

    assert answer.text == phrasing.CONTROL_CANCELLED_TEXT
    assert ventilation.settings.mode is FanMode.AUTO


def test_an_unanswered_confirmation_does_not_wait_around() -> None:
    """用户没回答确认问句，而是说了别的事。挂起的那条随之作废——
    一条没有得到授权的指令不该在对话里继续漂着，更不该被下一句
    碰巧含"是"的话点着。"""
    llm = _ScriptedLlm("fan_state")
    assistant, ventilation = _assistant_with_fan(llm)

    assistant.ask("把风扇打开")
    _drain(assistant)
    assistant.ask("现在温度多少")
    assistant.ask("是")

    assert ventilation.settings.mode is FanMode.AUTO


def test_a_silent_model_does_not_swallow_the_instruction() -> None:
    """超时与连接断在这里表现为空回复。裁决表把它归到"模型不可用"那一行：
    行为与改动前一样，照规则执行。一次超时不该把用户的指令吃掉。"""
    llm = _ScriptedLlm("")
    assistant, ventilation = _assistant_with_fan(llm)

    assistant.ask("把风扇打开")
    _drain(assistant)

    assert ventilation.settings.mode is FanMode.MANUAL_ON


def test_without_a_model_an_instruction_is_still_immediate() -> None:
    """可靠性下限：没有模型时，这套机制整个不出现——一次问答之内
    行为与改动前逐句一致，指令仍然当场执行。"""
    assistant, ventilation = _assistant_with_fan(NullLlmClient())

    answer = assistant.ask("把风扇打开")

    assert answer.source is AnswerSource.TEMPLATE
    assert ventilation.settings.mode is FanMode.MANUAL_ON


def test_a_channel_reply_completing_an_instruction_skips_review() -> None:
    """"温度"补的是上一条指令缺的那一半，而那一条已经裁决过了。
    单独拿这个词去问模型，回来的必然是"在问当前温度"，于是每一次补全
    都会被读成分歧，用户就再也说不完一句话。"""
    llm = _ScriptedLlm("set_vent_threshold temperature")
    assistant, ventilation = _assistant_with_fan(llm)

    assistant.ask("把通风阈值调到 28")
    _drain(assistant)
    answer = assistant.ask("温度")

    assert ventilation.settings.temperature_max == 28.0
    assert "28" in answer.text
    # 只复核过最初那一句：补通道的回答没有再问一次模型。
    assert llm.submit_count == 1


# -- 上一轮通道的记忆 ---------------------------------------------------------


def _clocked_assistant(clock) -> Assistant:
    processor = SensorDataProcessor()
    for channel, value in (
        (TEMPERATURE_CHANNEL, 22.4),
        (NOISE_CHANNEL, 47.3),
    ):
        processor.handle_data_point(
            DataPoint(device_id="dev-1", channel=channel, value=value)
        )
    return Assistant(processor, lambda: ["dev-1"], clock_ms=clock)


def test_a_follow_up_inherits_the_previous_question_s_channel() -> None:
    """「现在温度多少」→「最高呢」。没有这一步，第二句读不出通道，
    只能回落到帮助文案。"""
    assistant = _clocked_assistant(lambda: 0)

    assistant.ask("现在温度多少")
    answer = assistant.ask("最高呢")

    assert answer.intent is not None
    assert answer.intent.kind is IntentKind.MAXIMUM
    assert answer.intent.channel == TEMPERATURE_CHANNEL


def test_a_sentence_that_names_its_own_channel_wins() -> None:
    """记忆只补空缺，永远不覆盖句子自己说出来的东西。"""
    assistant = _clocked_assistant(lambda: 0)

    assistant.ask("现在温度多少")
    answer = assistant.ask("噪声多大")

    assert answer.intent is not None
    assert answer.intent.channel == NOISE_CHANNEL


def test_the_memory_lapses_after_its_timeout() -> None:
    """隔了很久再问一句"最高呢"，多半不是在接着上一个话题。
    过期后系统反问是哪个通道，而不是拿一个可能已经过时的通道去作答。"""
    now = [0]
    assistant = _clocked_assistant(lambda: now[0])

    assistant.ask("现在温度多少")
    now[0] = (CHANNEL_MEMORY_SECONDS + 1) * 1000
    answer = assistant.ask("最高呢")

    assert answer.text == phrasing.CLARIFY_TEXT
    assert answer.intent is not None
    assert answer.intent.channel is None


def test_a_channelless_question_does_not_erase_the_memory() -> None:
    """"有几个设备在线"夹在两句噪声提问之间，不算换了话题。"""
    assistant = _clocked_assistant(lambda: 0)

    assistant.ask("噪声多大")
    assistant.ask("有几个设备在线")
    answer = assistant.ask("最高呢")

    assert answer.intent is not None
    assert answer.intent.channel == NOISE_CHANNEL


def test_an_instruction_never_inherits_a_channel() -> None:
    """问句猜错通道只是答非所问，指令猜错通道会改错东西——
    所以指令分支根本不读这份记忆。"""
    assistant = _clocked_assistant(lambda: 0)

    assistant.ask("现在温度多少")
    answer = assistant.ask("把通风阈值调到 28")

    assert answer.facts is not None
    assert answer.facts.applied is not True


# -- "还差多少就超限了" -------------------------------------------------------


def test_a_reading_comes_with_its_distance_to_the_limit() -> None:
    """两个要求一口气问出来（"现在多少度，还差多少超限"）是常见说法。
    减法在代码里做，因此那个差值和读数一样是事实，不是模型编的。

    本用例原先问的是"现在温度多少"——只有一个要求，却断言余量必须出现，
    等于把"永远附带余量"这个行为固化成了预期。2026-09-09 改为按需附加后
    补齐两面：问了才给，没问就不给。"""
    assistant = _clocked_assistant(lambda: 0)

    answer = assistant.ask("现在温度多少，还差多少超限")

    assert answer.facts is not None
    assert answer.facts.margin == 35.0 - 22.4
    assert "12.6" in answer.text


def test_a_plain_reading_question_gets_only_the_reading() -> None:
    """多说多错：没问余量就不该给。余量本身照常算出并留在 Facts 里——
    它是事实，解释档仍会列出它——这里管的只是那一句模板要不要说。"""
    assistant = _clocked_assistant(lambda: 0)

    answer = assistant.ask("现在温度多少")

    assert answer.facts is not None
    assert answer.facts.margin == 35.0 - 22.4   # 仍然算了
    assert "12.6" not in answer.text            # 但没说
    assert "22.4" in answer.text


def test_the_memory_never_turns_an_unrelated_sentence_into_a_question() -> None:
    """演练里抓到的真实回归：第一版让上一轮通道补给任何句子，于是
    "帮我订张票"被答成了当前湿度——一句本该被拒绝的话，拿到了一个真数字。
    记忆只补全追问，不替一句话找话题。"""
    assistant = _clocked_assistant(lambda: 0)

    assistant.ask("现在温度多少")
    answer = assistant.ask("帮我订张票")

    assert answer.intent is not None
    assert answer.intent.kind is IntentKind.HELP


def test_a_colloquial_instruction_still_reaches_the_model() -> None:
    """同一处回归的另一面：一句没有通道词的话本该落空后交给模型分类，
    却被记忆读成了一次湿度提问。

    例句原为"别吹了关上吧"。2026-09-09 把"吹"收进风扇词表后（题库里这句
    是唯一一条规则认不出的指令），它已能被正确读作关风扇，不再落空，
    因此改用一句仍然落空的。换例句而非放弃收词：能被规则认出总好过绕一趟模型，
    而本用例要守的是**没有任何规则命中时记忆不得越权**。"""
    assistant = _clocked_assistant(lambda: 0)

    assistant.ask("那湿度呢")
    answer = assistant.ask("顺手弄一下吧")

    assert answer.intent is not None
    assert answer.intent.kind is IntentKind.HELP


# -- 报警断言黑名单 -----------------------------------------------------------


def test_a_rephrasing_that_invents_an_alarm_is_discarded() -> None:
    """演练里真实发生过：模型给"最高值是 95.0dB"的改写加了"处于超标状态"，
    数字全对，但 MAXIMUM 的事实里根本没有越限判定这一项。
    接地校验管数字不管结论，所以这条另设。"""
    llm = _ScriptedLlm("噪声最高 76.3dB，已经超标了。")
    assistant, _ = _assistant(llm)

    assistant.ask("噪声最高多少")
    answer = _drain(assistant)

    assert answer is not None
    assert answer.source is AnswerSource.TEMPLATE
    assert "超标" not in answer.text


def test_the_same_words_are_allowed_once_the_facts_carry_an_alarm() -> None:
    """越限时说"超标"是对的。黑名单挡的是没有依据的那一次。"""
    processor = SensorDataProcessor()
    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel=NOISE_CHANNEL, value=95.0)
    )
    llm = _ScriptedLlm("噪声 95.0dB，已经超标了。")
    assistant = Assistant(processor, lambda: ["dev-1"], llm=llm)  # type: ignore[arg-type]

    assistant.ask("噪声超标了吗")
    answer = _drain(assistant)

    assert answer is not None
    assert answer.source is AnswerSource.MODEL


# -- 反问澄清 -----------------------------------------------------------------


def test_a_question_with_no_channel_is_asked_back_about() -> None:
    """"超标了吗"以前答的是"该通道现在还没有有效读数"——一句关于谁也没提到的
    通道的话。问题被听懂了，缺的是对象，那就该问回去。"""
    assistant = _clocked_assistant(lambda: 0)

    answer = assistant.ask("超标了吗")

    assert answer.text == phrasing.CLARIFY_TEXT
    assert answer.facts is not None
    assert answer.facts.needs_channel is True


def test_a_one_word_reply_answers_the_question_that_prompted_it() -> None:
    """反问的价值全在这一步：回一个词就得到原来那个问题的答案，
    而不是这个词自己的当前读数。"""
    assistant = _clocked_assistant(lambda: 0)

    assistant.ask("超标了吗")
    answer = assistant.ask("噪声")

    assert answer.intent is not None
    assert answer.intent.kind is IntentKind.ALARM_STATE
    assert answer.intent.channel == NOISE_CHANNEL


def test_moving_on_drops_the_question_instead_of_saving_it() -> None:
    """用户换了话题就是换了话题。留着那个待答问题，只会让再往后的某个
    通道词莫名其妙地接到它上面。"""
    assistant = _clocked_assistant(lambda: 0)

    assistant.ask("超标了吗")
    assistant.ask("有几个设备在线")
    answer = assistant.ask("温度")

    assert answer.intent is not None
    assert answer.intent.kind is IntentKind.CURRENT_VALUE


def test_a_stale_question_is_not_answered() -> None:
    """隔了几分钟再回一个"温度"，用户多半已经忘了自己问过什么；
    这时给出旧问题的答案，是一个正确但答非所问的回答。"""
    now = [0]
    assistant = _clocked_assistant(lambda: now[0])

    assistant.ask("超标了吗")
    now[0] = (CLARIFY_SECONDS + 1) * 1000
    answer = assistant.ask("温度")

    assert answer.intent is not None
    assert answer.intent.kind is IntentKind.CURRENT_VALUE


def test_the_clarification_is_never_sent_to_the_model_for_rewording() -> None:
    """改写过的问句是另一个问句。这句话唯一要做对的事就是把那三个词说出来。"""
    llm = _ScriptedLlm("你想问哪个呢")
    assistant = Assistant(SensorDataProcessor(), lambda: ["dev-1"], llm=llm)  # type: ignore[arg-type]

    assistant.ask("超标了吗")

    assert llm.systems == [PARSE_SYSTEM_PROMPT]


def test_an_instruction_clears_a_question_left_hanging() -> None:
    assistant = _clocked_assistant(lambda: 0)

    assistant.ask("超标了吗")
    assistant.ask("把风扇打开")
    answer = assistant.ask("温度")

    assert answer.intent is not None
    assert answer.intent.kind is IntentKind.CURRENT_VALUE


def test_resetting_ends_the_exchange_but_touches_nothing_else() -> None:
    """两轮演练之间要能回到同一个起点。读数、阈值、风扇模式都不是对话，
    reset 只清掉"上一句问的是什么"和"还欠着哪个问题"。"""
    assistant = _clocked_assistant(lambda: 0)

    assistant.ask("超标了吗")
    assistant.reset_conversation()
    hanging = assistant.ask("噪声")
    assistant.ask("现在温度多少")
    assistant.reset_conversation()
    orphan = assistant.ask("最高呢")

    assert hanging.intent is not None
    assert hanging.intent.kind is IntentKind.CURRENT_VALUE
    assert orphan.text == phrasing.CLARIFY_TEXT


# -- 指令的反问（2026-09-09） -------------------------------------------------


def test_an_instruction_missing_its_channel_asks_back() -> None:
    """反问原先只管提问；指令缺对象时是一句平白的拒绝，用户得整句重打。
    数值仍取自**最初那句原话**，一个词的答复只补通道——绝不从后门带进数字。"""
    assistant, ventilation = _assistant_with_fan()

    asked = assistant.ask("把通风阈值调到 28")
    assert "温度还是湿度" in asked.text
    assert "把通风阈值调到 28" in asked.text   # 回显原话

    done = assistant.ask("温度")
    assert ventilation.settings.temperature_max == 28.0
    assert "28" in done.text


def test_an_instruction_without_a_value_is_still_refused() -> None:
    """两半都缺时没有任何一个词能补全它。把指令挂起来收集两个答复，
    正是"过期的答复写了一个没人要的设置"的来路。"""
    assistant, ventilation = _assistant_with_fan()

    answer = assistant.ask("把通风阈值调低一点")

    assert "说明是温度还是湿度" in answer.text
    assert ventilation.settings.temperature_max == 30.0


def test_a_new_question_cancels_a_pending_instruction() -> None:
    """"现在噪声多少"也是一个带通道的 CURRENT_VALUE，只看意图种类会把它
    当成上一轮的答复吞掉——提问那侧只是答非所问，指令那侧会改设置。
    因此答复必须是**裸的通道词**，这一条在文本上判定。"""
    assistant, ventilation = _assistant_with_fan()

    assistant.ask("把通风阈值调到 28")
    answer = assistant.ask("现在噪声多少")

    assert "噪声" in answer.text
    assert ventilation.settings.temperature_max == 30.0


def test_a_stale_reply_does_not_write_a_setting() -> None:
    """指令的待答窗口 25 s，短于提问的 60 s。差别不在长短而在性质：
    过期的提问给出一个答非所问的回答，过期的指令**改掉一个设置**。"""
    now = [0]
    processor = SensorDataProcessor()
    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel=TEMPERATURE_CHANNEL, value=24.0)
    )
    ventilation = VentilationController()
    assistant = Assistant(
        processor,
        lambda: ["dev-1"],
        ventilation=ventilation,
        llm=None,  # type: ignore[arg-type]
        clock_ms=lambda: now[0],
    )

    assistant.ask("把通风阈值调到 28")
    now[0] = 26_000                      # 26 秒后
    assistant.ask("温度")

    assert ventilation.settings.temperature_max == 30.0


def test_a_refused_rewording_gets_one_retry() -> None:
    """确定性检查判失败后让模型再写一次，判官仍是代码。
    与"输出前一律自校验"的区别在两处：自校验由刚出错的那个模型当判官，
    而且要给 100% 的请求付双倍时间；这里的判官是 choose()——免费、确定、
    对数字完备——且只有被退回的那些付。

    实测 30 次：首轮退回 5 次（17%），重写救回 4 次（80%），
    平均耗时 1.8 s → 2.3 s。"""
    llm = _ScriptedLlm("噪声 76.3dB。请注意保持安静。", then="现在的噪声是 76.3dB。")
    assistant, _ = _assistant(llm)

    assistant.ask("现在噪声多少")

    answer = _drain(assistant)
    assert isinstance(answer, Answer)
    assert answer.source is AnswerSource.MODEL
    assert answer.text == "现在的噪声是 76.3dB。"
    assert llm.systems[-1] == REPHRASE_RETRY_SYSTEM_PROMPT


def test_only_one_retry_then_the_template_stands() -> None:
    """第二次重写等于追着一个已经两次没过同一道检查的模型，
    而退回去的那份模板本来就是正确答案。"""
    llm = _ScriptedLlm(
        "噪声 76.3dB。请注意保持安静。", then="噪声 76.3dB。也请注意休息。"
    )
    assistant, _ = _assistant(llm)

    assistant.ask("现在噪声多少")

    answer = _drain(assistant)
    assert isinstance(answer, Answer)
    assert answer.source is AnswerSource.TEMPLATE
    assert llm.submit_count == 2


# -- 省略式追问与裸开关结算（2026-09-09 真人试用暴露） -----------------------


def test_a_bare_channel_follow_up_inherits_the_previous_question_kind() -> None:
    """"温度最高值是多少 → 噪声呢"此前答的是噪声**当前值**。

    通道记忆当时只做了一半：句子没说通道时用记忆补通道（"最高呢"），
    但句子只说了通道、没说问法时，问法无处可补，落回默认的当前值。
    数字是真的，答的却是另一个问题——这类错误没有下游能发现。"""
    assistant = _clocked_assistant(lambda: 0)

    first = assistant.ask("温度最高值是多少")
    assert first.intent is not None
    assert first.intent.kind is IntentKind.MAXIMUM

    second = assistant.ask("噪声呢")
    assert second.intent is not None
    assert second.intent.kind is IntentKind.MAXIMUM
    assert second.intent.channel == NOISE_CHANNEL


def test_a_follow_up_that_states_its_own_kind_is_not_overwritten() -> None:
    """"现在噪声多少"自己说清了问法，用上一轮的"最高"覆盖它就是篡改。"""
    assistant = _clocked_assistant(lambda: 0)

    assistant.ask("温度最高值是多少")
    answer = assistant.ask("现在噪声多少")

    assert answer.intent is not None
    assert answer.intent.kind is IntentKind.CURRENT_VALUE


def test_an_unanswered_question_does_not_seed_the_kind_memory() -> None:
    """以反问收场的那一轮什么也没回答。把它的问法留下，会让两轮后一句
    "温度"接上那个已被丢弃的问题——而丢弃它正是待答机制的用意。"""
    assistant = _clocked_assistant(lambda: 0)

    assistant.ask("超标了吗")        # 反问，未作答
    assistant.ask("有几个设备在线")   # 换话题，待答被丢弃
    answer = assistant.ask("温度")

    assert answer.intent is not None
    assert answer.intent.kind is IntentKind.CURRENT_VALUE


def test_the_bare_switch_question_can_actually_be_answered() -> None:
    """真人试用里撞出的死胡同：系统反问"是要开关风扇吗"，
    用户怎么回都接不住，只能把"关风扇"整句重打。

    做通道反问与指令反问时都配了待答状态与结算逻辑，做这个时只做了"问"、
    没做"接"。"""
    assistant, ventilation = _assistant_with_fan()

    asked = assistant.ask("打开")
    assert "开关风扇" in asked.text

    done = assistant.ask("是的 关了")
    assert ventilation.settings.mode is FanMode.MANUAL_OFF
    assert "手动常关" in done.text


def test_a_fan_instruction_makes_the_next_bare_switch_actionable() -> None:
    """上一句刚操作过风扇，"关了吧"就不必再反问一遍——话题已经定死了。"""
    assistant, ventilation = _assistant_with_fan()

    assistant.ask("去吧风扇打开")
    answer = assistant.ask("关了吧")

    assert ventilation.settings.mode is FanMode.MANUAL_OFF
    assert "手动常关" in answer.text


def test_without_a_fan_topic_a_bare_switch_still_asks_back() -> None:
    """脱离了风扇话题，"关了吧"可能在说任何东西。这条是安全边界：
    读错一个通道只是答非所问，把一句无关的话读成开关风扇会真的动执行器。"""
    assistant, ventilation = _assistant_with_fan()

    assistant.ask("现在温度多少")
    answer = assistant.ask("关了吧")

    assert "开关风扇" in answer.text
    assert ventilation.settings.mode is FanMode.AUTO


def test_a_stale_fan_topic_no_longer_settles_a_bare_switch() -> None:
    """九十秒够接住一次对话里的追问，又不至于让几分钟后一句"关了吧"
    莫名其妙地关掉风扇。"""
    now = [0]
    processor = SensorDataProcessor()
    processor.handle_data_point(
        DataPoint(device_id="dev-1", channel=TEMPERATURE_CHANNEL, value=24.0)
    )
    ventilation = VentilationController()
    assistant = Assistant(
        processor,
        lambda: ["dev-1"],
        ventilation=ventilation,
        llm=None,  # type: ignore[arg-type]
        clock_ms=lambda: now[0],
    )

    assistant.ask("打开")            # 反问，话题钉在风扇上
    now[0] = 91_000                  # 超过 FAN_TOPIC_SECONDS
    answer = assistant.ask("关了吧")

    assert "开关风扇" in answer.text
    assert ventilation.settings.mode is FanMode.AUTO


def test_a_question_the_rules_miss_always_reaches_the_model() -> None:
    """"规则认不出、模型也不介入"是这套设计里最不该出现的状态：
    用户得到一句套话，而系统连试都没试。用户 2026-09-09 报告撞见过，
    复现后发现是「你能」被当成了「你能干什么」。"""
    for question in (
        "你能告诉我现在温度多少吗",
        "帮助我查一下湿度",
        "这半天里最遭罪的时候是多少",
        "给我看看数据",
        "帮我订张票",
    ):
        llm = _ScriptedLlm(None)          # 永远不给结果，只看有没有被叫
        assistant, _ = _assistant(llm)
        answer = assistant.ask(question)

        assert llm.submit_count == 1, question
        assert answer.source is AnswerSource.PENDING, question


def test_a_genuine_capability_question_does_not_pay_for_a_model_call() -> None:
    """反过来，真在问能力的那几句该当场给清单——它要的就是这张清单，
    绕一趟模型只是白等几秒。"""
    for question in ("你能干什么", "有什么功能", "帮助"):
        llm = _ScriptedLlm(None)
        assistant, _ = _assistant(llm)
        answer = assistant.ask(question)

        assert llm.submit_count == 0, question
        assert answer.source is AnswerSource.FALLBACK, question
        assert answer.text == phrasing.HELP_TEXT, question


def test_the_boundary_document_quotes_the_prompts_verbatim() -> None:
    """`LLM_Boundary.md` 的附录抄了四份系统提示词的原文。

    抄下来的东西会脱节——改了代码里的提示词，文档还停在旧版本，而那份
    附录的全部价值就在于"这是原文，不是转述"。这条用例让脱节变成一次
    失败的测试，而不是被读者指出的一处不一致。

    提示词若确需修改，同步改文档即可；这条不阻止修改，只阻止**悄悄**修改。
    """
    from pathlib import Path

    from service.assistant.parsing import PARSE_SYSTEM_PROMPT

    doc = Path(__file__).resolve().parents[3] / "docs" / "02_Architecture" / (
        "LLM_Boundary.md"
    )
    text = doc.read_text(encoding="utf-8")

    for prompt in (
        REPHRASE_SYSTEM_PROMPT,
        REPHRASE_RETRY_SYSTEM_PROMPT,
        EXPLAIN_SYSTEM_PROMPT,
    ):
        assert prompt in text, prompt[:30]

    # 分类提示词是多行的，文档里逐行加了引用符号，故逐行核对
    for line in PARSE_SYSTEM_PROMPT.splitlines():
        if line.strip():
            assert line in text, line[:30]


# -- 一句话里的几件事（2026-09-15） ---------------------------------------------

_COMPOUND = "现在多少度啊 有点热 你可以帮我打开风扇嘛"
"""用户试用时的原句。拆句之前温度那一问被丢掉，复核又因整句含两件事判成分歧。"""


def _assistant_with_readings(
    llm: object | None = None,
) -> tuple[Assistant, VentilationController]:
    processor = SensorDataProcessor()
    for channel, value in ((TEMPERATURE_CHANNEL, 24.0), (HUMIDITY_CHANNEL, 61.0)):
        processor.handle_data_point(
            DataPoint(device_id="dev-1", channel=channel, value=value)
        )
    ventilation = VentilationController()
    assistant = Assistant(
        processor,
        lambda: ["dev-1"],
        ventilation=ventilation,
        llm=llm,  # type: ignore[arg-type]
    )
    return assistant, ventilation


def test_a_question_and_an_instruction_in_one_sentence_are_both_handled() -> None:
    assistant, ventilation = _assistant_with_readings()

    answer = assistant.ask(_COMPOUND)

    assert "24" in answer.text
    assert ventilation.settings.mode is FanMode.MANUAL_ON
    # 消费端靠 facts.applied 判断执行了没有，所以复合句带的是指令那一条
    assert answer.facts is not None
    assert answer.facts.applied is True


def test_only_the_instruction_clause_is_sent_for_review() -> None:
    """整句送去复核，模型只能回一个标签，挑中提问那半句就成了分歧。"""
    llm = _ScriptedLlm("fan_on")
    assistant, ventilation = _assistant_with_readings(llm)

    first = assistant.ask(_COMPOUND)

    assert llm.prompts == ["你可以帮我打开风扇嘛"]
    assert first.source is AnswerSource.PENDING
    assert "24" in first.text
    assert ventilation.settings.mode is FanMode.AUTO

    answer = _drain(assistant)

    assert isinstance(answer, Answer)
    # 迟到的答案会整条替换占位，已经答出的温度必须还在
    assert "24" in answer.text
    assert ventilation.settings.mode is FanMode.MANUAL_ON


def test_a_disagreeing_review_still_keeps_the_answered_question() -> None:
    llm = _ScriptedLlm("fan_state")
    assistant, ventilation = _assistant_with_readings(llm)

    assistant.ask(_COMPOUND)
    answer = _drain(assistant)

    assert isinstance(answer, Answer)
    assert "24" in answer.text
    assert "是想让我" in answer.text
    assert ventilation.settings.mode is FanMode.AUTO


def test_two_questions_in_one_sentence_are_both_answered() -> None:
    assistant, _ = _assistant_with_readings()

    answer = assistant.ask("现在温度多少，湿度呢")

    assert "24" in answer.text
    assert "61" in answer.text


def test_a_feeling_before_an_instruction_is_not_answered_separately() -> None:
    """"太热了"会被规则读成问是否超标，拆开单独答就平白多出一句。"""
    plain, _ = _assistant_with_readings()
    compound, ventilation = _assistant_with_readings()

    expected = plain.ask("把风扇打开").text
    answer = compound.ask("太热了，把风扇打开")

    assert answer.text == expected
    assert ventilation.settings.mode is FanMode.MANUAL_ON


def test_the_same_question_asked_twice_is_not_split() -> None:
    """后半句继承了温度，与前半句是同一个问题，整句照旧处理并带上余量。"""
    assistant, _ = _assistant_with_readings()

    answer = assistant.ask("现在温度多少，还差多少超限")

    assert answer.intent is not None
    assert answer.intent.wants_margin is True


def test_two_instructions_in_one_sentence_are_not_split() -> None:
    """两条指令一起下发，任何一条判错都会改设备状态——这类句子保持整句处理。"""
    assistant, ventilation = _assistant_with_readings()

    assistant.ask("打开风扇，通风阈值调到 28 度")

    assert ventilation.settings.temperature_max == 28.0
    assert ventilation.settings.mode is FanMode.AUTO


def test_a_threshold_instruction_keeps_its_number_after_splitting() -> None:
    assistant, ventilation = _assistant_with_readings()

    answer = assistant.ask("现在多少度 通风阈值调到 28 度")

    assert ventilation.settings.temperature_max == 28.0
    assert "24" in answer.text


# -- 删除请求：认出但拒绝（2026-09-18） ---------------------------------------


def test_a_delete_request_is_refused_without_touching_the_model() -> None:
    """与裸开关、播报同一档：规则已经认得很确定，而这句话是一条政策声明，
    唯一的要求是说得准。送去改写只会给它一个变软的机会。"""
    llm = _ScriptedLlm("我可以帮你清理一下旧数据")
    assistant, _ = _assistant(llm)

    answer = assistant.ask("把旧数据删了")

    assert answer.source is AnswerSource.TEMPLATE
    assert answer.text == phrasing.DELETE_REFUSAL_TEXT
    assert llm.submit_count == 0


def test_a_delete_request_mentioning_a_channel_is_not_answered_with_a_reading():
    """这是加这个意图的**具体**理由。数据在日常句子里紧挨着通道词，
    没有这个分支时"把噪声数据清一清"会被噪声分支抢走，
    于是一条要求删除的话拿回一个真实声压级——与 09-09"试一下播报能不能响"
    被答成噪声读数是同一种错。"""
    assistant, _ = _assistant()

    answer = assistant.ask("把噪声数据清一清")

    assert answer.text == phrasing.DELETE_REFUSAL_TEXT
    assert "76.3" not in answer.text


def test_a_delete_request_beside_an_instruction_executes_nothing() -> None:
    """最要紧的一条。一句话里同时有删除和一条真指令时，指令**不能**被执行——
    拆句在这里刻意不接管（删除段没有问句标记，只剩一件事），整句退回到
    删除分支，风扇一动不动。"""
    for question in (
        "清空历史记录，顺便把风扇关了",
        "把数据删了，然后把风扇打开",
    ):
        assistant, ventilation = _assistant_with_fan()
        before = ventilation.settings.mode

        answer = assistant.ask(question)

        assert answer.text == phrasing.DELETE_REFUSAL_TEXT, question
        assert ventilation.settings.mode is before, question


def test_a_question_sharing_the_sentence_with_a_delete_request_is_dropped() -> None:
    """已知局限，写下来免得被当成漏做：一句话里既问了问题又要求删除时，
    整句按删除处理，那个问题不作答。

    取舍是有意的——静悄悄答了半句、把删除请求当没看见，比少答一个问题糟：
    用户会以为删除也照做了。"""
    assistant, _ = _assistant()

    answer = assistant.ask("清空历史记录，现在噪声多少")

    assert answer.text == phrasing.DELETE_REFUSAL_TEXT
    assert "76.3" not in answer.text


# -- Answer.trace: a read-only record of every rewording (2026-09-23) -------


def test_the_trace_keeps_a_refused_attempt_and_the_retry_that_answered() -> None:
    """The web console shows what the exit checks stopped. The refused first
    attempt must survive into the answer the retry produced -- otherwise the
    one interception worth showing is exactly the one that disappears."""
    from service.assistant.models import CheckVerdict

    llm = _ScriptedLlm("噪声 76.3dB。请注意保持安静。", then="现在的噪声是 76.3dB。")
    assistant, _ = _assistant(llm)
    assistant.ask("现在噪声多少")
    answer = _drain(assistant)

    assert isinstance(answer, Answer)
    first, second = answer.trace
    assert first.reply == "噪声 76.3dB。请注意保持安静。"
    assert first.verdict is not CheckVerdict.ACCEPTED
    assert first.retry is False
    assert second.reply == "现在的噪声是 76.3dB。"
    assert second.verdict is CheckVerdict.ACCEPTED
    assert second.retry is True
    assert first.template == second.template


def test_the_trace_of_a_twice_refused_rewording_explains_the_template() -> None:
    llm = _ScriptedLlm(
        "噪声 76.3dB。请注意保持安静。", then="噪声 76.3dB。也请注意休息。"
    )
    assistant, _ = _assistant(llm)
    assistant.ask("现在噪声多少")
    answer = _drain(assistant)

    assert isinstance(answer, Answer)
    assert answer.source is AnswerSource.TEMPLATE
    assert len(answer.trace) == 2
    assert all(a.verdict.value != "accepted" for a in answer.trace)


def test_an_answer_without_a_model_has_an_empty_trace() -> None:
    assistant, _ = _assistant()
    assert assistant.ask("现在噪声多少").trace == ()


def test_a_new_question_does_not_inherit_the_previous_trace() -> None:
    """Pending state is discarded per question; the trace must be too, or a
    rewording refused for one question would be shown under the next."""
    llm = _ScriptedLlm("噪声 76.3dB。请注意保持安静。", then="现在的噪声是 76.3dB。")
    assistant, _ = _assistant(llm)
    assistant.ask("现在噪声多少")
    assistant.ask("现在噪声多少")  # abandons the first before any poll
    answer = _drain(assistant)
    assert isinstance(answer, Answer)
    # The second question's first attempt already gets the good reply
    # (the scripted client switches after one submit), so exactly one
    # attempt -- nothing carried over from the abandoned question.
    (only,) = answer.trace
    assert only.reply == "现在的噪声是 76.3dB。"
    assert only.retry is False

