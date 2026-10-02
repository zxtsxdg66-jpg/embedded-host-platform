"""The assistant facade: one question in, one :class:`Answer` out.

Wires the three stages together and owns the single rule that makes the
whole feature trustworthy: **the model never sees a reading, and never
supplies a number.** Retrieval reads the data layer, phrasing renders a
template, and only then may a model rephrase -- with its output checked
against the facts before it is accepted.

A model has exactly two jobs here, and both are language jobs:
:data:`JOB_REPHRASE` rewords a finished template answer, and
:data:`JOB_PARSE` classifies a question the keyword rules did not
recognise. Numbers, thresholds and the choice of what to answer stay in
code either way.

Answering is synchronous and fast because stages 1 and 2 are pure code.
No model call is folded into :meth:`ask` -- it would block the caller for
seconds. Model work is driven separately by :meth:`poll_rephrasing`,
which the composition root calls from the same loop that drives
everything else. A caller that ignores it simply gets rule-and-template
answers, which is the default and always correct.
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import replace

from core.models import ChannelId
from core.timestamps import monotonic_ms
from device.sensors.channels import (
    HUMIDITY_CHANNEL,
    NOISE_CHANNEL,
    TEMPERATURE_CHANNEL,
)
from service.assistant import control, parsing, phrasing
from service.assistant import intent as intent_rules
from service.assistant.control import ControlExecutor
from service.assistant.export_status_port import ExportStatus
from service.assistant.llm_port import LlmClient, NullLlmClient
from service.assistant.models import (
    Answer,
    AnswerSource,
    AnswerStep,
    CheckResult,
    CheckVerdict,
    Facts,
    Intent,
    IntentKind,
    RephraseAttempt,
    StepKind,
)
from service.assistant.retrieval import DeviceLister, FactRetriever
from service.sensor_data_processor import SensorDataProcessor
from service.ventilation_controller import VentilationController

REPHRASE_SYSTEM_PROMPT = (
    "你是地铁站环境监测系统的播报助手。"
    "把给你的一句话改写得更自然口语，控制在两句以内。"
    "严禁增删或改动任何数字、单位与判断结论，"
    "也不要补充系统行为、设备能力或任何未给出的信息。"
)
"""Fixed and short, in that order of importance.

Fixed, because Ollama reuses the KV cache for an identical prompt prefix:
measured on the target machine this took prefill from 74 to 740 tok/s and
first-token latency from 1.55 s to 0.16 s. Short, because prefill is the
dominant cost of a CPU-only model -- which is affordable here precisely
because no readings need to be stuffed into the context.
"""

TEASE_SYSTEM_PROMPT = (
    REPHRASE_SYSTEM_PROMPT
    + "原句是在对方说的体感与读数相反时轻轻调侃一句，改写时保留这种轻松的语气；"
    "照读数说，不要附和对方的感受，不要给任何建议。"
)
"""For a template that answers "好冷啊" at 34℃ (``phrasing.mismatch_kind``).

Added 2026-09-27 after the first smoke run: under the plain rephrase
prompt the model kept the facts and dropped the joke -- "你喊冷？这句我可
不太敢接" came back as "按数据判断已经是偏热了". A separate constant rather
than a sentence added to the shared one, so the ordinary rephrase keeps
its cached prefix. The checks are the same checks; the prompt only asks
for a tone, and what stops agreement or advice is still
``phrasing._advice_problem``."""

REPHRASE_RETRY_SYSTEM_PROMPT = (
    REPHRASE_SYSTEM_PROMPT
    + "上一次改写被系统退回了：它加进了原句没有的判断或建议。"
    "这次只调整语序和用词，不得出现任何原句没有的判断、评价、建议或提醒。"
)
"""Second attempt, sent only after the deterministic checks refused the
first one.

The judge stays in code. That is the whole difference between this and
asking the model to check itself before answering: a self-check is graded
by the model that just made the mistake, and it makes every request pay
twice. Here the grader is :func:`phrasing.choose` -- free, deterministic,
complete for numbers -- and only the refused answers pay.

Measured on 30 rewordings: 5 were refused (17%), a retry rescued 4 of them
(80%), and the average latency went from 1.8 s to 2.3 s. One rescue
mattered rather more than the others: "这个数值已经超出正常范围了" on a
49.5 dB reading against an 80 dB limit became a plain restatement.

One retry only. A second would be chasing a model that has now failed the
same check twice, and the template it falls back to is a correct answer."""

_CHANNEL_QUESTION_KINDS = frozenset(
    {
        IntentKind.CURRENT_VALUE,
        IntentKind.MINIMUM,
        IntentKind.MAXIMUM,
        IntentKind.AVERAGE,
        IntentKind.ALARM_STATE,
        IntentKind.THRESHOLD_INFO,
        IntentKind.SAMPLE_COUNT,
    }
)
"""换个通道重问一遍仍然说得通的问法。

风扇状态与设备列表不在其中：它们与通道无关，让"噪声呢"继承出一个
"噪声的风扇状态"只会得到一句谁也没问的话。"""

_FAN_ACTIONS = frozenset(
    {IntentKind.FAN_ON, IntentKind.FAN_OFF, IntentKind.FAN_AUTO}
)

FAN_TOPIC_SECONDS = 90
"""刚操作过或刚反问过风扇之后，一句"关了吧"还能被读成风扇指令的时长。

比通道记忆（180 s）短：记错通道只是答非所问，把一句无关的话读成开关风扇
却会真的动执行器。九十秒够接住一次对话里的追问，又不至于让几分钟后
一句"关了吧"莫名其妙地关掉风扇。"""

CHANNEL_MEMORY_SECONDS = 180
"""How long "那湿度呢" can still refer back to the previous question.

Three minutes is a demonstration's rhythm, not a measured constant. It is
short enough that a question asked after the operator has walked away is
not silently answered about a topic they have forgotten, and long enough
that a normal follow-up never has to repeat the channel. When it lapses
the behaviour is the pre-existing one -- the help text -- so the failure
mode of picking wrong is a re-ask, not a wrong number.
"""

EXPLAIN_SYSTEM_PROMPT = (
    "你是地铁站环境监测系统的播报助手。"
    "下面给你的是系统查到的全部事实，每行一条。"
    "用两到三句自然的中文把情况说清楚，可以取舍详略。"
    "只能使用列出的事实：不得出现任何未列出的数字，"
    "也不得下没有列出的结论，尤其不要判断是否超标、报警或故障。"
)
"""For the explain job. Same two properties as the rephrase prompt --
fixed, so Ollama reuses the KV cache, and short, because prefill dominates
on CPU -- but it asks for an account of the facts rather than a rewording
of one sentence.

The last clause exists because of a rehearsal on 2026-09-08 where the
model added "处于超标状态" to a maximum-value answer. A prompt is a
request, not a constraint, so the same failure is also refused at the
boundary by ``phrasing.choose`` -- this line only makes it rarer.
"""

EXPLAINED_KINDS = frozenset({IntentKind.ALARM_STATE, IntentKind.FAN_STATE})
"""Which questions get the whole fact list rather than one sentence.

Both hold appreciably more than their template prints: whether a channel
is over its limit involves the range and the distance to it, and the fan
answer turns on two thresholds and two readings while the template names
one reason. "最高值是多少" carries a single number and an explanation of it
would be padding, so it keeps the rephrase job.

**Kept narrow on measured grounds, not taste.** With ``CURRENT_VALUE``
included as well, the 65-question benchmark's median answer went from
3.7 s to 9.7 s -- and "现在温度多少" is the most-asked question in the set,
answered by a template that already states the reading and the distance to
the limit. Paying six seconds to add a sample count to it is a bad trade;
paying it to explain why the fan is running is not.
"""

_VENT_CHANNELS = (TEMPERATURE_CHANNEL, HUMIDITY_CHANNEL)
"""The channels a ventilation threshold exists for."""

_COMPOUND_QUESTION_KINDS = _CHANNEL_QUESTION_KINDS | {
    IntentKind.FAN_STATE,
    IntentKind.DEVICE_LIST,
}
"""拆句时能单独作答的提问种类。

帮助、裸开关、播报请求不在内：它们作为一句话里的一段时说明不了什么
（"你好"落到帮助，"开吧"要反问对象），单独答出来只会在正经回答之间
插一句不相干的话。"""

_SENTENCE_ENDS = "。！？!?…"


def _join_sentences(parts: Sequence[str]) -> str:
    """把几段模板答案接成一段，缺句号的补上句号。"""
    text = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if text and text[-1] not in _SENTENCE_ENDS:
            text += "。"
        text += part
    return text


def _with_prefix(answer: Answer, prefix: str) -> Answer:
    """在答案前面接上同一句话里已经答完的提问。"""
    if not prefix:
        return answer
    return replace(answer, text=_join_sentences([prefix, answer.text]))

_BARE_REPLY_SLACK = 3
"""How many characters may remain around a channel word for the sentence
to still count as a bare reply.

