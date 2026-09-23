"""Stage 3: render :class:`Facts` as Chinese, and police what a model wrote.

Templates are the default and are always sufficient. A language model, if
one is attached, may only *rephrase* — and whatever it returns is checked
by :func:`numbers_are_grounded` before being used.

That check is the runtime backstop for this feature's central guarantee.
The prompt can ask a model not to invent figures, but a prompt is a
request, not a constraint. Verifying at the boundary is: every number in
the rendered text must also appear in the Facts the retrieval stage
produced. A model that "helpfully" rounds 76.3 to 76, or adds a plausible
"（标准是 75）", fails the check and its output is discarded in favour of
the template.
"""

from __future__ import annotations

import re

from device.sensors.channels import HUMIDITY_CHANNEL, TEMPERATURE_CHANNEL
from service.assistant import control
from service.assistant.models import (
    AnswerSource,
    CheckVerdict,
    Facts,
    Intent,
    IntentKind,
)

_FAN_MODE_LABELS = {
    "AUTO": "自动",
    "MANUAL_ON": "手动常开",
    "MANUAL_OFF": "手动常关",
}

ANNOUNCE_REFUSAL_TEXT = (
    "语音播报只在读数越限时自动触发，不支持手动播放。"
    "你可以问我某个通道有没有超标，或者查看活动日志里的播报记录。"
)
"""Why this is a fixed string and never handed to the model: it carries no
number, so ``numbers_are_grounded`` has nothing to check, and a rephrase
that turned "不支持手动播放" into an offer to try would be accepted. The
sentence's whole job is to state a limit correctly -- the same reason
``CLARIFY_TEXT`` is not rephrased either."""

DELETE_REFUSAL_TEXT = (
    "删除数据不在我能做的事情里。读数分在三处——本机历史库、导出的归档文件、"
    "以及已经传上云的那份，删哪一处、删哪一段都得你自己确认，所以这一步没有交给我。"
    "界面上的「清空历史记录」只清屏幕上显示的行，不会动数据库里的数据。"
)
"""Fixed and never handed to the model, for the same reason as
:data:`ANNOUNCE_REFUSAL_TEXT`: it carries no number, so
``numbers_are_grounded`` has nothing to check, and a rephrase that softened
"不在我能做的事情里" into an offer would be accepted by every guard we
have. Stating a limit correctly is the sentence's entire job.

It says where the data is rather than only saying no, because "删不了" on
its own invites a second attempt at rephrasing the same request. Naming
the three places, and what the button actually does, answers the question
behind the question."""

CLOUD_SYNC_NONE_TEXT = (
    "已经结束的时段都传上去了。当前这一小时还没结束，要归档得等到整点——"
    "想把到现在为止的读数先传一份，点下面的按钮。"
)
"""都传完时的回话。

原来只说"没有待传的时段"（2026-09-18 到 09-21）。那句话是准确的，
但它是**一条死路**：用户问"现在的数据能传吗"，得到"没什么要传的"，
而当前这一小时确实还有读数没上去——只是归档按整点切，它还不算"待传"。
2026-09-21 起按钮背后接了快照（``--snapshot``），于是这一档有事可做了，
话就得跟着改：说清"已结束的都传了"与"当前这一小时另说"是两件事。

不含数字，因此"当前这一小时有多少条"这个数**刻意不说**——那要查历史库，
而"不让问答去查历史"是这套设计明确划下的界
（``docs/02_Architecture/History_And_Cloud_Design.md`` 第 2 节）。
说得出来的只有"还没结束"，那不是数，永远为真。
"""

CLOUD_SYNC_UNKNOWN_TEXT = (
    "我查不到还有多少没传。归档台账没接上或者打不开，"
    "可以直接双击项目根目录的 cloud_sync_导出并上传.bat 看一眼。"
)
"""台账不可用时的回话。刻意不猜一个数：这一档的整句价值就在那个数字上，
编一个出来正是这套系统从头到尾在防的事。"""


