"""Data models exchanged between the assistant's three stages.

The shape that matters here is :class:`Facts`: it is **structured**, never
a pre-composed sentence. That is deliberate and load-bearing, because
Facts has more than one consumer -- the phrasing stage renders Chinese for
a human, and (later) the same object is what a board's LCD push would be
built from, which needs numbers and codes rather than prose. See
docs/02_Architecture/Assistant_Design.md section 3.2.

The other load-bearing property: **every number a user ever sees
originates in a Facts field**, put there by code that read it from the
data layer. Nothing downstream may invent one; see
``phrasing.numbers_are_grounded``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from core.models import ChannelId, DeviceId


class IntentKind(Enum):
    """What the user is asking for.

    Extending this enum is how a new question type is added -- including
    the timetable lookup sketched in the design document, which slots in
    here rather than needing a parallel pipeline.
    """

    CURRENT_VALUE = "current_value"
    """"现在温度多少" -- the latest reading on one channel."""

    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    AVERAGE = "average"
    """Statistics over everything recorded so far on one channel."""

    ALARM_STATE = "alarm_state"
    """"噪声超标了吗" -- whether a channel is over its alarm threshold."""

    THRESHOLD_INFO = "threshold_info"
    """"噪声阈值是多少" -- the configured threshold and its basis."""

    FAN_STATE = "fan_state"
    """"风扇在转吗 / 为什么在转"."""

    DEVICE_LIST = "device_list"
    """"有几个设备在线"."""

    HELP = "help"
    """"你能干什么" -- also what an unrecognised question falls back to."""

    BARE_SWITCH = "bare_switch"
    """"打开" / "关了吧" -- an on-off instruction that named no object.

    Recognised in order to be *asked about*, never acted on directly. The
    system has exactly one actuator, so the guess would usually be right;
    the reason not to guess is that a silent guess and a visible question
    cost the same one round trip, and only one of them is checkable. See
    ``phrasing.SWITCH_CLARIFY_TEXT``.
    """

    ANNOUNCE_REQUEST = "announce_request"
    """"测试一下报警发声" -- a request to speak on demand, which is refused.

    This kind exists to be *declined*, not served, and that is the point:
    without it "试一下语音播报能不能响" matched the noise channel (响 and
    声音 are noise keywords) and came back with a real sound level -- a
    request the system cannot honour, answered with a plausible number.
    Naming the intent turns that into one honest sentence.

    Announcements are deliberately reachable only from
    :class:`service.alarm_announcer.AlarmAnnouncer`: speaking builds an
    ``ALERT_*`` command and puts a frame on the wire, where every kind in
    ``control.CONTROL_KINDS`` only writes a ventilation *setting* -- and a
    played phrase cannot be taken back, so it fails the reversibility that
    lets those four run without a confirmation step. See ``control`` for
    the three properties in full.
    """

    CLOUD_SYNC_HINT = "cloud_sync_hint"
    """"把数据传上去" -- an offer to upload, which the user then confirms.

    The one kind that leads to an *external* action, and it gets there
    without ever being executable by the assistant. Uploading fails the
    same three admission properties as deleting -- irreversible, launches
    a subprocess, parameters not stated in the sentence -- so it is not in
    ``control.CONTROL_KINDS`` either. What makes it different from
    :attr:`DELETE_REQUEST` is that the action is *additive*: a file that
    went up early costs nothing to have sent, whereas a row deleted early
    is gone. That is the whole reason one gets a button and the other
    gets a refusal.

    So this kind carries no power of its own. It produces a sentence and
    a count; the desktop turns that into a button, and a person clicking
    it is what starts anything. Model proposes, human disposes -- the
    same line as "the model may veto, never initiate".

    Design: docs/02_Architecture/History_And_Cloud_Design.md section 6.1.
    """

    CLOUD_VIEW_HINT = "cloud_view_hint"
    """"云上有什么" -- an offer to open the read-only archive listing.

    Sibling of :attr:`CLOUD_SYNC_HINT`, and the easier of the two to
    justify: ``cloud_view`` **reads and nothing else** -- it lists what is
    already in the bucket and opens the console. It still gets a button
    rather than being executed outright, for one reason only: it launches
    a subprocess, and that is the line the assistant does not cross. The
    admission test was never about how dangerous the action is; it is
    about whether the assistant should be the one starting it.

    Unlike the upload offer this one has **no count to report** and no
    precondition -- there is always something to show, even if the answer
    turns out to be "nothing up there yet". So the button appears whenever
    the intent is recognised.
    """

    DELETE_REQUEST = "delete_request"
    """"把旧数据删了" -- a request to destroy data, which is refused.

    Exists for the same reason as :attr:`ANNOUNCE_REQUEST`, and the same
    concrete hazard: 数据 sits next to channel words in ordinary sentences
    ("把噪声数据清一清"), so without a branch of its own the noise channel
    claims the sentence and a request to *delete* comes back as a real
    sound level. Naming it turns that into one honest sentence.

    Why it is refused rather than served, even behind a confirmation the
    way 上云 is (a button the user clicks -- see
    docs/02_Architecture/History_And_Cloud_Design.md §6.1):

    - **A button is already known to be too weak a gate here.** On
      2026-09-17 the desktop's 清空历史记录 button was deliberately
      narrowed to clearing the *display* only, on the grounds that
      deleting data is irreversible and must not hide behind a button
      that reads like "clear the screen". Routing deletion back through a
      button -- with a language model in front of it -- would undo that.
    - **The parameters cannot be taken from the user's words.** This
      platform's standing rule is that a command's numbers are extracted
      from the original sentence by code. "把旧数据清一清" carries no
      range at all, and guessing one is how you delete the wrong thing.
    - **There is no undo.** Every kind in ``control.CONTROL_KINDS`` can
      be set back the way it was.

    Deleting, if it is ever wanted, belongs in a separate script a person
    runs deliberately -- not on the end of a sentence.
    """

    # -- control (2026-09-08) -------------------------------------------
    #
    # Asking and instructing arrive through the same input box, so they
    # are classified by the same stage. What separates them is what
    # happens next: a question goes to retrieval, an instruction goes to
    # ``control.ControlExecutor``, which owns the whitelist and the range
    # checks. Nothing here dispatches a command -- these kinds change the
    # *ventilation policy*, and the existing dispatcher turns that into a
    # frame on its next poll, exactly as it does for a click in the panel.

    FAN_ON = "fan_on"
    """"把风扇打开" -- force the fan on (FanMode.MANUAL_ON)."""

    FAN_OFF = "fan_off"
    """"关掉风扇" -- force the fan off (FanMode.MANUAL_OFF)."""

    FAN_AUTO = "fan_auto"
    """"风扇交给自动" -- hand control back to the thresholds."""

    SET_VENT_THRESHOLD = "set_vent_threshold"
    """"通风温度阈值调到 28 度" -- move one ventilation threshold.

    The *number* is never taken from a model reply: it is read out of the
    user's own words by code. A model that transcribes 28 as 38 would
    otherwise silently change what the system does. See
    ``control.extract_value``.
    """


@dataclass(frozen=True)
class Intent:
    """A recognised question, reduced to a kind plus its parameters."""

    kind: IntentKind
    channel: ChannelId | None = None
    confidence: float = 1.0
    """1.0 for a rule match. A model-provided intent would score lower,
    which is how a caller can decide to ask for confirmation."""

    past_scoped: bool = False
    """The sentence asked about a period this run does not cover."""

    wants_margin: bool = False
    """The sentence also asked how far the reading is from its limit.

    "现在多少度，还差多少超限" is two requests in one breath, and both are
    served by the same lookup. Carrying it as a flag rather than a separate
    intent keeps that property. Default False, so a plain "现在多少度" gets
    a plain answer: the margin used to be appended unconditionally, which
    answered a question nobody had asked."""


@dataclass(frozen=True)
class Facts:
    """Everything the retrieval stage found, as numbers -- never as prose.

    Fields are deliberately explicit rather than a free-form mapping: the
    phrasing stage and the number-grounding check both need to enumerate
    them, and a ``dict[str, Any]`` would defeat mypy on both counts.

    ``available`` is False when the question was understood but the data
    is not there yet (no reading on that channel). That is a normal
    outcome, not an error -- the answer says so plainly instead of
    guessing.
    """

    kind: IntentKind
    available: bool = True
    channel: ChannelId | None = None
    channel_label: str = ""
    unit: str = ""

    value: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    average: float | None = None
    sample_count: int = 0

    threshold: float | None = None
    citation: str = ""
    """Where the threshold comes from, e.g. "GB 37488-2019".

    A *fact*, not template prose -- it is supplied by the retrieval stage
    like every other field. Keeping it here rather than hard-coding it in
    the template matters for the grounding check: the standard's number
    would otherwise look like a figure the system invented, and every
    threshold answer would fail its own check.
    """
    threshold_is_maximum: bool = True
    """True for an "above this is bad" rule, False for "below this is bad".

    Describes :attr:`threshold` -- the one bound this particular answer is
    about. A channel with a two-sided band still answers about one side at
    a time; :attr:`threshold_low` and :attr:`threshold_high` carry the
    whole band for the answers that need to state it.
    """
    threshold_low: float | None = None
    """Lower bound of the channel's alarm band, if it has one."""
    threshold_high: float | None = None
    """Upper bound of the channel's alarm band, if it has one."""
    needs_channel: bool = False
    """The question was understood but did not say which channel.

    Distinct from ``available=False``, which means "understood, and the
    data is not there". The two produce very different answers: one says
    the sensor has no reading yet, the other asks which sensor was meant.
    Rendering the first for the second is what "超标了吗" used to get --
    "该通道现在还没有有效读数"，an answer about a channel nobody named.
    """
    triggered: bool | None = None
    margin: float | None = None
    pending_uploads: int | None = None
    """待上传的时段数，只在 :attr:`IntentKind.CLOUD_SYNC_HINT` 下有值。

    登记在 Facts 里而不是直接拼进句子，是因为接地校验只认这里的数字——
    模板说"有 12 个时段没传"，而 12 不在 Facts 中的话，模型改写会被整句退回。
    2026-09-08 的风扇模板正是这么踩的。

    ``None`` 表示问不出来（没接台账，或台账打不开），与 0 不是一回事：
    0 是"都传完了"，None 是"不知道"，两者的答话不同。"""

    past_scoped: bool = False
    """Render the answer with its actual coverage stated up front.

    Carried through to phrasing rather than turned into a refusal at
    retrieval: the figure the question wanted is still the closest one
    available, and handing it over *labelled* is more use than declining.
    What must not happen is handing it over unlabelled, which is what used
    to happen."""

    margin_requested: bool = False
    """Whether to *render* ``margin``, not whether it was computed.

    The distance is always worked out -- it is a fact, and the explain job
    lists it among the others. This flag governs one sentence in one
    template: the plain reading answer, which should say what was asked
    and stop there."""
    """Distance from the reading to :attr:`threshold`, when both exist.

    Positive while the reading is inside the limit, negative once it is
    past. Computed here, in the retrieval stage, for one reason: "还差多少
    就超限了" is a subtraction, and a subtraction done by the model is a
    number the model invented. Doing it in code makes the result a *fact*,
    which the grounding check then lets a rephrasing use.
    """

    fan_running: bool | None = None
    fan_reason: str = ""
    fan_mode: str = ""
    vent_temperature_max: float | None = None
    vent_humidity_max: float | None = None
    """The two ventilation thresholds, when the answer is about the fan.

    Not decoration: ``fan_reason`` is presentation text and quotes these
    numbers ("温度 26.0℃ 高于通风阈值 25℃"), but until they were listed
    here they were in no Facts field, so the fan's own template failed the
    grounding check whenever the fan was actually running -- and every
    model rephrasing of it was discarded without a word. Carrying them as
    facts fixes the template and lets a rephrasing quote them.
    """
    readings: tuple[tuple[str, float, str], ...] = ()
    """(label, value, unit) for each channel behind a whole-system answer.

    The single ``value``/``channel`` pair cannot express "the fan is
    running because of these two channels", which is what an explanation
    of the fan needs. Values here count as facts like any other.
    """

    applied: bool | None = None
    """For a control intent: whether the change was actually made.

    None for every question -- ``applied is False`` means the instruction
    was understood but refused (out of range, no ventilation controller,
    no number in the sentence), and ``rejection`` says which.
    """
    echo_question: str = ""
    """The user's own sentence, echoed back inside an instruction's
    clarification. Not decoration: the reply that settles a pending
    instruction is a single word, and that word arrives seconds later with
    nothing on screen to say what it will set. Showing the original is what
    makes "湿度" an informed answer rather than a coin flip.

    Only ever the user's own text, never composed -- and the clarification
    it appears in is not sent for rewording, so nothing can alter it."""

    rejection: str = ""
    """Why a control intent was refused, as a short code the phrasing
    stage maps to a sentence. A code rather than prose because the same
    refusal has to be renderable in more than one place -- and because
    prose in Facts is exactly what section 3.2 of the design document
    rules out."""

    device_ids: tuple[DeviceId, ...] = field(default_factory=tuple)

    def citation_numbers(self) -> tuple[str, ...]:
        """Digit groups appearing in :attr:`citation`, as written.

        Kept separate from :meth:`numbers` because a standard's identifier
        is not a measurement -- it must be reproduced verbatim, not
        compared numerically.
        """
        return tuple(re.findall(r"\d+", self.citation))

    def numbers(self) -> tuple[float, ...]:
        """Every numeric value in this object.

        Used by the grounding check: a rendered answer may only contain
        numbers drawn from here.
        """
        candidates = (
            self.value,
            self.minimum,
            self.maximum,
            self.average,
            self.threshold,
            self.threshold_low,
            self.threshold_high,
            self.margin,
            None if self.margin is None else abs(self.margin),
            self.vent_temperature_max,
            self.vent_humidity_max,
            *(value for _, value, _ in self.readings),
            float(self.sample_count),
            float(len(self.device_ids)),
            None if self.pending_uploads is None else float(self.pending_uploads),
        )
        return tuple(n for n in candidates if n is not None)