"噪声吧" leaves 吧, "温度的" leaves 的, "是湿度" leaves 是 -- all answers.
"现在噪声多少" leaves 现在多少, which is a question. Three characters is
the widest gap that keeps those two groups apart on the phrasings seen so
far; erring low is safe, because a rejected reply becomes a normal
question rather than a wrong action."""


def _is_bare_channel_reply(text: str) -> bool:
    """Whether ``text`` is just a channel name, give or take a particle."""
    stripped = text.strip().lower()
    for _, words in intent_rules.channel_vocabulary():
        for word in words:
            if word in stripped:
                rest = stripped.replace(word, "", 1)
                rest = re.sub(r"[\s，。、？?！!的是吧呢啊嘛]", "", rest)
                if len(rest) <= _BARE_REPLY_SLACK:
                    return True
    return False


CONTROL_CLARIFY_SECONDS = 25
"""How long a half-given *instruction* waits for its missing channel.

Deliberately shorter than :data:`CLARIFY_SECONDS`, because what a stale
settle costs is different in kind. An unanswered question that is honoured
too late yields a correct answer to the wrong question -- annoying, and
visible. An unanswered *instruction* honoured too late **changes a
setting**: someone says "把通风阈值调到 28", walks away, comes back and
types "湿度" meaning to ask about humidity, and a threshold moves.

Twenty-five seconds is about as long as a reply to a question still on
screen takes. Past that the instruction is dropped and has to be repeated,
which is the cheap failure. The echoed original sentence (see
``Facts.echo_question``) covers the same risk from the other side."""

CLARIFY_SECONDS = 60
"""How long a question the assistant asked back stays open.

Shorter than :data:`CHANNEL_MEMORY_SECONDS` on purpose. A remembered topic
is a hint the next question may or may not lean on; an unanswered question
is a commitment -- if it is still open when the user comes back minutes
later and says "温度", they get an answer to something they have forgotten
asking. Letting it lapse costs one re-ask; honouring a stale one produces
a correct answer to the wrong question, which is the harder mistake to
notice.
"""

JOB_REPHRASE = "rephrase"
JOB_EXPLAIN = "explain"
JOB_PARSE = "parse"
JOB_REVIEW = "review"
"""The jobs a model may be given, and the full extent of its role.

Worth stating together: one rewords a sentence the code already composed,
the other two pick a label from a fixed list -- :data:`JOB_PARSE` when the
rules found nothing, :data:`JOB_REVIEW` when they found an *instruction*
and the question is whether they read it right. None of them produces a
number, and none of them decides anything: a review can only withhold an
action or send it to the user for confirmation, never start one. That is
what makes it safe to hand all of them to a 4B model running on a laptop
CPU.
"""

STEP_LOG_LIMIT = 500
"""How many recorded steps are kept for :meth:`Assistant.drain_steps`.

Bounded because only the gateway drains them: the desktop panel never
does, and an unbounded log there would grow for as long as it runs. Five
hundred is far more than one question produces (under twenty), so a
consumer polling every cycle never loses one."""

ALL_CHANNELS = (TEMPERATURE_CHANNEL, HUMIDITY_CHANNEL, NOISE_CHANNEL)
"""What "三个都" expands to (docs/decisions/03-intent.md, item 2)."""

CHOICE_SECONDS = 60
"""How long a "你是想问 A 还是 B" question waits for its answer.

Same as :data:`CLARIFY_SECONDS`: the options are all read-only questions
or instructions the user will name explicitly, so a late answer costs a
re-ask at worst."""

CONTROL_CONFIRM_SECONDS = 25
"""确认问句的有效期，与 :data:`CONTROL_CLARIFY_SECONDS` 取同一个值。