def cloud_sync_text(pending: int) -> str:
    """有 N 个时段待传时的提议句。

    句子以问号收尾、并说明"点一下"，因为界面会在这条答案下面放一个按钮——
    话与控件必须对得上，一句"已经开始上传了"配一个还没点的按钮，
    比不给按钮更糟。

    这一句**可以交模型改写**，与两条拒绝句不同：它带数字，接地校验因此
    真的能管住它（``pending`` 已登记进 ``Facts.pending_uploads``），
    而拒绝句不带数字，校验对它们无从下手。

    2026-09-21 起把"连同当前这一小时"写进句子里，因为按钮从这天起带
    ``--snapshot``：它除了补齐这 N 个已结束的时段，还会截一份当前时段的
    快照。**按钮做什么，话就得说什么**——这一条与当初给它加按钮时定的
    同一个道理，一句话与一个控件对不上比不给控件更糟。当前这一小时有
    多少条读数**不说**：那要查历史库，界已经划在那里了。
    """
    return (
        f"有 {pending} 个时段还没上传。点下面的按钮，"
        f"会把这 {pending} 个时段连同当前这一小时到现在为止的读数一起传上去。"
    )


CLOUD_VIEW_TEXT = (
    "可以看云上已经传了哪些归档。点下面的按钮，"
    "会列出文件清单并打开控制台——只读，不会上传也不会删除。"
)
"""查看云端的提议句。

**明说"只读"**：用户看到一个跟"上传"长得差不多的按钮，第一反应会是
"点了会不会又传一遍"。把它不做什么写在按钮旁边，比事后解释省事。

不含数字，因此与两句拒绝句一样不送模型改写——一次把"不会上传"
润色掉的改写，现有的出口校验一条都拦不住。"""

THINKING_TEXT = "让我想想…"
"""Shown the instant a question the rules missed is handed to the model.

What used to appear here was the whole capability list, replaced seconds
later by a real answer -- a wall of text swapped for something unrelated,
which reads as though the first reply had been a mistake. A placeholder
says the same thing the list was really saying ("not recognised yet")
without pretending to be an answer, and makes the replacement look like
what it is: the same reply finishing.

Only used when the model actually accepted the request. With no model
running the list is still the right immediate answer -- nothing is coming
to replace it."""

UNKNOWN_TEXT = "这句我没听懂。想知道我能回答哪些，问一句「你能干什么」。"
"""Shown when the model could not classify it either.

One line rather than the full list, and it turns the list into something
the user asks for. Someone who has just been misunderstood wants to know
that they were, not to read eleven bullet points; and the list stays one
short sentence away."""

HELP_TEXT = (
    "我可以回答这些问题：\n"
    "· 现在温度／湿度／噪声多少\n"
    "· 噪声超标了吗\n"
    "· 温度最高／最低／平均是多少\n"
    "· 噪声的报警阈值是多少\n"
    "· 风扇在转吗、为什么在转\n"
    "· 有几个设备在线\n"
    "也可以直接下指令：\n"
    "· 把风扇打开／关掉风扇／风扇交给自动\n"
    "· 把通风温度阈值调到某个值"
)
"""Instructions are listed here too, because this text is what a user sees
the moment they were *not* understood -- the one moment they are looking
for what else to try. Deliberately written without a sample number
("调到某个值" rather than "调到 28 度"): the templates hold themselves to
the same grounding rule they enforce on a model, and a figure in the help
text would be one no Facts object contains."""

_NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")


def _fmt(value: float) -> str:
    """One decimal place — matching how the desktop metric cards read."""
    return f"{value:.1f}"


def numbers_are_grounded(text: str, facts: Facts | None) -> bool:
    """Whether every number in ``text`` traces back to ``facts``.

    Comparison is on the *rendered* form rather than the float, because
    that is what a reader sees: 76.34 and 76.3 are different claims on
    screen even though they are close in value. A number is accepted if it
    matches a fact exactly, or matches its one-decimal rendering, or is an
    integer equal to a fact (so "3 个设备" passes against a count of 3).

    With no facts at all, any number is ungrounded.
    """
    found = _NUMBER_PATTERN.findall(text)
    if not found:
        return True
    if facts is None:
        return False

    allowed: set[str] = set(facts.citation_numbers())
    for number in facts.numbers():
        allowed.add(_fmt(number))
        allowed.add(f"{number:g}")
        if number.is_integer():
            allowed.add(str(int(number)))
    return all(token in allowed for token in found)