class AnswerSource(Enum):
    """Who composed the wording -- not who supplied the numbers.

    The numbers always come from :class:`Facts`. This only records whether
    the sentence around them was a template or a model rephrasing, which
    is what the UI labels so a viewer can tell the two apart.
    """

    TEMPLATE = "template"
    MODEL = "model"
    MODEL_INTENT = "model_intent"
    """The rules did not recognise the question but a model classified it.

    The wording is still a template and the numbers still come from Facts;
    what the model contributed was *understanding the question*. Kept
    distinct from TEMPLATE so the two contributions can be told apart --
    on screen, and when counting how often the model actually earned its
    place.
    """

    FALLBACK = "fallback"
    """The question was not understood; the text says so."""

    PENDING = "pending"
    """A placeholder, shown while the model works out what was asked.

    Distinct from the others because it is the one source whose text is
    **not an answer**: it exists to be replaced, and a consumer that knows
    that can render it accordingly -- greyed, or without the model/template
    label the real answers carry. It is only ever produced when a request
    is genuinely in flight, so nothing is left waiting for a reply that
    will not come.
    """


class CheckVerdict(Enum):
    """What the exit checks made of one model rewording.

    Added 2026-09-23 so the web console can show *why* a rewording was
    used or refused (docs/02_Architecture/Web_Console_Design.md section 6).
    It records a decision :func:`phrasing.judge` already made; nothing
    branches on it except the display.
    """

    ACCEPTED = "accepted"
    NO_REPLY = "no_reply"
    TOO_SHORT = "too_short"
    UNGROUNDED_NUMBER = "ungrounded_number"
    """A number in the rewording is not among the Facts."""
    UNSUPPORTED_ALARM = "unsupported_alarm"
    """It claims an alarm the Facts do not carry."""
    UNSUPPORTED_JUDGEMENT = "unsupported_judgement"
    """It passes a verdict the template did not."""
    ADVICE = "advice"
    """It gives advice the template did not."""
    TOO_LONG = "too_long"
    """Materially longer than what it reworded (rewording job only)."""


@dataclass(frozen=True)
class RephraseAttempt:
    """One rewording the model produced, and the exit checks' verdict on it.

    ``reply`` is the model's text verbatim -- including when it was
    refused, which is the point: a reader can see what the checks stopped.
    ``retry`` is True for the one stricter second attempt the assistant
    makes after a refusal.
    """

    template: str
    reply: str
    verdict: CheckVerdict
    retry: bool = False


@dataclass(frozen=True)
class Answer:
    """What :meth:`assistant.Assistant.ask` returns."""

    text: str
    source: AnswerSource
    intent: Intent | None = None
    facts: Facts | None = None
    trace: tuple[RephraseAttempt, ...] = ()
    """Every model rewording behind this answer, in order (empty when the
    model was not asked to reword). Read-only record, added 2026-09-23."""