理由也一样：过期的后果是设备状态被改，所以窗口要短。一句几分钟后飘来的
"是"不该把风扇打开。"""


class Assistant:
    """Answers environment questions from the platform's own data."""

    def __init__(
        self,
        processor: SensorDataProcessor,
        devices: DeviceLister,
        ventilation: VentilationController | None = None,
        llm: LlmClient | None = None,
        clock_ms: Callable[[], int] = monotonic_ms,
        exports: ExportStatus | None = None,
    ) -> None:
        self._retriever = FactRetriever(processor, devices, ventilation, exports)
        self._control = ControlExecutor(ventilation)
        self._llm: LlmClient = llm if llm is not None else NullLlmClient()
        self._pending_job: str = ""
        """Which model job is in flight: ``JOB_REPHRASE``, ``JOB_PARSE`` or
        empty for none. One at a time by construction -- there is a single
        client, and a new question cancels whatever the previous one
        started."""
        self._pending_facts: Facts | None = None
        self._pending_template: str = ""
        self._pending_intent: Intent | None = None
        self._pending_reply: str = ""
        self._pending_expanded: bool = False
        """Whether the job in flight is the explain one, whose output is
        exempt from the length cap."""
        self._retry_used: bool = False
        # Every rewording behind the answer being prepared, refused ones
        # included; handed out as Answer.trace. Read-only record (2026-09-23).
        self._pending_attempts: list[RephraseAttempt] = []
        """Whether this question has already had its one retry."""
        self._pending_placeholder: bool = False
        """Whether what ``ask`` returned was :data:`phrasing.THINKING_TEXT`.

        Read when a parse job comes back empty-handed: a placeholder has to
        be replaced by *something*, while a clarification question is a
        real answer and must be left standing."""
        self._pending_question: str = ""
        """The sentence a parse job is classifying. Kept because a control
        intent's *value* is read from the user's own words, never from the
        model's reply -- see ``control.extract_value``."""
        self._clock_ms = clock_ms
        self._pending_clarify: Intent | None = None
        self._pending_clarify_ms: int = 0
        self._pending_clarify_question: str = ""
        self._pending_review: Intent | None = None
        """规则判成指令、正在等模型复核的那一条。

        它**还没有被执行**——这是整个复核机制的要点：等待期间设备状态不变，
        用户看到的是一句占位（:data:`phrasing.REVIEW_WAIT_TEXT`）。"""
        self._pending_review_question: str = ""
        self._pending_confirm: Intent | None = None
        self._pending_confirm_question: str = ""
        self._pending_prefix: str = ""
        """复合句里已经答完的提问部分，等复核结果回来时接在前面。

        界面会用迟到的答案**整条替换**先前那条占位，不带上这一段，
        已经显示出来的温度读数会在几秒后凭空消失。"""
        self._pending_confirm_ms: int = 0
        self._pending_choice: tuple[Intent, ...] = ()
        """模型拿不准时给出的几个候选，正在等用户挑（docs/decisions/03-intent.md）。"""
        self._pending_choice_ms: int = 0
        self._pending_choice_question: str = ""
        """复核发现分歧后，挂起等用户点头的那一条指令。

        与 ``_pending_clarify`` 分开是因为两者问的不是一件事：那个问"哪个通道"，
        补的是指令缺的一半；这个问"你是不是要我这么做"，补的是**授权**。
        合并会让一句"温度"既能补通道又能算同意。"""
        self._settled_question: str = ""
        """The question waiting for a channel, and when it was asked.

        The other half of the same conversational state as
        ``_last_channel``: that one remembers what *was* answered, this one
        remembers what was not.
        """
        self._last_channel: ChannelId | None = None
        self._last_channel_ms: int = 0
        self._fan_topic_ms: int = 0
        """上一次话题落在风扇上的时刻。

        反问"是要开关风扇吗"之后，以及每次真正操作过风扇之后都会刷新。
        它让紧接着的一句"关了吧"不必再点名风扇——话题已经定死了。"""
        self._last_kind: IntentKind | None = None
        """上一次回答的是哪一类问题。

        与 ``_last_channel`` 共用同一个时间戳与有效期——它们是同一段上下文的
        两半：一半让"最高呢"知道问的是哪个通道，另一半让"噪声呢"知道问的是
        最高值。只做前一半时，"温度最高值是多少 → 噪声呢"答的是噪声当前值：
        数字是真的，答的却是另一个问题。"""
        """What the previous question was about, and when.

        This is the whole of the assistant's conversational memory, and it
        is held **here rather than given to the model**: resolving "那湿度
        呢" needs one remembered word, not a transcript. Feeding history to
        a 4B model would make every request longer and slower, would let
        an earlier label bias the next classification, and would put the
        thing that decides what a sentence means back into the part of the
        system that cannot be tested for it. A timeout applies for the
        same reason a person would ask "湿度什么" after a long silence --
        see :data:`CHANNEL_MEMORY_SECONDS`.
        """
        # -- step log (2026-09-26) -------------------------------------------
        # A read-only record of how each answer came about, drained by the
        # gateway for the web console (docs/decisions/08-web.md).
        # Nothing below reads it back: every branch decides exactly as it
        # did before the log existed.
        self._steps: deque[AnswerStep] = deque(maxlen=STEP_LOG_LIMIT)
        self._last_qid = 0
        self._active_qid = 0
        """The question the steps being recorded right now belong to: the
        one being asked inside :meth:`ask`, or the one whose model job is
        being collected inside :meth:`poll_rephrasing`."""
        self._pending_qid = 0
        """The question the model job in flight belongs to."""
        self._qid_start_ms: dict[int, int] = {}
        self._qid_seq: dict[int, int] = {}

    @property
    def llm(self) -> LlmClient:
        """The attached model client (``NullLlmClient`` when none was given)."""
        return self._llm

    def ask(self, question: str) -> Answer:
        """Answer ``question`` from rules, data and templates. Never raises.

        Returns immediately with a complete, correct answer -- stages 1 and
        2 are pure code and a model, if attached, is never waited on. What
        the model then does depends on how the rules fared:

        - **Rules recognised it.** A rephrasing request is started; nicer
          wording of the same facts arrives later via
          :meth:`poll_rephrasing`.
        - **Rules did not.** The help text is returned, and the model is
          asked to *classify* the question instead. If it manages to, a
          real answer -- retrieved and templated by the same code as any
          other -- replaces the help text through the same poll.

        Either way one model request is started at most, and a caller that
        never polls simply keeps what ``ask`` returned.
        """
        qid = self._begin_question(question)
        answer = self._answer(question)
        in_flight = bool(self._pending_job) and self._pending_qid == qid
        self._log(
            StepKind.ANSWERED,
            text=answer.text,
            source=answer.source,
            final=not in_flight,
        )
        return replace(answer, question_id=qid)

    # -- step log (2026-09-26) ----------------------------------------------

    def drain_steps(self) -> tuple[AnswerStep, ...]:
        """Every step recorded since the last call, oldest first.

        For the gateway's live view of how an answer came about. Draining
        is the only way steps leave the log, and nothing inside the
        assistant reads them, so a caller that never drains changes nothing
        but the log's contents (bounded by :data:`STEP_LOG_LIMIT`).
        """
        # popleft rather than copy-then-clear: the gateway asks on its
        # request thread while the poll loop drains, and a step appended
        # between a copy and a clear would be lost. deque's popleft and
        # append are each atomic.
        steps: list[AnswerStep] = []
        while True:
            try:
                steps.append(self._steps.popleft())
            except IndexError:
                return tuple(steps)

    def _begin_question(self, question: str) -> int:
        self._last_qid += 1
        qid = self._last_qid
        self._active_qid = qid
        self._qid_start_ms[qid] = self._clock_ms()
        self._qid_seq[qid] = 0
        # Keep the bookkeeping for the current question and the one whose
        # model job may still be running; older ones can no longer log.
        for old in [k for k in self._qid_start_ms if k not in (qid, self._pending_qid)]:
            del self._qid_start_ms[old]
            self._qid_seq.pop(old, None)
        self._log(StepKind.RECEIVED, text=question)
        return qid

    def _log(
        self,
        kind: StepKind,
        *,
        qid: int | None = None,
        text: str = "",
        job: str = "",
        note: str = "",
        intent: Intent | None = None,
        facts: Facts | None = None,
        source: AnswerSource | None = None,
        checks: tuple[CheckResult, ...] = (),
        verdict: CheckVerdict | None = None,
        final: bool = False,
    ) -> None:
        """Append one step to the log. Records only; decides nothing."""
        owner = self._active_qid if qid is None else qid
        if owner not in self._qid_start_ms:
            return
        seq = self._qid_seq.get(owner, 0) + 1
        self._qid_seq[owner] = seq
        self._steps.append(AnswerStep(
            question_id=owner,
            seq=seq,
            at_ms=self._clock_ms() - self._qid_start_ms[owner],
            kind=kind,
            text=text,
            job=job,
            note=note,
            intent=intent,
            facts=facts,
            source=source,
            checks=checks,
            verdict=verdict,
            final=final,
        ))

    def _log_context(self, before: Intent, after: Intent, reason: str) -> None:
        """Record that conversational memory changed what the rules read."""
        if after != before:
            self._log(StepKind.CONTEXT, intent=after, note=reason)

    def _answer(self, question: str) -> Answer:
        """The body of :meth:`ask`, which wraps it with the step log."""
        confirmed = self._settle_confirmation(question)
        if confirmed is not None:
            return confirmed
        chosen = self._settle_choice(question)
        if chosen is not None:
            return chosen
        every = self._settle_clarification_all(question)
        if every is not None:
            return every
        if intent_rules.is_manipulation(question):
            return self._answer_manipulation(question)
        return self._answer_body(question)

    def _answer_body(self, question: str) -> Answer:
        """系统没有的东西先说明，其余交给规则。"""
        absent = intent_rules.absent_mentions(question)
        if absent:
            return self._answer_absent(question, absent)
        return self._answer_rules(question)

    def _answer_manipulation(self, question: str) -> Answer:
        """冒充身份、要求忽略规则：先说一句权限不是一句话能改的，再照常答剩下的。

        2026-09-27。剩下的认不出（落到帮助）或只是一句裸开关，就只回那一句加能力简介，
        **不交给模型**——整句话的用意就是让模型换个身份，没有理由把它送过去。
        剩下的部分照常走规则、复核与执行；说明接在最前面，
        做法与 :meth:`_answer_absent` 相同。
        """
        kept = intent_rules.strip_manipulation(question)
        self._log(StepKind.MANIPULATION, text=kept)
        leftover = (
            intent_rules.recognise(kept, self._recent_channel()) if kept else None
        )
        if leftover is None or (
            leftover.kind in (IntentKind.HELP, IntentKind.BARE_SWITCH)
            and not intent_rules.absent_mentions(kept)
        ):
            self._discard_pending()
            self._pending_clarify = None
            text = phrasing.MANIPULATION_TEXT + phrasing.CAPABILITY_BRIEF
            self._log(StepKind.TEMPLATE, text=text)
            return Answer(
                text=text,
                source=AnswerSource.TEMPLATE,
                intent=Intent(kind=IntentKind.HELP),
                facts=None,
            )
        return self._with_notice(phrasing.MANIPULATION_TEXT, self._answer_body(kept))

    def _with_notice(self, notice: str, answer: Answer) -> Answer:
        """把一句说明接在回答前面，并让还在飞的模型工作不把它冲掉。

        复核的结果到时经 ``_pending_prefix`` 接在说明后面；改写与分类这一轮放弃——
        它们回来的整句会把说明换掉。"""
        if self._pending_job == JOB_REVIEW:
            self._pending_prefix = _join_sentences([notice, self._pending_prefix])
        elif self._pending_job:
            self._discard_pending(abandoned=False)
        return _with_prefix(answer, notice)

    def _answer_absent(self, question: str, absent: list[str]) -> Answer:
        """句子里有系统没有的东西：先说明做不了，再只按剩下的那一段作答。

        2026-09-26 外部题库查出的问题：规则整句读，"开风扇，顺便把灯关了"里属于灯的
        "关"被算到了风扇头上，"把风扇打开，再把空调调到24度"读成了改通风阈值，
        而做不了的那一半从来不说。改法是先把只关于没有的东西的那几段去掉
        （``intent.strip_absent``），剩下的照常走规则、复核与执行，说明放在最前面。

        剩下的认不出（落到帮助）或只是一句裸开关，就只回说明，不再交给模型猜：
        那句话里系统能做的事一件也没有。例外是"空调现在几度"这类点了通道的提问，见下。

        说明要一直留在回答里，所以这一轮不送改写——改写回来的整句会把它换掉。
        复核照送，结果到时经 ``_pending_prefix`` 接在说明后面。
        """
        kept = intent_rules.strip_absent(question)
        devices = intent_rules.absent_devices(absent)
        fan_speed = intent_rules.FAN_SPEED in absent
        measures = [
            name
            for name in absent
            if name not in devices and name != intent_rules.FAN_SPEED
        ]
        self._log(StepKind.ABSENT, note="、".join(absent), text=kept)
        station_reading = False
        leftover = (
            intent_rules.recognise(kept, self._recent_channel()) if kept else None
        )
        if leftover is None or leftover.kind in (
            IntentKind.HELP,
            IntentKind.BARE_SWITCH,
        ):
            # "空调现在温度是多少"：去掉空调那一段就什么也不剩了，但它确实在问温度，
            # 此前答的也是站内温度。只提到了没有的**设备**、整句是一个点了通道的提问时，
            # 说明之后照答站内读数；"室外温度多少"提到的是测量项，不在此列——
            # 拿站内温度去答室外温度就是答错了。
            whole = intent_rules.recognise(question, self._recent_channel())
            if (
                devices
                and not measures
                and not fan_speed
                and whole.kind in _CHANNEL_QUESTION_KINDS
                and whole.channel is not None
                and intent_rules.is_question_clause(question)
                and not intent_rules.asks_to_change(question)
            ):
                kept = question
                leftover = whole
                station_reading = True
        if leftover is None or leftover.kind in (
            IntentKind.HELP,
            IntentKind.BARE_SWITCH,
        ):
            self._discard_pending()
            self._pending_clarify = None
            text = phrasing.absent_notice(
                devices, measures, partial=False, fan_speed=fan_speed
            )
            self._log(StepKind.TEMPLATE, text=text)
            return Answer(
                text=text,
                source=AnswerSource.TEMPLATE,
                intent=Intent(kind=IntentKind.HELP),
                facts=None,
            )
        notice = phrasing.absent_notice(
            devices,
            measures,
            partial=True,
            fan_speed=fan_speed,
            station_reading=station_reading,
        )
        return self._with_notice(notice, self._answer_rules(kept))

    def _answer_rules(self, question: str) -> Answer:
        """规则、复核、执行与检索那一整段。

        :meth:`_answer` 在几种待答状态都没接住后调用。"""
        compound = self._split_compound(question)
        if compound is not None:
            return self._answer_compound(*compound)
        recognised = intent_rules.recognise(question, self._recent_channel())
        self._log(StepKind.RULES, intent=recognised)
        before = recognised
        recognised = self._inherit_kind(question, recognised)
        self._log_context(before, recognised, "inherited_kind")
        before = recognised
        recognised = self._settle_bare_switch(question, recognised)
        self._log_context(before, recognised, "fan_topic")
        # Settling runs before the control split, not after it: a pending
        # instruction is completed by a bare channel word, and that word
        # classifies as a plain question. Checking CONTROL_KINDS first would
        # route it to retrieval and drop the instruction on the floor.
        self._settled_question = ""
        before = recognised
        recognised = self._settle_clarification(recognised, question)
        self._log_context(before, recognised, "clarification")
        if (
            recognised.kind is IntentKind.SET_VENT_THRESHOLD
            and len(intent_rules.named_channels(question)) > 1
        ):
            # 一句话要改两个通风阈值（"温度和湿度阈值都调到 30 度"）：原先只改了
            # 第一个通道、不提第二个。指令不展开（docs/decisions/03-intent.md 3.1），
            # 于是把通道清空，走既有的"你要调的是温度还是湿度"反问，一次只改一个。
            before = recognised
            recognised = replace(recognised, channel=None)
            self._log_context(before, recognised, "multi_channel_instruction")
        if recognised.kind in control.CONTROL_KINDS:
            if recognised.kind in _FAN_ACTIONS:
                self._fan_topic_ms = self._clock_ms()
            self._pending_clarify = None
            # The value is read from whichever sentence *carried* it -- the
            # original when this is a settled clarification. The one-word
            # reply supplies the channel and nothing else, which is the
            # whole point: no number ever enters through the back door.
            source_text = self._settled_question or question
            # 一句补全了通道的回答（"温度"）不再送复核：它补的是上一条指令
            # 缺的那一半，而那一条已经裁决过了。单独拿"温度"去问模型，
            # 得到的必然是"这是在问当前温度"，于是每一次补全都会被读成分歧。
            settled = bool(self._settled_question)
            if not settled and self._start_review(recognised, source_text):
                return Answer(
                    text=phrasing.REVIEW_WAIT_TEXT,
                    source=AnswerSource.PENDING,
                    intent=recognised,
                    facts=None,
                )
            return self._perform_control(
                recognised, source_text, AnswerSource.TEMPLATE
            )
        expanded = self._expand_channels(recognised, question)
        if expanded:
            self._log(StepKind.EXPAND, note=str(len(expanded)), intent=expanded[0])
            return self._answer_compound(expanded, None, log_compound=False)

        self._remember_channel(recognised.channel)

        facts = self._retriever.retrieve(recognised)
        text = phrasing.render(facts)
        self._log(StepKind.FACTS, intent=recognised, facts=facts)
        self._log(StepKind.TEMPLATE, text=text)

        if facts.needs_channel:
            # Ask back, and remember what for -- but let the model try the
            # sentence as well. "这半天里最闹腾的时候到底是多少" names its
            # channel in a way no keyword matches, and a model that reads
            # 闹腾 as noise answers it outright; the question back is what
            # the user sees meanwhile, and what stands if the model cannot.
            # Asking and guessing are not alternatives here: one of them
            # arrives instantly and the other replaces it or does not.
            #
            # The clarification itself is never sent for rewording. A
            # reworded question is a different question, and the one thing
            # this text has to do exactly is name the three words it wants
            # back.
            self._pending_clarify = recognised
            self._pending_clarify_ms = self._clock_ms()
            self._start_parsing(question)
            return Answer(
                text=text,
                source=AnswerSource.TEMPLATE,
                intent=recognised,
                facts=facts,
            )

        # 问法在**答出来之后**才记：以反问收场的那一轮什么也没回答，
        # 把它的问法留下，会让两轮后一句"温度"莫名其妙地接上那个被丢弃的问题
        # ——而丢弃它正是待答机制的用意。通道记忆不同，它记的是话题，
        # 话题在反问时确实已经建立。
        self._remember_kind(recognised.kind)

        if recognised.kind is IntentKind.BARE_SWITCH:
            # 反问之后把话题钉在风扇上，下一句"关了吧"才接得住。
            self._fan_topic_ms = self._clock_ms()
        if recognised.kind in (
            IntentKind.BARE_SWITCH,
            IntentKind.ANNOUNCE_REQUEST,
            IntentKind.DELETE_REQUEST,
            IntentKind.CHANNEL_SET_REQUEST,
            IntentKind.ALARM_OFF_REQUEST,
            IntentKind.IDENTITY,
            IntentKind.CLOUD_VIEW_HINT,
        ):
            # Neither rephrased nor sent for classification: the rules
            # already matched with confidence, and the text is a policy
            # statement whose only requirement is to stay accurate.
            return Answer(
                text=text,
                source=AnswerSource.TEMPLATE,
                intent=recognised,
                facts=facts,
            )

        if recognised.kind is IntentKind.HELP:
            # 明确问"你能干什么"的那一类由规则直接命中，走的也是这条分支，
            # 但它不该被当成没听懂——用问句本身区分：能力清单是它要的答案。
            asked_for_help = intent_rules.asks_for_help(question)
            if asked_for_help:
                return Answer(
                    text=text,
                    source=AnswerSource.FALLBACK,
                    intent=recognised,
                    facts=facts,
                )
            if self._start_parsing(question):
                self._pending_placeholder = True
                return Answer(
                    text=phrasing.THINKING_TEXT,
                    source=AnswerSource.PENDING,
                    intent=recognised,
                    facts=facts,
                )
            # 没有模型可问，就没有东西会来替换占位句。此时那张清单仍是
            # 当下最有用的答复。
            return Answer(
                text=text,
                source=AnswerSource.FALLBACK,
                intent=recognised,
                facts=facts,
            )

        self._start_rephrasing(text, facts, recognised)
        return Answer(
            text=text,
            source=AnswerSource.TEMPLATE,
            intent=recognised,
            facts=facts,
        )

    # -- 一句话里的几件事（2026-09-15） --------------------------------------

    def _split_compound(
        self, question: str
    ) -> tuple[list[Intent], tuple[Intent, str] | None] | None:
        """把一句话拆成几段提问加至多一条指令；不值得拆时返回 None。

        规则一次只认一个意图，风扇分支又排在通道之前，所以"现在多少度啊
        有点热 你可以帮我打开风扇嘛"原先整句判成开风扇，温度那一问被丢掉；
        复核再把整句交给模型，模型挑了前半句答"当前温度"，与规则不一致，
        于是用户收到一句莫名的"你是想让我把风扇切到手动常开吗"。

        拆句**只在确有两件事时**才接管，其余情况返回 None、整句照旧处理，
        这是改动面能控制住的前提。判定条件：

        - 提问段要被规则认成 :data:`_COMPOUND_QUESTION_KINDS` 之一、需要通道的
          要有通道，并且带问句标记（见 ``intent._QUESTION_MARKERS``）；
          "太热了，把风扇打开"里的"太热了"因此只是铺垫，整句仍是一条指令。
        - 同一个问题问两遍（种类与通道都相同）算一件事——"现在温度多少，
          还差多少超限"的后半句继承了温度，与前半句合并后只剩一件，整句照旧。
        - **指令至多一条。**两条指令一句话下发，任何一条判错都会改设备状态，
          而用户是一次读完回显的；这种句子不拆，按原来的整句优先级处理。

        后一段没点名通道时沿用前一段的通道（"噪声最高多少，平均呢"），
        只点了通道的省略句沿用前一段的问法（"温度最高多少，湿度呢"），
        与跨轮追问是同一套规则，只是记忆的范围缩到一句话之内。
        """
        clauses = intent_rules.split_clauses(question)
        if len(clauses) < 2:
            return None
        questions: list[Intent] = []
        instruction: tuple[Intent, str] | None = None
        channel = self._recent_channel()
        for clause in clauses:
            recognised = intent_rules.recognise(clause, channel)
            if recognised.kind in control.CONTROL_KINDS:
                if instruction is not None:
                    return None
                instruction = (recognised, clause)
                continue
            if recognised.kind not in _COMPOUND_QUESTION_KINDS:
                continue
            needs_channel = recognised.kind in _CHANNEL_QUESTION_KINDS
            if needs_channel and recognised.channel is None:
                continue
            if not intent_rules.is_question_clause(clause):
                continue
            if (
                questions
                and recognised.kind is IntentKind.CURRENT_VALUE
                and questions[-1].kind in _CHANNEL_QUESTION_KINDS
                and intent_rules.is_bare_channel_question(clause)
            ):
                recognised = replace(recognised, kind=questions[-1].kind)
            named = intent_rules.named_channels(clause)
            if len(named) > 1:
                for each in named:
                    self._merge_question(questions, replace(recognised, channel=each))
            else:
                self._merge_question(questions, recognised)
            channel = recognised.channel or channel
        if len(questions) + (instruction is not None) < 2:
            return None
        return questions, instruction

    @staticmethod
    def _merge_question(questions: list[Intent], recognised: Intent) -> None:
        """同种类同通道的并成一个，附带的"要余量""问过去"标记取并集。"""
        for index, earlier in enumerate(questions):
            if (earlier.kind, earlier.channel) == (recognised.kind, recognised.channel):
                questions[index] = replace(
                    earlier,
                    wants_margin=earlier.wants_margin or recognised.wants_margin,
                    past_scoped=earlier.past_scoped or recognised.past_scoped,
                )
                return
        questions.append(recognised)

    def _answer_compound(
        self,
        questions: list[Intent],
        instruction: tuple[Intent, str] | None,
        log_compound: bool = True,
    ) -> Answer:
        """先答提问，再处理指令，合成一条回答。

        提问部分只用模板，不送模型改写：几段事实拼成的一句话没有单一的
        ``Facts`` 可供接地校验对照，而放宽校验去迁就它，等于为了措辞
        拆掉"数字只来自事实"这道闸。

        指令照常复核，但送给模型的**只有指令那一段**。整句送过去，模型
        本就只能回一个标签，它挑中提问那半句就会被判成分歧——这正是拆句
        要消除的那句莫名反问。

        返回的 ``intent``/``facts`` 取指令那一条（有指令时），否则取第一个
        提问：消费端据此判断"执行了没有"（``facts.applied``）与上板显示，
        二者都只认得单个意图。
        """
        self._pending_clarify = None
        if log_compound:
            self._log(
                StepKind.COMPOUND,
                note=f"{len(questions)}+{0 if instruction is None else 1}",
            )
        parts: list[str] = []
        every: list[Facts] = []
        first: Answer | None = None
        for recognised in questions:
            facts = self._retriever.retrieve(recognised)
            text = phrasing.render(facts)
            every.append(facts)
            self._log(StepKind.RULES, intent=recognised)
            self._log(StepKind.FACTS, intent=recognised, facts=facts)
            self._log(StepKind.TEMPLATE, text=text)
            parts.append(text)
            if first is None:
                first = Answer(
                    text=text,
                    source=AnswerSource.TEMPLATE,
                    intent=recognised,
                    facts=facts,
                )
            self._remember_channel(recognised.channel)
            self._remember_kind(recognised.kind)
        prefix = _join_sentences(parts)

        if instruction is None:
            # 与普通提问一样，新问题放弃上一句还在飞的模型工作；普通提问
            # 靠 _start_rephrasing 顺手做掉，这里不改写，得自己做。
            self._discard_pending()
            assert first is not None  # 至少两件事且没有指令，提问必然非空
            return replace(
                first, text=prefix, all_facts=tuple(every) if len(every) > 1 else ()
            )

        recognised, clause = instruction
        self._log(StepKind.RULES, intent=recognised, text=clause)
        if recognised.kind in _FAN_ACTIONS:
            self._fan_topic_ms = self._clock_ms()
        if self._start_review(recognised, clause):
            self._pending_prefix = prefix
            return Answer(
                text=_join_sentences([prefix, phrasing.REVIEW_WAIT_TEXT]),
                source=AnswerSource.PENDING,
                intent=recognised,
                facts=None,
            )
        return _with_prefix(
            self._perform_control(recognised, clause, AnswerSource.TEMPLATE),
            prefix,
        )

    # -- conversational memory --------------------------------------------

    def _settle_bare_switch(self, question: str, recognised: Intent) -> Intent:
        """话题已在风扇上时，把一句没点名的开关话读成指令。

        触发条件是话题新鲜——刚反问过，或刚操作过风扇。过期之后
        "关了吧"重新变回一句需要反问的话，因为那时它可能在说别的东西。
        """
        if recognised.kind not in (IntentKind.BARE_SWITCH, IntentKind.HELP):
            return recognised
        if not self._fan_topic_ms:
            return recognised
        if self._clock_ms() - self._fan_topic_ms > FAN_TOPIC_SECONDS * 1000:
            return recognised
        if intent_rules.names_something_else(question):
            # "有没有开关开着""窗户有没有打开的"：话题虽在风扇上，这句话点的却是别的东西
            # （2026-09-26 外部题库快照对照查出，2026-09-27 修）。
            return recognised
        direction = intent_rules.bare_switch_direction(question)
        if direction is None:
            return recognised
        return Intent(kind=direction)

    def _inherit_kind(self, question: str, recognised: Intent) -> Intent:
        """给"只点了个通道"的省略句补回上一轮的问法。

        只在两个条件同时成立时生效：句子确实只点了通道（由
        ``intent.is_bare_channel_question`` 判定），且记忆里那个问法是同一类
        可以换通道重问的问题。风扇状态、设备列表这些与通道无关的问法不参与，
        否则"噪声呢"会继承出一个说不通的意图。
        """
        if self._last_kind is None or recognised.channel is None:
            return recognised
        if recognised.kind is not IntentKind.CURRENT_VALUE:
            return recognised
        if self._last_kind not in _CHANNEL_QUESTION_KINDS:
            return recognised
        if self._clock_ms() - self._last_channel_ms > CHANNEL_MEMORY_SECONDS * 1000:
            return recognised
        if not intent_rules.is_bare_channel_question(question):
            return recognised
        return replace(recognised, kind=self._last_kind)

    def _remember_kind(self, kind: IntentKind) -> None:
        """记下这一轮问的是哪一类，供下一句"噪声呢"继承。

        只记可以换通道重问的那几类；帮助、反问、裸开关这些记下来毫无用处，
        而且会让下一句省略问句继承出一个说不通的意图。"""
        if kind in _CHANNEL_QUESTION_KINDS:
            self._last_kind = kind

    def _recent_channel(self) -> ChannelId | None:
        """The previous question's channel, if it is still recent."""
        if self._last_channel is None:
            return None
        if self._clock_ms() - self._last_channel_ms > CHANNEL_MEMORY_SECONDS * 1000:
            return None
        return self._last_channel

    # -- several channels in one sentence; choosing between readings --------

    def _expand_channels(self, recognised: Intent, question: str) -> list[Intent]:
        """One sentence, several channels: one intent per channel, or none.

        Three cases, all read-only questions (docs/decisions/03-intent.md 3.1):

        - the sentence names two or more channels by their proper names
          ("温度湿度噪声是多少") -- the rules used to keep the first and drop
          the rest without a word;
        - it asks for all of them ("三个都说一下"); when it states no
          question of its own, the previous question's kind carries over,
          otherwise it is the current reading;
        - it asks how many readings were recorded without naming a channel.

        Instructions, the fan and the device list are never expanded.
        """
        kind = recognised.kind
        if kind in _CHANNEL_QUESTION_KINDS:
            named = intent_rules.named_channels(question)
            if len(named) > 1:
                return [replace(recognised, channel=c) for c in named]
            # 口语里并列的几个通道（"又热又闷吗""有多吵有多热"）：只在确实是问句、
            # 或带"都说说"时展开，感叹句不展开（歧义题库调参集，2026-09-26）。
            spoken = intent_rules.colloquial_channels(question)
            if len(spoken) > 1 and (
                intent_rules.is_question_clause(question)
                or intent_rules.mentions_all_words(question)
            ):
                return [replace(recognised, channel=c) for c in spoken]
            if kind is IntentKind.SAMPLE_COUNT and recognised.channel is None:
                return [replace(recognised, channel=c) for c in ALL_CHANNELS]
        if not intent_rules.asks_all_channels(question):
            return []
        if kind in _CHANNEL_QUESTION_KINDS:
            return [replace(recognised, channel=c) for c in ALL_CHANNELS]
        if kind is not IntentKind.HELP:
            return []
        recent = (
            self._last_kind is not None
            and self._clock_ms() - self._last_channel_ms
            <= CHANNEL_MEMORY_SECONDS * 1000
        )
        carried = self._last_kind if recent and self._last_kind else None
        return [
            Intent(kind=carried or IntentKind.CURRENT_VALUE, channel=c)
            for c in ALL_CHANNELS
        ]

    def _settle_choice(self, question: str) -> Answer | None:
        """接住用户对"你是想问 A 还是 B"的回答（docs/decisions/03-intent.md）。

        依次认否认、"都要"、序号，再用规则读这句话，读出的意图恰好对应一个
        选项就选它。都不中就当新问题，挂起的选项作废——与确认问句同一个处理。
        """
        options = self._pending_choice
        if not options:
            return None
        source_text = self._pending_choice_question
        fresh = (
            self._clock_ms() - self._pending_choice_ms <= CHOICE_SECONDS * 1000
        )
        self._pending_choice = ()
        self._pending_choice_question = ""
        if not fresh:
            self._log(StepKind.CHOICE, note="expired")
            return None
        if intent_rules.is_denial(question):
            self._log(StepKind.CHOICE, note="cancel")
            return Answer(
                text=phrasing.CHOICE_CANCELLED_TEXT,
                source=AnswerSource.TEMPLATE,
                intent=None,
                facts=None,
            )
        if intent_rules.chooses_all(question):
            asked = [o for o in options if o.kind not in control.CONTROL_KINDS]
            if asked:
                self._log(StepKind.CHOICE, note="all")
                return self._answer_compound(asked, None, log_compound=False)
        index = intent_rules.choice_index(question)
        if index is None:
            read = intent_rules.recognise(question, self._recent_channel())
            matches = [
                i for i, o in enumerate(options)
                if o.kind is read.kind
                and (o.channel is None or read.channel in (None, o.channel))
            ]
            if len(matches) == 1:
                index = matches[0]
                if options[index].channel is None and read.channel is not None:
                    options = tuple(
                        replace(o, channel=read.channel) if i == index else o
                        for i, o in enumerate(options)
                    )
        if index is None or index >= len(options):
            self._log(StepKind.CHOICE, note="other")
            return None
        picked = options[index]
        self._log(StepKind.CHOICE, note=f"picked:{index + 1}", intent=picked)
        if picked.kind in control.CONTROL_KINDS:
            # 用户从代码写出的选项里明确挑了这个动作，选项文字写明了动作本身，
            # 这就是授权；数值照旧只从用户最初那句话里读。
            if picked.kind in _FAN_ACTIONS:
                self._fan_topic_ms = self._clock_ms()
            return self._perform_control(picked, source_text, AnswerSource.TEMPLATE)
        expanded = self._expand_channels(picked, "")
        if expanded:
            return self._answer_compound(expanded, None, log_compound=False)
        return self._answer_question(picked, source_text)

    def _settle_clarification_all(self, question: str) -> Answer | None:
        """对"你问的是温度、湿度还是噪声？"回一句"都要"：三个通道一起答。

        原先这一问只接一个通道，"都要""三个都"会被当成新问题，于是又被问一遍
        （歧义题库调参集"报警线定在哪"，2026-09-26）。只对提问生效；
        指令的反问（"要调温度还是湿度的通风阈值"）仍然一次只接一个。"""
        pending = self._pending_clarify
        if pending is None or pending.kind in control.CONTROL_KINDS:
            return None
        if intent_rules.is_denial(question) or not intent_rules.chooses_all(question):
            return None
        fresh = (
            self._clock_ms() - self._pending_clarify_ms <= CLARIFY_SECONDS * 1000
        )
        if not fresh:
            return None
        self._pending_clarify = None
        self._pending_clarify_question = ""
        self._log(StepKind.CHOICE, note="all")
        return self._answer_compound(
            [replace(pending, channel=c) for c in ALL_CHANNELS],
            None,
            log_compound=False,
        )

    def _answer_question(self, intent: Intent, question: str) -> Answer:
        """取数、套模板，处理"缺通道就反问"。不送模型改写。"""
        self._remember_channel(intent.channel)
        facts = self._retriever.retrieve(intent)
        text = phrasing.render(facts)
        self._log(StepKind.FACTS, intent=intent, facts=facts)
        self._log(StepKind.TEMPLATE, text=text)
        if facts.needs_channel:
            self._pending_clarify = intent
            self._pending_clarify_ms = self._clock_ms()
        else:
            self._remember_kind(intent.kind)
        return Answer(
            text=text, source=AnswerSource.TEMPLATE, intent=intent, facts=facts
        )

    def reset_conversation(self) -> None:
        """Forget the topic and any question left hanging.

        Nothing about the platform's state changes -- readings, thresholds
        and the fan mode are not conversation. This ends the *exchange*,
        which is what a caller needs when the next question comes from
        somewhere else entirely: a fresh rehearsal round, a cleared chat
        panel, the next person to walk up to the screen.

        Without it a rehearsal's second round is not a repeat of its
        first: "超标了吗" opened with no topic in round one and was asked
        back about, then inherited round one's last channel in round two
        and was answered outright. Both are correct, which is exactly why
        a stability check comparing the two rounds needs them to start
        from the same place.
        """
        self._pending_clarify = None
        self._pending_confirm = None
        self._pending_confirm_question = ""
        self._pending_review = None
        self._pending_review_question = ""
        self._last_channel = None
        self._last_channel_ms = 0
        self._pending_choice = ()
        self._pending_choice_question = ""

    def _settle_clarification(self, recognised: Intent, text: str) -> Intent:
        """Fold a one-word reply back into the question that prompted it.

        The reply this expects is a **bare** channel -- "温度", "噪声吧" --
        and bareness is checked on the text, not inferred from the intent.
        Kind alone is not enough: "现在噪声多少" is also a CURRENT_VALUE
        naming a channel, and reading it as an answer swallows a perfectly
        good new question. On the instruction side that mistake also loops,
        because the pending instruction is re-registered and asks again.

        Anything that is not a bare reply drops the pending clarification
        rather than leaving it to attach itself to a later sentence.
        """
        pending = self._pending_clarify
        if pending is None:
            return recognised
        is_control = pending.kind in control.CONTROL_KINDS
        window = CONTROL_CLARIFY_SECONDS if is_control else CLARIFY_SECONDS
        fresh = self._clock_ms() - self._pending_clarify_ms <= window * 1000
        question = self._pending_clarify_question
        self._pending_clarify = None
        self._pending_clarify_question = ""
        if not fresh:
            return recognised
        if (
            recognised.kind is IntentKind.CURRENT_VALUE
            and recognised.channel
            and _is_bare_channel_reply(text)
        ):
            if is_control:
                # Only two channels have a ventilation threshold. A reply of
                # 噪声 to "温度还是湿度" answers neither, so the instruction
                # is dropped and the sentence stands on its own -- better a
                # noise reading than a third round of the same question.
                if recognised.channel not in _VENT_CHANNELS:
                    return recognised
                self._settled_question = question
            return replace(pending, channel=recognised.channel)
        return recognised

    def _remember_channel(self, channel: ChannelId | None) -> None:
        """Record what this question was about, so the next one can lean on
        it. A question that named no channel leaves the memory alone rather
        than clearing it -- "有几个设备在线" between two noise questions is
        not a change of subject."""
        if channel is None:
            return
        self._last_channel = channel
        self._last_channel_ms = self._clock_ms()

    def _act(self, recognised: Intent, question: str, source: AnswerSource) -> Answer:
        """Carry out an instruction and report it, with no model involved.

        Deliberately not reworded afterwards, unlike an answer to a
        question: a confirmation that something was changed should read
        identically every time, and a model that "improves" it is only
        adding a way for the wording to drift from what actually happened.
        """
        self._discard_pending()
        facts = self._control.execute(recognised, question)
        self._log(StepKind.EXECUTED, intent=recognised, facts=facts, text=question)
        return Answer(
            text=phrasing.render(facts),
            source=source,
            intent=recognised,
            facts=facts,
        )

    def _perform_control(
        self, recognised: Intent, source_text: str, source: AnswerSource
    ) -> Answer:
        """真正执行一条指令，并接住"缺通道"那一路的反问。

        三条路径汇合到这里：没有模型时的直接执行、复核一致后的执行、
        用户点头后的执行。三者之后的处理必须一样，所以只写一遍——
        原先这段逻辑长在 ``ask()`` 里，复核加进来时若照抄一份，
        "缺通道就反问"很容易只在其中一条路径上生效。
        """
        self._pending_clarify = None
        answer = self._act(recognised, source_text, source)
        if answer.facts is not None and answer.facts.needs_channel:
            self._pending_clarify = recognised
            self._pending_clarify_ms = self._clock_ms()
            self._pending_clarify_question = source_text
        return answer

    def _settle_confirmation(self, question: str) -> Answer | None:
        """接住用户对"你是想让我……吗"的回答。

        只有三种去向：答"是"就执行，答"不用"就作罢，答别的就当成新问题
        （挂起的那条随之作废，不留到下一句去）。最后一种是有意的——
        用户没回答确认问句，说明他已经在说别的事了，而一条没有得到授权的
        指令不应该在对话里继续漂着。

        窗口过期同样作废，理由见 :data:`CONTROL_CONFIRM_SECONDS`。
        """
        pending = self._pending_confirm
        if pending is None:
            return None
        source_text = self._pending_confirm_question
        fresh = (
            self._clock_ms() - self._pending_confirm_ms
            <= CONTROL_CONFIRM_SECONDS * 1000
        )
        self._pending_confirm = None
        self._pending_confirm_question = ""
        if not fresh:
            self._log(StepKind.CONFIRMATION, intent=pending, note="expired")
            return None
        if intent_rules.is_denial(question):
            self._log(StepKind.CONFIRMATION, intent=pending, note="deny")
            return Answer(
                text=phrasing.CONTROL_CANCELLED_TEXT,
                source=AnswerSource.TEMPLATE,
                intent=pending,
                facts=None,
            )
        if intent_rules.is_affirmation(question):
            self._log(StepKind.CONFIRMATION, intent=pending, note="affirm")
            if pending.kind in _FAN_ACTIONS:
                self._fan_topic_ms = self._clock_ms()
            return self._perform_control(
                pending, source_text, AnswerSource.TEMPLATE
            )
        self._log(StepKind.CONFIRMATION, intent=pending, note="other")
        return None

    def _start_review(self, recognised: Intent, question: str) -> bool:
        """请模型对**同一句话**独立判一次，用来核对规则读出的这条指令。

        用的是分类任务用的那套提示词，模型看到的仍然只有用户原话，
        给回来的仍然只有一个标签——它没有多出任何权力：裁决在
        :meth:`_finish_review`，执行在 :class:`ControlExecutor`，
        数值仍然从用户自己的句子里读。

        返回请求是否真的发出去了。发不出去（没装模型、模型忙、空句子）
        就返回 False，调用方随即按老路直接执行——**模型缺席时行为与
        改动前逐句一致**，这是这套机制的可靠性下限。
        """
        self._discard_pending()
        text = parsing.build_prompt(question)
        if not text:
            return False
        if not self._llm.submit(text, system=parsing.REVIEW_SYSTEM_PROMPT):
            self._log(StepKind.MODEL_UNAVAILABLE, job=JOB_REVIEW)
            return False
        self._pending_qid = self._active_qid
        self._log(StepKind.MODEL_SUBMIT, job=JOB_REVIEW, text=text)
        self._pending_job = JOB_REVIEW
        self._pending_question = question
        self._pending_reply = ""
        self._pending_review = recognised
        self._pending_review_question = question
        return True

    def _finish_review(self) -> Answer | None:
        """裁决：一致就执行，不一致就反问，模型没说话就按原样执行。

        三条分支对应 `docs/decisions/03-intent.md`裁决表的指令列：

        - **模型给出同一类指令** → 执行。两边独立读出同一个意思，
          这是现有管线里准确率最高的情形（留出题库上 104 句一致、错 1 句）。
        - **模型给出别的判断，或明说不认识** → 不执行，反问一句。
          规则自信答错的句子几乎都长这样：22 个错判里 21 个会暴露成分歧。
          代价是偶尔的误报——规则本来对，模型有异议，于是多问一句。
        - **模型什么也没回来**（超时、连接断） → 按规则原样执行。
          这与"模型不可用"是同一种情形，而那一行写的是"与改动前完全一样"：
          一次超时不应该把用户的指令吃掉。区分靠的是回复是否为空，
          不是靠猜——模型真的作答但读不出标签时，走的是上面那条反问分支。

        执行用的始终是**规则**判出的那条意图，模型的标签只用来比对。
        它同意与否都不会改变要执行什么，这是"模型提议、代码裁决"里
        "代码裁决"那一半的落点。
        """
        pending = self._pending_review
        question = self._pending_review_question
        reply = self._pending_reply
        prefix = self._pending_prefix
        self._discard_pending(abandoned=False)
        if pending is None:
            return None
        proposed = parsing.parse_reply(reply)
        if proposed is not None and proposed.kind is pending.kind:
            review_note = "agree"
        elif not reply.strip():
            review_note = "silent"
        else:
            review_note = "disagree"
        self._log(
            StepKind.LABEL, job=JOB_REVIEW, intent=proposed, note=review_note
        )
        if proposed is not None and proposed.kind is pending.kind:
            return _with_prefix(
                self._perform_control(pending, question, AnswerSource.TEMPLATE),
                prefix,
            )
        if not reply.strip():
            return _with_prefix(
                self._perform_control(pending, question, AnswerSource.TEMPLATE),
                prefix,
            )
        self._pending_confirm = pending
        self._pending_confirm_question = question
        self._pending_confirm_ms = self._clock_ms()
        return _with_prefix(
            Answer(
                text=phrasing.confirm_control_text(pending, question),
                source=AnswerSource.TEMPLATE,
                intent=pending,
                facts=None,
            ),
            prefix,
        )

    def _start_parsing(self, question: str) -> bool:
        """Ask the model which of the known question kinds ``question`` is.

        Only reached when the rules failed, which is what keeps this
        affordable: the common phrasings never pay for a model call, and
        the ones that do have already been answered (with the help text)
        before the request is even sent.

        An empty question is not sent -- there is nothing to classify, and
        the help text is the right answer to it.

        Returns whether a request is actually in flight. The caller needs
        to know: it decides between showing a placeholder and showing the
        capability list, and a placeholder with nothing coming to replace
        it would sit there for good.
        """
        self._discard_pending()
        text = parsing.build_prompt(question)
        if not text:
            return False
        if not self._llm.submit(text, system=parsing.PARSE_SYSTEM_PROMPT):
            self._log(StepKind.MODEL_UNAVAILABLE, job=JOB_PARSE)
            return False
        self._pending_qid = self._active_qid
        self._log(StepKind.MODEL_SUBMIT, job=JOB_PARSE, text=text)
        self._pending_job = JOB_PARSE
        self._pending_question = question
        self._pending_reply = ""
        return True

    def _start_rephrasing(
        self, text: str, facts: Facts, recognised: Intent
    ) -> None:
        """Ask the model to reword ``text``.

        **A new question abandons any model work still in flight.** Two
        reasons, and the second is the serious one:

        - The user has moved on. A nicer wording of a question that has
          already scrolled up is worth nothing.
        - Left running, that stale rephrasing arrives *after* the new
          question has been answered, and a view has no way to tell which
          question it belongs to -- it lands under the wrong one. Every
          number in it is real, which makes it worse, not better: the
          answer is correct and attached to the wrong question. Cancelling
          at the source removes the possibility rather than asking every
          consumer to guard against it.
        """
        self._discard_pending()
        explain = recognised.kind in EXPLAINED_KINDS and facts.available
        prompt = phrasing.facts_brief(facts) if explain else text
        if explain:
            system = EXPLAIN_SYSTEM_PROMPT
        elif phrasing.mismatch_kind(facts) in phrasing.TEASING_MISMATCHES:
            system = TEASE_SYSTEM_PROMPT
        else:
            system = REPHRASE_SYSTEM_PROMPT
        job = JOB_EXPLAIN if explain else JOB_REPHRASE
        if not self._llm.submit(prompt, system=system):
            self._log(StepKind.MODEL_UNAVAILABLE, job=job)
            return
        self._pending_qid = self._active_qid
        self._log(StepKind.MODEL_SUBMIT, job=job, text=prompt)
        self._pending_job = JOB_EXPLAIN if explain else JOB_REPHRASE
        self._pending_expanded = explain
        self._pending_facts = facts
        self._pending_template = text
        self._pending_intent = recognised
        self._pending_reply = ""

    def _discard_pending(self, abandoned: bool = True) -> None:
        """Drop any in-flight model work and the state tracking it.

        ``abandoned`` only affects the step log: the ``_finish_*`` methods
        pass False because the job they clear has completed, not been
        dropped.

        A pending **review** is dropped with the rest, which means the
        instruction it was holding is dropped too: the user asked something
        else before the verdict came back, and carrying out an order they
        have moved on from is worse than doing nothing. The confirmation
        state is deliberately *not* cleared here -- it is waiting on the
        user, not on the model, and ``_settle_confirmation`` retires it.
        """
        if abandoned and self._pending_job:
            self._log(
                StepKind.ABANDONED, qid=self._pending_qid, job=self._pending_job
            )
        if self._llm.is_busy():
            self._llm.cancel()
        self._pending_review = None
        self._pending_review_question = ""
        self._pending_prefix = ""
        self._pending_job = ""
        self._pending_facts = None
        self._pending_template = ""
        self._pending_intent = None
        self._pending_reply = ""
        self._pending_question = ""
        self._pending_placeholder = False
        self._pending_expanded = False
        self._retry_used = False
        self._pending_attempts = []

    def poll_rephrasing(self) -> Answer | None:
        """Collect a finished model result, if one is ready.

        Call from the poll loop. Returns None while nothing is pending, the
        model is still working, or its output was not usable; returns an
        :class:`Answer` meant to replace the one ``ask`` gave, whose
        ``source`` says what the model contributed:

        - ``MODEL`` -- it reworded a template answer, and the wording
          passed the grounding check.
        - ``TEMPLATE`` -- it reworded one and the result was rejected, so
          the template stands.
        - ``MODEL_INTENT`` -- it classified a question the rules missed,
          and the answer below is retrieved and templated as usual.

        The name is historical: rephrasing was the only job when this was
        written. It is kept because :class:`api.ApiInterface` and the
        composition root call it, and the meaning ("hand me anything the
        model finished") has not changed.
        """
        if not self._pending_job:
            return None
        qid = self._pending_qid
        self._active_qid = qid
        answer = self._collect()
        if answer is not None:
            self._log(
                StepKind.ANSWERED, text=answer.text, source=answer.source, final=True
            )
            return replace(answer, question_id=qid)
        if not self._pending_job:
            # The job finished and produced nothing to show: the immediate
            # answer is the final one.
            self._log(StepKind.ANSWERED, note="immediate_stands", final=True)
        return None

    def _collect(self) -> Answer | None:
        """The body of :meth:`poll_rephrasing`, which wraps it with the log."""
        chunk = self._llm.poll()
        if chunk is None:
            return None

        # Accumulate. A streaming client returns the text produced since
        # the last call, so treating one poll as the whole answer would
        # keep only the final fragment -- which would then almost always
        # fail the grounding check and silently disable rephrasing.
        self._pending_reply += chunk
        if self._llm.is_busy():
            return None
        self._log(
            StepKind.MODEL_REPLY, job=self._pending_job, text=self._pending_reply
        )

        if self._pending_job == JOB_REVIEW:
            return self._finish_review()
        if self._pending_job == JOB_PARSE:
            return self._finish_parsing()
        return self._finish_rephrasing()

    def _finish_rephrasing(self) -> Answer | None:
        """Accept the rewording, or ask for one more before giving up.

        Returning None means "still working": one retry is started and its
        result comes back through a later poll, exactly like the first
        attempt. The caller already handles None on every cycle, so the
        retry costs it nothing.
        """
        text, source, verdict = phrasing.judge(
            self._pending_template,
            self._pending_reply,
            self._pending_facts,
            expanded=self._pending_expanded,
        )
        self._log(
            StepKind.CHECKS,
            job=self._pending_job,
            text=self._pending_reply,
            checks=phrasing.explain_checks(
                self._pending_template,
                self._pending_reply,
                self._pending_facts,
                expanded=self._pending_expanded,
            ),
            verdict=verdict,
        )
        # Recorded before the retry decision, so a refused first attempt is
        # kept even when the retry is what finally answers.
        self._pending_attempts.append(RephraseAttempt(
            template=self._pending_template,
            reply=self._pending_reply,
            verdict=verdict,
            retry=self._retry_used,
        ))
        if (
            source is AnswerSource.TEMPLATE
            and not self._retry_used
            and self._pending_reply.strip()
            and self._retry_rephrasing()
        ):
            return None
        answer = Answer(
            text=text,
            source=source,
            intent=self._pending_intent,
            facts=self._pending_facts,
            trace=tuple(self._pending_attempts),
        )
        self._discard_pending(abandoned=False)
        return answer

    def _retry_rephrasing(self) -> bool:
        """Resend the same template under the stricter prompt. One only.

        Everything the pending answer needs -- facts, template, intent --
        is kept rather than discarded, because the retry answers the same
        question; only the reply buffer is cleared.
        """
        if self._llm.is_busy():
            self._llm.cancel()
        if not self._llm.submit(
            self._pending_template, system=REPHRASE_RETRY_SYSTEM_PROMPT
        ):
            return False
        self._retry_used = True
        self._pending_reply = ""
        self._log(StepKind.RETRY, job=self._pending_job, text=self._pending_template)
        return True

    def _finish_parsing(self) -> Answer | None:
        """Answer the question the model just classified, or give up quietly.

        Giving up replaces the placeholder with one short sentence, or
        returns None when what is on screen was never a placeholder. The
        distinction matters: "让我想想…" has to be replaced by something or
        it stands as the final answer, while a clarification question is
        itself a real answer and repeating anything over it would read as
        though the question had been asked twice.

        The answer is built by the ordinary path -- retrieval then template
        -- so nothing the model wrote reaches the user. It only chose which
        question was being asked.
        """
        candidates = parsing.parse_candidates(self._pending_reply)
        question = self._pending_question
        placeholder = self._pending_placeholder
        self._discard_pending(abandoned=False)
        kinds = {c.kind for c in candidates}
        if not candidates:
            note = "unusable"
        elif len(kinds) > 1:
            note = "ambiguous"
        elif len(candidates) > 1:
            note = "multi_channel"
        else:
            note = ""
        self._log(
            StepKind.LABEL,
            job=JOB_PARSE,
            intent=candidates[0] if candidates else None,
            note=note,
            text=" / ".join(phrasing.describe([c]) for c in candidates)
            if len(candidates) > 1
            else "",
        )
        if not candidates:
            if not placeholder:
                return None
            return Answer(
                text=phrasing.UNKNOWN_TEXT,
                source=AnswerSource.FALLBACK,
                intent=Intent(kind=IntentKind.HELP),
                facts=Facts(kind=IntentKind.HELP),
            )

        if len(kinds) > 1:
            # ⑤ 模型拿不准，给了几个候选：由代码写反问，选项只可能是系统真有的能力。
            # 规则已经反问过通道的（不是占位句）不再叠一句不同的反问。
            if not placeholder:
                return None
            self._pending_choice = candidates
            self._pending_choice_ms = self._clock_ms()
            self._pending_choice_question = question
            return Answer(
                text=phrasing.choice_text(candidates),
                source=AnswerSource.MODEL_INTENT,
                intent=None,
                facts=None,
            )

        recognised = candidates[0]
        # The model got there first. Whatever was asked back is answered
        # now, so retiring it stops a later "温度" from being folded into a
        # question the user has already had answered.
        self._pending_clarify = None

        if recognised.kind in control.CONTROL_KINDS:
            self._remember_channel(recognised.channel)
            # 规则认不出、模型单方面判成指令——这一路原先是直接执行的。
            # 改为反问确认：模型可以提议一个动作，但不能独自触发它，
            # 而这里没有第二个判断来跟它对照（裁决表第四行）。
            self._pending_confirm = recognised
            self._pending_confirm_question = question
            self._pending_confirm_ms = self._clock_ms()
            return Answer(
                text=phrasing.confirm_control_text(recognised, question),
                source=AnswerSource.MODEL_INTENT,
                intent=recognised,
                facts=None,
            )

        # 模型只给标签，不给体感；"冻死我了"这类规则没认出、由模型判成问温度的句子，
        # 体感方向仍由代码从原话里取（2026-09-27），否则 34℃ 时它会被答成"注意防暑"。
        asked = [
            replace(c, felt_claim=intent_rules.felt_claim(question, c.channel))
            for c in candidates
        ]
        if (
            len(asked) == 1
            and recognised.kind is IntentKind.SAMPLE_COUNT
            and recognised.channel is None
        ):
            asked = [replace(recognised, channel=c) for c in ALL_CHANNELS]
        # ④ 模型分类出来的提问，先说按什么理解的：它毫不犹豫地选错时不会反问，
        # 这一句是让错读一眼可见的补救。
        parts: list[str] = []
        every: list[Facts] = []
        first: Answer | None = None
        for intent in asked:
            self._remember_channel(intent.channel)
            facts = self._retriever.retrieve(intent)
            text = phrasing.render(facts)
            every.append(facts)
            self._log(StepKind.FACTS, intent=intent, facts=facts)
            self._log(StepKind.TEMPLATE, text=text)
            parts.append(text)
            if first is None:
                first = Answer(
                    text=text,
                    source=AnswerSource.MODEL_INTENT,
                    intent=intent,
                    facts=facts,
                )
        assert first is not None
        body = _join_sentences(parts)
        return replace(
            first,
            text=phrasing.interpretation(asked) + body + phrasing.INTERPRETATION_TAIL,
            all_facts=tuple(every) if len(every) > 1 else (),
        )

    def capabilities(self) -> Sequence[str]:
        """The question types this assistant handles, for a UI hint line."""
        return tuple(phrasing.HELP_TEXT.splitlines()[1:])


__all__ = [
    "Assistant",
    "EXPLAIN_SYSTEM_PROMPT",
    "JOB_EXPLAIN",
    "JOB_PARSE",
    "JOB_REPHRASE",
    "JOB_REVIEW",
    "REPHRASE_SYSTEM_PROMPT",
    "TEASE_SYSTEM_PROMPT",
]