SWITCH_CLARIFY_TEXT = "你是要开关风扇吗？说一声「开风扇」或「关风扇」就行。"
"""Asked when an on-off instruction named nothing to act on.

Names the two sentences that would work rather than saying "请说明对象":
the reply this wants is one短句, and showing it is what makes it one."""

CONTROL_CLARIFY_TEXT = "你要调的是温度还是湿度的通风阈值？"
"""Asked when an instruction named a value but no channel.

Two channels rather than three: only temperature and humidity have a
ventilation threshold. Echoing the original sentence after it is what lets
the one-word reply be given knowingly -- see ``Facts.echo_question``."""

CLARIFY_TEXT = "你问的是温度、湿度还是噪声？"
"""Asked when the question was understood but named no channel.

Lists the three by name rather than saying "请说明通道": the answer this
wants is one word, and showing which three words are on offer is what
makes it one word. No number appears in it, so it passes the same
grounding rule the other templates hold themselves to.
"""


REVIEW_WAIT_TEXT = "收到，让我确认一下这句话的意思…"
"""指令等待模型复核时先显示的一句。

与 :data:`THINKING_TEXT` 同一个性质——它不是答案，是等待期的占位，
所以同样以 ``AnswerSource.PENDING`` 标出。措辞刻意不说"正在执行"：
这一刻什么都还没做，说了就是一句会被复核结果推翻的话。"""

CONTROL_CANCELLED_TEXT = "好，那就不动它。"
"""用户对确认问句答了"不用"之后的回话。"""

_VENT_LABELS = {TEMPERATURE_CHANNEL: "温度", HUMIDITY_CHANNEL: "湿度"}
"""只有这两个通道有通风阈值，与 ``control.VALUE_RANGES`` 同一组。"""

_CONTROL_CONFIRM: dict[IntentKind, str] = {
    IntentKind.FAN_ON: "把风扇切到手动常开",
    IntentKind.FAN_OFF: "把风扇切到手动常关",
    IntentKind.FAN_AUTO: "把风扇交回自动模式",
}


def confirm_control_text(intent: Intent, question: str) -> str:
    """问用户"你是想让我……吗"，用在规则与模型对这句话的理解不一致时。

    说的是**将要改成什么设置**，与 :func:`_render_control` 的确认句同一口径，
    这样用户看到的两句话能对上。阈值那一条要把数字说出来——它取自用户自己的
    句子（``control.extract_value``），不是模型给的，这也正是可以放心复述的原因。

    这句话不送去改写：它唯一的职责是把要确认的事说准，而改写会把它变成
    另一个问题。
    """
    if intent.kind is IntentKind.SET_VENT_THRESHOLD:
        value = control.extract_value(question)
        label = _VENT_LABELS.get(intent.channel, "") if intent.channel else ""
        if value is not None and label:
            action = f"把{label}的通风阈值调到 {value:g}"
        elif value is not None:
            action = f"把通风阈值调到 {value:g}"
        else:
            action = "改通风阈值"
    else:
        action = _CONTROL_CONFIRM.get(intent.kind, "执行这条指令")
    return f"你是想让我{action}吗？说「是」我就执行，说「不用」就算了。"


