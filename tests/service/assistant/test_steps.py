"""The step log: a read-only record of how each answer came about.

Added 2026-09-26 for the web console's live view
(docs/decisions/08-web.md). Two kinds of
guarantee are tested here:

- **The record is right.** Each path an answer can take leaves the steps a
  reader would expect, in order, under the right question.
- **The record decides nothing.** ``explain_checks`` shows all five exit
  checks, but its first failure must always be the check ``judge`` acted
  on -- otherwise the page would show a different reason from the one
  that actually applied.
"""

from device.sensors.channels import (
    HUMIDITY_CHANNEL,
    NOISE_CHANNEL,
    TEMPERATURE_CHANNEL,
)
from service.assistant import phrasing
from service.assistant.assistant import STEP_LOG_LIMIT, Assistant
from service.assistant.models import (
    AnswerSource,
    CheckVerdict,
    Intent,
    IntentKind,
    StepKind,
)
from service.assistant.retrieval import FactRetriever
from service.data_models import DataPoint
from service.sensor_data_processor import SensorDataProcessor
from service.ventilation_controller import FanMode, VentilationController


class _Llm:
    """Returns the next scripted reply for each submit, in two chunks."""

    def __init__(self, *replies: str) -> None:
        self._replies = list(replies)
        self._pending: list[str] = []
        self._busy = False

    def submit(self, prompt: str, system: str = "") -> bool:
        if self._busy:
            return False
        reply = self._replies.pop(0) if self._replies else ""
        half = max(1, len(reply) // 2)
        self._pending = [reply[:half], reply[half:]] if reply else []
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


class _Clock:
    def __init__(self) -> None:
        self.now = 1000

    def __call__(self) -> int:
        self.now += 5
        return self.now


def _processor() -> SensorDataProcessor:
    processor = SensorDataProcessor()
    for channel, value in (
        (TEMPERATURE_CHANNEL, 26.6),
        (HUMIDITY_CHANNEL, 58.8),
        (NOISE_CHANNEL, 49.5),
    ):
        processor.handle_data_point(
            DataPoint(device_id="dev-1", channel=channel, value=value)
        )
    return processor


def _assistant(llm: object | None = None) -> tuple[Assistant, VentilationController]:
    ventilation = VentilationController()
    assistant = Assistant(
        _processor(),
        lambda: ["dev-1"],
        ventilation=ventilation,
        llm=llm,  # type: ignore[arg-type]
        clock_ms=_Clock(),
    )
    return assistant, ventilation


def _finish(assistant: Assistant) -> list[object]:
    late = []
    for _ in range(50):
        answer = assistant.poll_rephrasing()
        if answer is not None:
            late.append(answer)
    return late


def _kinds(assistant: Assistant) -> list[StepKind]:
    return [step.kind for step in assistant.drain_steps()]


# -- one timeline per path ------------------------------------------------------


def test_a_refused_rewording_then_an_accepted_retry() -> None:
    assistant, _ = _assistant(
        _Llm("现在这里的温度是 26.6℃。请做好防暑降温措施。", "当前温度为 26.6 摄氏度。")
    )
    first = assistant.ask("现在多少度")
    late = _finish(assistant)
    steps = assistant.drain_steps()

    assert [s.kind for s in steps] == [
        StepKind.RECEIVED, StepKind.RULES, StepKind.FACTS, StepKind.TEMPLATE,
        StepKind.MODEL_SUBMIT, StepKind.ANSWERED,
        StepKind.MODEL_REPLY, StepKind.CHECKS, StepKind.RETRY,
        StepKind.MODEL_REPLY, StepKind.CHECKS, StepKind.ANSWERED,
    ]
    refused, accepted = [s for s in steps if s.kind is StepKind.CHECKS]
    assert refused.verdict is CheckVerdict.TOO_LONG
    assert [c.name for c in refused.checks if not c.passed] == ["length"]
    assert accepted.verdict is CheckVerdict.ACCEPTED
    assert all(c.passed for c in accepted.checks)
    # The immediate answer is not final; the late one is, and both carry
    # the same question id as every step.
    assert [s.final for s in steps if s.kind is StepKind.ANSWERED] == [False, True]
    assert {s.question_id for s in steps} == {first.question_id}
    assert [a.question_id for a in late] == [first.question_id]  # type: ignore[attr-defined]


def test_the_model_is_shown_only_the_template_sentence() -> None:
    assistant, _ = _assistant(_Llm("温度是 26.6℃。"))
    assistant.ask("现在多少度")
    steps = assistant.drain_steps()
    template = next(s for s in steps if s.kind is StepKind.TEMPLATE)
    submit = next(s for s in steps if s.kind is StepKind.MODEL_SUBMIT)
    assert submit.job == "rephrase"
    assert submit.text == template.text


def test_without_a_model_the_template_is_the_final_answer() -> None:
    assistant, _ = _assistant()
    assistant.ask("现在多少度")
    steps = assistant.drain_steps()
    assert [s.kind for s in steps][-2:] == [
        StepKind.MODEL_UNAVAILABLE, StepKind.ANSWERED
    ]
    assert steps[-1].final is True
    assert steps[-1].source is AnswerSource.TEMPLATE


def test_a_review_that_agrees_executes_the_rules_reading() -> None:
    assistant, ventilation = _assistant(_Llm("fan_on"))
    assistant.ask("打开风扇")
    _finish(assistant)
    steps = assistant.drain_steps()
    label = next(s for s in steps if s.kind is StepKind.LABEL)
    assert label.job == "review"
    assert label.note == "agree"
    executed = next(s for s in steps if s.kind is StepKind.EXECUTED)
    assert executed.intent == Intent(kind=IntentKind.FAN_ON)
    assert ventilation.settings.mode is FanMode.MANUAL_ON


def test_a_review_that_disagrees_asks_and_executes_nothing() -> None:
    assistant, ventilation = _assistant(_Llm("fan_state"))
    assistant.ask("风扇是不是可以开一下")
    _finish(assistant)
    kinds = _kinds(assistant)
    assert StepKind.EXECUTED not in kinds
    assert ventilation.settings.mode is FanMode.AUTO

    assistant.ask("是的")
    steps = assistant.drain_steps()
    confirmation = next(s for s in steps if s.kind is StepKind.CONFIRMATION)
    assert confirmation.note == "affirm"
    assert StepKind.EXECUTED in [s.kind for s in steps]
    assert ventilation.settings.mode is FanMode.MANUAL_ON


def test_a_silent_review_is_recorded_as_silent() -> None:
    assistant, _ = _assistant(_Llm(""))
    assistant.ask("打开风扇")
    _finish(assistant)
    label = next(s for s in assistant.drain_steps() if s.kind is StepKind.LABEL)
    assert label.note == "silent"


def test_a_classification_that_fails_leaves_the_immediate_answer_standing() -> None:
    # "最高是多少" names no channel: the rules ask back and the model is
    # asked to classify. An unusable label leaves the question-back as the
    # final answer, which the log has to say explicitly.
    assistant, _ = _assistant(_Llm("unknown"))
    assistant.ask("最高是多少")
    assert _finish(assistant) == []
    steps = assistant.drain_steps()
    label = next(s for s in steps if s.kind is StepKind.LABEL)
    assert label.job == "parse"
    assert label.note == "unusable"
    assert steps[-1].kind is StepKind.ANSWERED
    assert steps[-1].note == "immediate_stands"
    assert steps[-1].final is True


def test_a_new_question_marks_the_old_job_abandoned() -> None:
    assistant, _ = _assistant(_Llm("温度是 26.6℃。", "湿度是 58.8%RH。"))
    first = assistant.ask("现在多少度")
    second = assistant.ask("湿度多少")  # before the first reply was collected
    steps = assistant.drain_steps()
    abandoned = [s for s in steps if s.kind is StepKind.ABANDONED]
    assert len(abandoned) == 1
    assert abandoned[0].question_id == first.question_id
    assert second.question_id == first.question_id + 1


def test_a_compound_sentence_logs_each_part() -> None:
    assistant, _ = _assistant(_Llm("fan_on"))
    assistant.ask("现在多少度啊，有点热，帮我把风扇打开")
    _finish(assistant)
    steps = assistant.drain_steps()
    compound = next(s for s in steps if s.kind is StepKind.COMPOUND)
    assert compound.note == "1+1"
    rules = [s for s in steps if s.kind is StepKind.RULES]
    assert [r.intent.kind for r in rules if r.intent] == [
        IntentKind.CURRENT_VALUE, IntentKind.FAN_ON
    ]
    review = next(s for s in steps if s.kind is StepKind.MODEL_SUBMIT)
    # Only the instruction clause goes to the model, never the whole sentence.
    assert review.text == rules[1].text


def test_a_follow_up_records_what_memory_changed() -> None:
    assistant, _ = _assistant()
    assistant.ask("温度最高是多少")
    assistant.drain_steps()
    assistant.ask("噪声呢")
    context = [s for s in assistant.drain_steps() if s.kind is StepKind.CONTEXT]
    assert len(context) == 1
    assert context[0].note == "inherited_kind"
    assert context[0].intent == Intent(kind=IntentKind.MAXIMUM, channel=NOISE_CHANNEL)


# -- properties of the log itself ----------------------------------------------


def test_steps_are_numbered_and_timed_from_the_question() -> None:
    assistant, _ = _assistant(_Llm("温度是 26.6℃。"))
    assistant.ask("现在多少度")
    _finish(assistant)
    steps = assistant.drain_steps()
    assert [s.seq for s in steps] == list(range(1, len(steps) + 1))
    times = [s.at_ms for s in steps]
    assert times == sorted(times)
    assert steps[0].kind is StepKind.RECEIVED


def test_draining_empties_the_log() -> None:
    assistant, _ = _assistant()
    assistant.ask("现在多少度")
    assert assistant.drain_steps()
    assert assistant.drain_steps() == ()


def test_an_undrained_log_stays_bounded() -> None:
    # The desktop panel never drains; the log must not grow without limit.
    assistant, _ = _assistant()
    for _ in range(STEP_LOG_LIMIT):
        assistant.ask("现在多少度")
    assert len(assistant.drain_steps()) == STEP_LOG_LIMIT


def test_draining_or_not_does_not_change_any_answer() -> None:
    questions = ["现在多少度", "噪声呢", "打开风扇", "最高是多少", "你能干什么"]
    drained, _ = _assistant(_Llm("fan_on", "maximum noise"))
    kept, _ = _assistant(_Llm("fan_on", "maximum noise"))
    for question in questions:
        a = drained.ask(question)
        b = kept.ask(question)
        drained.drain_steps()
        assert (a.text, a.source, a.intent) == (b.text, b.source, b.intent)
        assert [(x.text, x.source) for x in _finish(drained)] == [  # type: ignore[attr-defined]
            (y.text, y.source) for y in _finish(kept)  # type: ignore[attr-defined]
        ]


# -- explain_checks shows what judge decided -----------------------------------


_REPLIES = (
    None, "", "好", "温度现在是 26.6℃。", "当前温度为 26.6 摄氏度。",
    "现在温度 27.1℃。", "温度 26.6℃，已经超标了。", "温度 26.6℃，一切正常。",
    "温度 26.6℃，请注意保暖。", "温度 26.6℃，建议开窗，目前舒适。",
    "现在这里的温度是 26.6℃，这个数值比较适合大家在站台等候列车。",
    "噪声 49.5dB，处于报警状态，请注意。", "噪声 49.5dB，未超标。",
    "3 个设备在线，温度 26.6℃。", "湿度 58.8%RH，偏高，记得除湿。",
)


def _all_facts() -> list[tuple[str, object]]:
    retriever = FactRetriever(_processor(), lambda: ["dev-1"], VentilationController())
    out: list[tuple[str, object]] = [("", None)]
    for kind in (IntentKind.CURRENT_VALUE, IntentKind.MAXIMUM, IntentKind.ALARM_STATE):
        for channel in (TEMPERATURE_CHANNEL, NOISE_CHANNEL):
            facts = retriever.retrieve(Intent(kind=kind, channel=channel))
            out.append((phrasing.render(facts), facts))
    return out


def test_the_first_failed_check_is_the_one_judge_names() -> None:
    compared = 0
    for template, facts in _all_facts():
        for reply in _REPLIES:
            for expanded in (False, True):
                _, _, verdict = phrasing.judge(
                    template, reply, facts, expanded=expanded  # type: ignore[arg-type]
                )
                checks = phrasing.explain_checks(
                    template, reply, facts, expanded=expanded  # type: ignore[arg-type]
                )
                if verdict in (CheckVerdict.NO_REPLY, CheckVerdict.TOO_SHORT):
                    assert checks == (), (template, reply)
                    continue
                assert [c.name for c in checks] == [
                    "grounding", "alarm", "judgement", "advice", "length"
                ]
                failed = [c for c in checks if not c.passed]
                if verdict is CheckVerdict.ACCEPTED:
                    assert failed == [], (template, reply, failed)
                else:
                    assert failed, (template, reply, verdict)
                    assert phrasing._CHECK_VERDICTS[failed[0].name] is verdict
                compared += 1
    assert compared > 100


def test_a_failed_check_says_what_it_found() -> None:
    template = "温度现在是 26.6℃。"
    facts = next(f for t, f in _all_facts() if t == template)
    checks = {
        c.name: c
        for c in phrasing.explain_checks(
            template, "温度 27.1℃，已经超标了，请注意。", facts  # type: ignore[arg-type]
        )
    }
    assert checks["grounding"].detail == "27.1"
    assert checks["alarm"].detail == "超标"
    assert "请注意" in checks["advice"].detail


def test_the_explain_job_is_exempt_from_the_length_cap() -> None:
    checks = phrasing.explain_checks(
        "短句。", "这是一句明显比模板长很多的解释性回答。", None, expanded=True
    )
    length = next(c for c in checks if c.name == "length")
    assert length.passed


def test_ungrounded_numbers_agrees_with_numbers_are_grounded() -> None:
    for _, facts in _all_facts():
        for reply in _REPLIES:
            if reply is None:
                continue
            assert phrasing.numbers_are_grounded(reply, facts) == (  # type: ignore[arg-type]
                not phrasing.ungrounded_numbers(reply, facts)  # type: ignore[arg-type]
            )