SCOPE_NOTICE = "我只按本次启动以来的数据回答；更早的读数在「历史记录」页里。"
"""Prefix for an answer whose question asked about a period not covered.

States the limit once and then answers anyway. Restating it inside the
sentence ("本次运行以来的最高值是…") would be tidier but doubles the
length of every such answer; a leading sentence reads once and applies to
what follows.

**Reworded 2026-09-18, because the old sentence had become false.** It
read "系统只保留本次运行以来的数据，给不出更早的时段", which was true
until 2026-09-17, when readings began persisting to SQLite. After that a
user could be told the system keeps nothing earlier, then page over to
历史记录 and see yesterday -- a small contradiction, and those are the
ones that cost trust. (The change was predicted in
docs/02_Architecture/History_And_Cloud_Design.md section 6 when history
was designed, and then not made.)

The limit itself is real and unchanged: retrieval reads
``SensorDataProcessor``'s in-memory statistics, which start empty at
every launch -- it never touches the history store. So the honest
sentence attributes the limit to *the assistant* rather than to the
system, and points at where the earlier readings actually are.

That distinction also covers a coverage mismatch worth knowing about:
the history database is continuous from launch to launch, while these
statistics reset. "今天最高多少度" can therefore answer 27 ℃ while the
history page shows 29 ℃ from before a restart. Both numbers are real
readings; what differs is the span each one covers, which is exactly
what this prefix now says."""


def render(facts: Facts) -> str:
    """Compose the template answer for ``facts``. Always succeeds."""
    body = _render(facts)
    if facts.past_scoped and facts.available and facts.value is not None:
        return f"{SCOPE_NOTICE}{body}"
    return body


def _render(facts: Facts) -> str:
    """The answer itself, before any scope notice."""
    if facts.needs_channel:
        if facts.kind is IntentKind.SET_VENT_THRESHOLD:
            return f"{CONTROL_CLARIFY_TEXT}（原话：{facts.echo_question}）"
        return CLARIFY_TEXT
    if facts.kind is IntentKind.HELP:
        return HELP_TEXT
    if facts.kind is IntentKind.BARE_SWITCH:
        return SWITCH_CLARIFY_TEXT
    if facts.kind is IntentKind.ANNOUNCE_REQUEST:
        return ANNOUNCE_REFUSAL_TEXT
    if facts.kind is IntentKind.DELETE_REQUEST:
        return DELETE_REFUSAL_TEXT
    if facts.kind is IntentKind.CLOUD_VIEW_HINT:
        return CLOUD_VIEW_TEXT
    if facts.kind is IntentKind.CLOUD_SYNC_HINT:
        if facts.pending_uploads is None:
            return CLOUD_SYNC_UNKNOWN_TEXT
        if facts.pending_uploads == 0:
            return CLOUD_SYNC_NONE_TEXT
        return cloud_sync_text(facts.pending_uploads)
    if facts.kind is IntentKind.DEVICE_LIST:
        return _render_devices(facts)
    if facts.kind is IntentKind.FAN_STATE:
        return _render_fan(facts)
    if facts.kind is IntentKind.THRESHOLD_INFO:
        return _render_threshold(facts)
    if facts.applied is not None:
        return _render_control(facts)
    if not facts.available:
        label = facts.channel_label or "该通道"
        return f"{label}现在还没有有效读数，可能是刚启动或者传感器没接好。"
    if facts.kind is IntentKind.ALARM_STATE:
        return _render_alarm(facts)
    return _render_measurement(facts)


def _render_devices(facts: Facts) -> str:
    count = len(facts.device_ids)
    if count == 0:
        return "当前没有已注册的设备。"
    names = "、".join(facts.device_ids)
    return f"当前有 {count} 个设备在线：{names}。"


def _render_fan(facts: Facts) -> str:
    if not facts.available or facts.fan_running is None:
        return "通风控制没有启用，我看不到风扇状态。"
    state = "正在运行" if facts.fan_running else "已停止"
    mode = _FAN_MODE_LABELS.get(facts.fan_mode, facts.fan_mode)
    reason = facts.fan_reason.strip()
    if reason:
        return f"风扇{state}（{mode}）：{reason}。"
    return f"风扇{state}，当前为{mode}模式。"


def _render_threshold(facts: Facts) -> str:
    label = facts.channel_label or "该通道"
    basis = f"，依据 {facts.citation}" if facts.citation else ""
    low, high = facts.threshold_low, facts.threshold_high
    if low is not None and high is not None:
        # A two-sided band cannot be stated as one number and a direction:
        # saying only the ceiling would hide the floor that is equally
        # able to raise an alarm.
        return (
            f"{label}的正常范围是 {low:g}~{high:g}{facts.unit}，"
            f"低于或高于这个范围都会报警{basis}。"
        )
    if facts.threshold is None:
        return f"{label}没有配置报警阈值。"
    direction = "高于" if facts.threshold_is_maximum else "低于"
    return (
        f"{label}的报警阈值是 {facts.threshold:g}{facts.unit}，"
        f"{direction}这个值就会报警{basis}。"
    )


_REJECTION_TEXT: dict[str, str] = {
    control.REJECT_NO_CONTROLLER: "通风控制没有启用，我改不了风扇。",
    control.REJECT_NO_CHANNEL: (
        "调通风阈值要说明是温度还是湿度，比如「把通风温度阈值调低一点」。"
    ),
    control.REJECT_NO_VALUE: "没看出要调到多少，请在句子里写清楚一个数值。",
}
"""Refusals that need no number. Out-of-range is rendered separately
because it quotes the value the user asked for -- which is in Facts, and
so passes the grounding check the templates hold themselves to."""

_CONTROL_DONE: dict[IntentKind, str] = {
    IntentKind.FAN_ON: "已把风扇切到手动常开",
    IntentKind.FAN_OFF: "已把风扇切到手动常关",
    IntentKind.FAN_AUTO: "风扇已交回自动模式，按通风阈值决定开停",
}


def _render_control(facts: Facts) -> str:
    """Confirm -- or refuse -- an instruction.

    Deliberately says what *setting* changed rather than what the fan is
    doing: the frame reaches the board on the next poll, and only if the
    application holds control of the device. Claiming "风扇已启动" would be
    a promise this layer is in no position to make.
    """
    if not facts.applied:
        if facts.rejection == control.REJECT_OUT_OF_RANGE and facts.value is not None:
            label = facts.channel_label or "该通道"
            return (
                f"{label}的通风阈值不能设成 {facts.value:g}{facts.unit}，"
                "超出了传感器的量程。"
            )
        return _REJECTION_TEXT.get(facts.rejection, "这条指令我没有执行。")

    if facts.kind is IntentKind.SET_VENT_THRESHOLD and facts.threshold is not None:
        label = facts.channel_label or "该通道"
        return (
            f"好的，{label}的通风阈值已设为 {facts.threshold:g}{facts.unit}，"
            f"当前判定是{'需要通风' if facts.fan_running else '不需要通风'}。"
        )

    done = _CONTROL_DONE.get(facts.kind, "设置已更新")
    if facts.fan_running is None:
        return f"{done}。"
    return f"{done}，当前判定是{'运行' if facts.fan_running else '停止'}。"


def _render_alarm(facts: Facts) -> str:
    label = facts.channel_label or "该通道"
    if facts.triggered is None or facts.threshold is None or facts.value is None:
        return f"{label}没有配置报警阈值，无法判断是否超标。"
    reading = f"{_fmt(facts.value)}{facts.unit}"
    limit = f"{facts.threshold:g}{facts.unit}"
    if facts.triggered:
        direction = "高于" if facts.threshold_is_maximum else "低于"
        return f"{label}当前 {reading}，已经{direction}报警阈值 {limit}，处于报警状态。"
    low, high = facts.threshold_low, facts.threshold_high
    if low is not None and high is not None:
        return (
            f"{label}当前 {reading}，在 {low:g}~{high:g}{facts.unit} 的正常范围内，"
            "一切正常。"
        )
    return f"{label}当前 {reading}，未超过报警阈值 {limit}，一切正常。"


def _render_measurement(facts: Facts) -> str:
    label = facts.channel_label or "该通道"
    unit = facts.unit

    if facts.kind is IntentKind.MAXIMUM and facts.maximum is not None:
        return f"{label}记录到的最高值是 {_fmt(facts.maximum)}{unit}。"
    if facts.kind is IntentKind.MINIMUM and facts.minimum is not None:
        return f"{label}记录到的最低值是 {_fmt(facts.minimum)}{unit}。"
    if facts.kind is IntentKind.AVERAGE and facts.average is not None:
        return (
            f"{label}的平均值是 {_fmt(facts.average)}{unit}"
            f"（共 {facts.sample_count} 个采样点）。"
        )

    if facts.value is None:
        return f"{label}现在还没有有效读数。"
    text = f"{label}现在是 {_fmt(facts.value)}{unit}"
    margin = _margin_clause(facts)
    if margin:
        return text + margin + "。"
    # 报警说，正常不说。这条不对称是有意的：越限是使用者无论如何都要知道的
    # 事，而"一切正常"可以由沉默表达。原先两侧都说，于是"现在多少度"这样一个
    # 只问了读数的问题，回来的是读数加一句没人问的判断。
    if facts.triggered is True:
        text += "，已超过报警阈值"
    return text + "。"


def _margin_clause(facts: Facts) -> str:
    """"还差多少就超限了" -- appended only when the sentence asked for it.

    A reading and its distance to the limit are two questions people ask
    in one breath（"现在多少度，还差多少超限"）, and the second is a
    subtraction over numbers the retrieval stage already holds. Answering
    both at once costs one clause and saves a round trip; the arithmetic
    stays in code, so the figure is grounded like any other.

    It used to be appended to *every* reading answer, which is a different
    thing and was wrong: "现在多少度" asked one question and got two
    answered. The clause now waits for ``margin_requested``. The margin
    itself is still computed and still travels in Facts -- the explain job
    lists it, and a later template may want it.
    """
    if not facts.margin_requested:
        return ""
    if facts.margin is None or facts.threshold is None:
        return ""
    limit = f"{facts.threshold:g}{facts.unit}"
    # 越限时说的是哪一侧，取决于命中的是上界还是下界：湿度低到 27.1%RH
    # 是"低于下限 30%RH"，写成"超出 30%RH"字面就错了。双向阈值引入之后
    # 这条分支才有第二种可能，原实现两侧共用一句话。
    if facts.margin < 0:
        if facts.threshold_is_maximum:
            return f"，已超出 {limit} 的报警上限 {_fmt(-facts.margin)}{facts.unit}"
        return f"，已低于 {limit} 的报警下限 {_fmt(-facts.margin)}{facts.unit}"
    bound = "上限" if facts.threshold_is_maximum else "下限"
    return f"，距 {limit} 的报警{bound}还有 {_fmt(facts.margin)}{facts.unit}"


ALARM_CLAIM_WORDS = ("超标", "告警", "故障", "危险", "报警状态")
"""Words that assert an alarm, refused unless the facts say one is on.

**This is a blacklist, and a blacklist is a mitigation, not a guarantee.**
Worth stating plainly, because it is a different kind of check from
:func:`numbers_are_grounded`: numbers form a closed set, so every one of
them can be traced back to a fact and the check is complete. Claims do
not. Deciding what a Chinese sentence asserts is itself a language
problem, and the tool best suited to it is the model being checked.

So this covers one specific failure that was actually observed, not
claims in general. A rehearsal on 2026-09-08 had the model turn "噪声记录
到的最高值是 95.0dB" into "……该值超出了规定的阈值，处于超标状态" -- every
number correct, the judgement invented (the MAXIMUM facts contain no
threshold comparison at all; it happened to be true, which is worse, not
better).

"报警" alone is deliberately absent: legitimate answers say 报警阈值 all
the time. False positives are accepted where they occur -- "未超标" is
refused along with "超标" -- because the cost is a stiffer sentence and
the alternative is parsing negation scope.
"""


def _claims_an_alarm(text: str, facts: Facts | None) -> bool:
    """Whether ``text`` asserts an alarm the facts do not support."""
    if facts is not None and facts.triggered is True:
        return False
    return any(word in text for word in ALARM_CLAIM_WORDS)


STATE_WORDS = (
    "正常", "恢复", "偏高", "偏低", "较高", "较低", "过高", "过低",
    "危险", "异常", "安全", "舒适", "良好",
) + ALARM_CLAIM_WORDS
"""Words by which a sentence passes judgement on the reading.

Wider than :data:`ALARM_CLAIM_WORDS`, which only covers claiming an alarm.
These cover the other direction and the vague middle -- "已恢复正常",
"噪声水平较高" -- neither of which the alarm blacklist sees, and both of
which a model produced unprompted once the template stopped stating the
state itself."""

LENGTH_SLACK = 1.4
LENGTH_MARGIN = 6
"""How much longer than the template a rewording may be.

Measured, not chosen: 30 rewordings across six scenarios split cleanly at
about 1.4x. Everything at or below it only reworded ("当前湿度测量结果为
61.9%RH。" at 1.29); everything above added something ("请注意保暖" at
1.75, "咱们刚记录的…这个数值目前就是监测到的最高值" at 2.06). The flat
margin exists because the templates are now short: on a ten-character
sentence a pure ratio would reject a natural rewording that added four
characters.

A cap on length is a crude instrument and catches only padding that says
something new *without* a judgement word. It is the second of two nets,
not the main one."""


ADVICE_WORDS = ("请注意", "建议", "记得", "小心", "务必", "应当", "请保持")
"""Openers of advice, which this system does not give.

Caught by name rather than by length: "请注意保暖" is only eight characters
past the template, well inside any tolerance wide enough for an ordinary
rewording, yet it is the clearest case of the model speaking for a system
that knows nothing about what the reader should wear. Tightening the
length cap until it caught this one would have meant fitting it to a
sample of thirty."""


def _has_state_claim(text: str) -> bool:
    return any(word in text for word in STATE_WORDS)


def _gives_advice(text: str) -> bool:
    return any(word in text for word in ADVICE_WORDS)


def _adds_an_unsupported_judgement(
    template_text: str, candidate: str, facts: Facts | None
) -> bool:
    """Did the rewording introduce a verdict the template did not carry?

    Allowed when the template already passes the same judgement (the model
    is then rewording it, which is its job) or when the facts show an alarm
    -- an over-limit reading may be described in whatever words fit.
    """
    if facts is not None and facts.triggered is True:
        return False
    if _has_state_claim(template_text):
        return False
    return _has_state_claim(candidate)


def _is_padded(template_text: str, candidate: str) -> bool:
    """Whether the rewording is materially longer than what it reworded."""
    return len(candidate) > len(template_text) * LENGTH_SLACK + LENGTH_MARGIN


def choose(
    template_text: str,
    model_text: str | None,
    facts: Facts | None,
    expanded: bool = False,
) -> tuple[str, AnswerSource]:
    """Pick between the template and a model rephrasing.

    The model's version is used only if it exists, is non-trivial, passes
    :func:`numbers_are_grounded`, claims no alarm the facts do not carry,
    passes no judgement the template did not, and is not materially longer
    than what it reworded. Anything else falls back to the template
    silently -- a slightly stiff sentence is a much better outcome than a
    confident wrong number.

``expanded`` turns the length cap off. It is set for the explain job,
    whose output is *meant* to be several times the length of the template
    -- it recounts the facts the template dropped. Without the switch the
    cap rejects every expansion, which is what it did for a few hours on
    2026-09-09 before a manual check caught it; no test covered a
    realistic explain output going through here.

    The last two checks were added 2026-09-09, after the normal-reading
    template stopped stating "处于正常范围" of its own accord. A shorter
    template turned out to invite padding: in 30 measured rewordings the
    model volunteered advice ("请注意保暖") and, more seriously, verdicts
    the facts did not support ("目前该区域已恢复正常" on a reading well
    inside its limits).
    """
    text, source, _ = judge(template_text, model_text, facts, expanded=expanded)
    return text, source


def judge(
    template_text: str,
    model_text: str | None,
    facts: Facts | None,
    expanded: bool = False,
) -> tuple[str, AnswerSource, CheckVerdict]:
    """:func:`choose`, plus which check decided.

    Split out 2026-09-23 so a caller can show *why* a rewording was used or
    refused. The checks, their order and their outcomes are exactly those
    :func:`choose` always applied -- ``choose`` is now this function with
    the verdict dropped, and a test compares the two on every case the
    phrasing tests exercise.
    """
    if model_text is None:
        return template_text, AnswerSource.TEMPLATE, CheckVerdict.NO_REPLY
    candidate = model_text.strip()
    if len(candidate) < 2:
        return template_text, AnswerSource.TEMPLATE, CheckVerdict.TOO_SHORT
    if not numbers_are_grounded(candidate, facts):
        return template_text, AnswerSource.TEMPLATE, CheckVerdict.UNGROUNDED_NUMBER
    if _claims_an_alarm(candidate, facts):
        return template_text, AnswerSource.TEMPLATE, CheckVerdict.UNSUPPORTED_ALARM
    if _adds_an_unsupported_judgement(template_text, candidate, facts):
        return template_text, AnswerSource.TEMPLATE, CheckVerdict.UNSUPPORTED_JUDGEMENT
    if _gives_advice(candidate) and not _gives_advice(template_text):
        return template_text, AnswerSource.TEMPLATE, CheckVerdict.ADVICE
    if not expanded and _is_padded(template_text, candidate):
        return template_text, AnswerSource.TEMPLATE, CheckVerdict.TOO_LONG
    return candidate, AnswerSource.MODEL, CheckVerdict.ACCEPTED


def facts_brief(facts: Facts) -> str:
    """Every fact behind an answer, one per line, for the explain job.

    The templates use a few of these and drop the rest: a reading question
    holds the current value, the range, the average, the sample count, the
    limit and the distance to it, and answers with one sentence about the
    first. Handing the whole list to the model is what lets it write a
    fuller answer *without* being told anything new -- the numbers are the
    same numbers the grounding check will hold it to.

    Deliberately labels rather than prose: this is data being listed, and
    a paragraph here would be the model rewriting a paragraph, which is
    the old job.
    """
    lines: list[str] = []
    if facts.channel_label:
        lines.append(f"通道：{facts.channel_label}")
    unit = facts.unit
    for label, value in (
        ("当前值", facts.value),
        ("最低值", facts.minimum),
        ("最高值", facts.maximum),
        ("平均值", facts.average),
    ):
        if value is not None:
            lines.append(f"{label}：{_fmt(value)}{unit}")
    if facts.sample_count:
        lines.append(f"采样点数：{facts.sample_count}")
    if facts.threshold_low is not None and facts.threshold_high is not None:
        lines.append(
            f"报警范围：{facts.threshold_low:g}~{facts.threshold_high:g}{unit}"
            "（超出两侧任一端都会报警）"
        )
    elif facts.threshold is not None:
        side = "高于" if facts.threshold_is_maximum else "低于"
        lines.append(f"报警阈值：{facts.threshold:g}{unit}（{side}即报警）")
    if facts.citation:
        lines.append(f"阈值依据：{facts.citation}")
    if facts.margin is not None:
        if facts.margin < 0:
            lines.append(f"已越过阈值：{_fmt(-facts.margin)}{unit}")
        else:
            lines.append(f"距阈值还有：{_fmt(facts.margin)}{unit}")
    if facts.triggered is not None:
        lines.append(f"是否越限：{'是' if facts.triggered else '否'}")

    for label, value, reading_unit in facts.readings:
        lines.append(f"{label}当前：{_fmt(value)}{reading_unit}")
    if facts.fan_mode:
        mode = _FAN_MODE_LABELS.get(facts.fan_mode, facts.fan_mode)
        lines.append(f"风扇模式：{mode}")
    if facts.fan_running is not None:
        lines.append(f"风扇状态：{'运行' if facts.fan_running else '停止'}")
    if facts.vent_temperature_max is not None:
        lines.append(f"通风温度阈值：{facts.vent_temperature_max:g}℃")
    if facts.vent_humidity_max is not None:
        lines.append(f"通风湿度阈值：{facts.vent_humidity_max:g}%RH")
    if facts.fan_reason:
        lines.append(f"判定原因：{facts.fan_reason}")
    return "\n".join(lines)
