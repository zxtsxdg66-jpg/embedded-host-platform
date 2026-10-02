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

from core.models import ChannelId
from device.sensors.channels import HUMIDITY_CHANNEL, NOISE_CHANNEL, TEMPERATURE_CHANNEL
from service.assistant import control
from service.assistant.models import (
    AnswerSource,
    CheckResult,
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

REFUSAL_OPENER = "这个我做不了："
"""所有"做不了"的回答共用的开头（2026-09-27）。此前关报警、改读数、删数据、播报、
系统没有的设备各有各的措辞，放在一起看像是几个人写的。统一成
"这个我做不了：〔原因〕。我能做的是〔相关的能力〕。"——原因各不相同，
结构与开头一致，用户一眼就知道这是一句拒绝，不必读到最后。"""

MANIPULATION_TEXT = "身份和权限不是一句话能改的，我照常按规则回答。"
"""冒充身份、要求忽略规则时回答的第一句（2026-09-27，``intent.is_manipulation``）。
后面接的是这句话去掉那段说法之后的正常回答；什么也不剩时接 :data:`CAPABILITY_BRIEF`。"""

CAPABILITY_BRIEF = "我能做的是查温度、湿度、噪声的读数，开关风扇，调通风阈值。"

ASSISTANT_NAME = "站内环境助手"

IDENTITY_TEXTS: dict[str, str] = {
    "who": (
        f"我是{ASSISTANT_NAME}，这套地铁站环境监测系统里的问答助手。" + CAPABILITY_BRIEF
    ),
    "model": (
        "我背后是一个在本机运行的小型语言模型，只负责理解问题和组织措辞；"
        "读数和设备动作都由系统代码负责，模型碰不到。"
    ),
    "maker": "我是一个毕业设计项目的一部分，是这套地铁站环境监测系统的问答模块。",
    "network": (
        "问答本身不联网，理解和措辞都在本机完成。"
        "只有在界面上点按钮上传时，归档的读数才会传到云端。"
    ),
}
"""身份问答（2026-09-27，:attr:`IntentKind.IDENTITY`）。固定句，不送改写：
小模型被问"你是谁"，很可能报出训练它的那家公司的产品名；"你其实是 GPT 吧"一类的话
也能把它带偏。名字"站内环境助手"是有意取的平实说法。"谁开发的"不写开发者姓名。
"不联网"说的是问答：上云是界面按钮背后的脚本，由人点了才传。"""

ANNOUNCE_REFUSAL_TEXT = (
    REFUSAL_OPENER + "语音播报只在读数越限时自动触发，不支持手动播放。"
    "我能做的是告诉你某个通道有没有超标，播报记录在活动日志里。"
)
"""Why this is a fixed string and never handed to the model: it carries no
number, so ``numbers_are_grounded`` has nothing to check, and a rephrase
that turned "不支持手动播放" into an offer to try would be accepted. The
sentence's whole job is to state a limit correctly -- the same reason
``CLARIFY_TEXT`` is not rephrased either."""

DELETE_REFUSAL_TEXT = (
    REFUSAL_OPENER
    + "删除数据不在我能做的事情里。读数分在三处——本机历史库、导出的归档文件、"
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
（``docs/decisions/06-history.md`` 第 2 节）。
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
    return not ungrounded_numbers(text, facts)


def ungrounded_numbers(text: str, facts: Facts | None) -> list[str]:
    """The numbers in ``text`` that do not trace back to ``facts``, in order.

    :func:`numbers_are_grounded` is this list being empty. Split out
    2026-09-26 so the web console can show *which* number failed the check.
    """
    found = _NUMBER_PATTERN.findall(text)
    if not found:
        return []
    if facts is None:
        return found

    allowed: set[str] = set(facts.citation_numbers())
    for number in facts.numbers():
        allowed.add(_fmt(number))
        allowed.add(f"{number:g}")
        if number.is_integer():
            allowed.add(str(int(number)))
    return [token for token in found if token not in allowed]


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
docs/decisions/06-history.md when history
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
    if facts.kind is IntentKind.CHANNEL_SET_REQUEST:
        return channel_set_text(facts)
    if facts.kind is IntentKind.ALARM_OFF_REQUEST:
        return ALARM_OFF_REFUSAL_TEXT
    if facts.kind is IntentKind.IDENTITY:
        return IDENTITY_TEXTS.get(facts.topic, IDENTITY_TEXTS["who"])
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


ALARM_OFF_REFUSAL_TEXT = (
    REFUSAL_OPENER + "报警是按阈值自动判定的，读数回到正常范围后会自动解除。"
    "我能做的是开关风扇、调通风阈值。"
)
""""帮我关掉警报"的回答（2026-09-27，:attr:`IntentKind.ALARM_OFF_REQUEST`）。
固定句，不送改写，理由同 :data:`DELETE_REFUSAL_TEXT`。"""


def channel_set_text(facts: Facts) -> str:
    """"把温度调节至40度"的回答（2026-09-27，:attr:`IntentKind.CHANNEL_SET_REQUEST`）。

    固定句，不送模型改写，理由同 :data:`DELETE_REFUSAL_TEXT`：它的全部任务是把
    "做不到"说准，改写把它软化成一个提议，现有的检查一道也拦不住。不带读数——
    问的是改它，回一个当前值等于没听见。"""
    label = facts.channel_label or "读数"
    if facts.channel in _VENT_LABELS:
        return (
            f"{REFUSAL_OPENER}{label}是传感器测出来的，没法直接调节。"
            f"我能做的是开关风扇，或者改{label}的通风阈值，"
            f"比如说「{label}通风阈值调到多少」。"
        )
    return (
        f"{REFUSAL_OPENER}{label}是传感器测出来的，没法直接调节。我能做的是开关风扇。"
    )


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
            "一切正常。" + care_line(facts)
        )
    return f"{label}当前 {reading}，未超过报警阈值 {limit}，一切正常。" + care_line(
        facts
    )


def _render_measurement(facts: Facts) -> str:
    label = facts.channel_label or "该通道"
    unit = facts.unit

    if facts.kind is IntentKind.MAXIMUM and facts.maximum is not None:
        return f"{label}记录到的最高值是 {_fmt(facts.maximum)}{unit}。"
    if facts.kind is IntentKind.MINIMUM and facts.minimum is not None:
        return f"{label}记录到的最低值是 {_fmt(facts.minimum)}{unit}。"
    if facts.kind is IntentKind.SAMPLE_COUNT:
        return f"{label}本次启动以来记录了 {facts.sample_count} 个读数。"
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
    return text + "。" + care_line(facts)


_CARE_TEXT: dict[tuple[ChannelId, str], str] = {
    (TEMPERATURE_CHANNEL, "high"): "有点热，注意防暑降温。",
    (TEMPERATURE_CHANNEL, "low"): "有点凉，注意保暖，别着凉。",
    (HUMIDITY_CHANNEL, "high"): "空气偏潮，体感会有些闷。",
    (HUMIDITY_CHANNEL, "low"): "空气偏干，记得多喝水。",
}
"""读数出了舒适区间时模板补的一句关心（2026-09-27）。

方向由取数层按 ``retrieval.COMFORT_BANDS`` 判定，这里只负责说出来；
模型改写时可以换说法，不能换方向，见 :data:`_CARE_GROUPS`。
此前的立场是"系统不给建议"（:data:`ADVICE_WORDS`），依据是模型不知道读者该穿什么
——那句"请注意保暖"是在 25℃ 时说的。问题出在由谁判断冷热，不在关心本身：
判断交给代码之后，这句话就和读数一样有出处。"""


_MISMATCH: dict[tuple[str, str], str] = {
    ("cold", "high"): "cold_on_hot",
    ("hot", "low"): "hot_on_cold",
    ("dry", "high"): "dry_on_humid",
    ("humid", "low"): "humid_on_dry",
    ("quiet", "near"): "quiet_on_loud",
    ("quiet", "high"): "quiet_on_alarm",
    ("loud", "ok"): "loud_on_quiet",
}

TEASING_MISMATCHES = frozenset(
    {"cold_on_hot", "hot_on_cold", "dry_on_humid", "humid_on_dry"}
)
"""用调侃语气改写的那几种（``assistant.TEASE_SYSTEM_PROMPT``）。噪声两种不在内：
说"安静"而读数接近报警线，照读数说即可；说"好吵"而读数低，更可能是没采到那一阵
（见 :func:`_noise_line`），不该调侃。"""

_MISMATCH_LINES: dict[str, tuple[str, ...]] = {
    "cold_on_hot": (
        "你觉得冷？可这读数已经高过 {hi}{unit}，按数据看是偏热的。"
        "传感器测的是站内这一处，你那儿说不定正对着空调风口。",
        "你喊冷？这句我可不太敢接：读数比 {hi}{unit} 还高，明明偏热。"
        "是不是刚从空调房出来？",
        "这温度还觉得冷，挺抗热的嘛。按读数已经高过 {hi}{unit}，是偏热的，"
        "那种感觉可能只是你那一处的。",
    ),
    "hot_on_cold": (
        "你觉得热？可这读数比 {lo}{unit} 还低，按数据看是偏凉的。"
        "可能是刚一路走得急。",
        "你喊热？这句我可不太敢接：读数低于 {lo}{unit}，明明偏凉。"
        "是不是刚小跑过来？",
        "这温度还觉得热，火力挺旺啊。按读数已经低于 {lo}{unit}，是偏凉的。",
    ),
    "dry_on_humid": (
        "你觉得干？可湿度已经高过 {hi}{unit}，按数据看是偏潮的。"
        "传感器测的是站内这一处。",
        "你嫌干？这句我可不太敢接：湿度比 {hi}{unit} 还高，明明偏潮。",
    ),
    "quiet_on_loud": (
        "你觉得安静？可这读数离 {thr}{unit} 的报警线不远了。传感器测的是站内这一处，"
        "你那儿可能正好离声源远一点。",
    ),
    "quiet_on_alarm": (
        "你觉得安静？可这读数已经超过 {thr}{unit} 的报警线了。传感器测的是站内这一处。",
    ),
    "humid_on_dry": (
        "你觉得潮？可湿度低于 {lo}{unit}，按数据看是偏干的。"
        "传感器测的是站内这一处。",
        "你嫌潮？这句我可不太敢接：湿度比 {lo}{unit} 还低，明明偏干。",
    ),
}
"""用户说的体感与读数相反时的回答（2026-09-27）：轻轻调侃一句，指出读数在哪一边。

- **不给建议**：说冷时劝"注意防暑"接不住那句话，劝"注意保暖"又和读数相反，两头都不对。
- **不附和**：句中用户的感受只以"你觉得冷""你喊冷""还觉得冷"的转述出现，
  出口检查把这类转述剔除后再查方向词（:data:`_QUOTED_FEELING`），模型因此能说
  "34 度你还喊冷"，说不出"确实挺冷"。
- **不猜身体原因**：只说到"传感器测的是这一处"为止，系统没有依据谈健康。
- 不写"舒适"二字：那一组词模板一旦出现，改写就能说"处于舒适区间"
  （见 :data:`_CARE_GROUPS`）。

几句轮着用，按读数挑（同一读数总是同一句，便于复现），模型改写被拦时退回的也是它。"""


def _noise_line(facts: Facts) -> str:
    """噪声那句（2026-09-27）：只说离报警线多远，不给建议。

    - 离报警线 5 dB 以内：说"离报警线不远了"。
    - 越限：报警句已经说了，这里不再加。
    - 说"好吵"而读数低：不调侃也不附和，承认可能漏测——列车进站那一阵只有几秒，
      采样可能正好没赶上；附上本次运行记到的最高值，那个数也许正是用户听到的。
    - 说"好安静"而读数接近或超过报警线：照读数说。
    - 用体感问（"吵不吵"）而读数低：说离报警线还远。"""
    if facts.threshold is None:
        return ""
    thr, unit = f"{facts.threshold:g}", facts.unit
    mismatch = mismatch_kind(facts)
    if mismatch == "loud_on_quiet":
        peak = (
            f"；本次运行记到的最高是 {_fmt(facts.maximum)}{unit}"
            if facts.maximum is not None
            else ""
        )
        return (
            f"这一刻测到的离 {thr}{unit} 的报警线还远。列车进站那一阵可能正好没采到，"
            f"传感器测的也只是站内这一处{peak}。"
        )
    if mismatch:
        return _MISMATCH_LINES[mismatch][0].format(thr=thr, unit=unit)
    if facts.comfort == "near":
        return f"离 {thr}{unit} 的报警线不远了。"
    if facts.comfort == "ok" and facts.felt:
        return f"离 {thr}{unit} 的报警线还远。"
    return ""


def mismatch_kind(facts: Facts) -> str:
    """体感与读数相反时返回 :data:`_MISMATCH_LINES` 的键，否则返回空串。"""
    return _MISMATCH.get((facts.felt_claim, facts.comfort), "")


def care_line(facts: Facts) -> str:
    """模板末尾那句关心；区间内且不是用体感问的就不说。

    区间内但问的是"有点冷啊"时，说读数在舒适区间内——不说"不冷"，免得给改写
    留下一个带方向的词去改反（见 :data:`_CARE_GROUPS`）。"""
    if facts.channel is None or facts.value is None or not facts.comfort:
        return ""
    if facts.kind not in (IntentKind.CURRENT_VALUE, IntentKind.ALARM_STATE):
        return ""
    if facts.past_scoped:
        return ""
    if facts.channel == NOISE_CHANNEL:
        return _noise_line(facts)
    mismatch = mismatch_kind(facts)
    if mismatch and facts.comfort_low is not None and facts.comfort_high is not None:
        lines = _MISMATCH_LINES[mismatch]
        line = lines[int(round(facts.value * 10)) % len(lines)]
        return line.format(
            lo=f"{facts.comfort_low:g}", hi=f"{facts.comfort_high:g}", unit=facts.unit
        )
    if facts.comfort == "ok":
        if not facts.felt or facts.comfort_low is None or facts.comfort_high is None:
            return ""
        return (
            f"在 {facts.comfort_low:g}~{facts.comfort_high:g}{facts.unit} "
            "的舒适区间内。"
        )
    return _CARE_TEXT.get((facts.channel, facts.comfort), "")


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


ADVICE_WORDS = ("注意", "建议", "记得", "小心", "务必", "应当", "请保持")
"""Openers of advice, which the model may not add on its own.

2026-09-27: advice is no longer refused outright. When the reading is
outside the comfort band the template itself carries a line of care
(:func:`care_line`), and a rewording may then word that care its own way
-- in the same direction only (:data:`_CARE_GROUPS`). What stays refused
is advice the template did not give. "请注意" became "注意" so that the
template's "注意防暑" counts as advice given. The history below is why
the model is not the one deciding.

Caught by name rather than by length: "请注意保暖" is only eight characters
past the template, well inside any tolerance wide enough for an ordinary
rewording, yet it is the clearest case of the model speaking for a system
that knows nothing about what the reader should wear. Tightening the
length cap until it caught this one would have meant fitting it to a
sample of thirty."""


_CARE_GROUPS: tuple[tuple[str, ...], ...] = (
    ("热", "暑", "降温"),
    ("冷", "凉", "保暖", "着凉", "添衣", "加衣", "感冒"),
    ("潮", "闷", "除湿"),
    ("干", "喝水", "补水", "加湿"),
    ("舒适", "舒服", "宜人", "适宜"),
    ("吵", "闹", "嘈杂"),
    ("安静", "静"),
    (
        "降至", "降到", "升至", "升到", "下降", "上升", "回落", "回升",
        "降低了", "升高了",
    ),
)
"""体感方向与变化趋势的几组词（2026-09-27）。改写里出现某一组的词，模板里就必须也有同一组的词。

这是建议措辞检查的另一半：模板说"有点热，注意防暑"，改写成"天挺热的，记得防暑"可以，
改成"注意保暖"就被拦下——关心可以换说法，方向必须与代码的判定一致。
最后一组是变化趋势（2026-09-27 第三批对抗实验）：0.8 温度下改写两次写出"已降至 49.5dB"
"室温已降至 15.2℃"——只有一个采样点，系统从没见过"降"。模板从不陈述趋势，所以这一组等于
不许改写凭空说变化。

第五组是"舒适"本身：对抗实验里 0.8 温度的解释档把 31.4℃ 说成"处于舒适区间"，
前四组都没拦住——模板说了"有点热"，没说"舒适"，改写就不许说。代价是"已超出舒适区间"
这种说对了的也退回模板。
与 :data:`ALARM_CLAIM_WORDS` 一样是词表，是缓解不是保证；单字"干""凉"会误伤
"干净""凉快"，误伤的代价是退回模板，可以接受。"""


_QUOTED_FEELING = re.compile(
    r"(?:(?:你|您)(?:说|觉得|感觉|喊|嫌|觉着)|还(?:喊|嫌|说|觉得|感觉))"
    r"(?:得)?(?:有点|有些|好|太|很|这么|挺)?(?:冷|凉|冻|热|烫|潮|闷|湿|干|燥|吵|闹|安静)"
)
"""转述用户体感的说法（2026-09-27）："你觉得冷""还喊冷"。检查方向词之前从模板与改写里
一并剔除：它们说的是用户的感受，不是系统的判断。要求主语"你"或"还"，
"感觉有点冷"没有主语，读作系统在说，照查不误。"""


def _care_words_added(template_text: str, candidate: str) -> list[str]:
    """改写里出现、而模板里没有同组词的体感词（用户体感的转述不算）。"""
    template_text = _QUOTED_FEELING.sub("", template_text)
    candidate = _QUOTED_FEELING.sub("", candidate)
    added: list[str] = []
    for group in _CARE_GROUPS:
        if any(word in template_text for word in group):
            continue
        added.extend(word for word in group if word in candidate)
    return added


_AGREEING_WORDS = (
    "说得对", "说的对", "没错", "确实如此", "按您的体感", "按你的体感",
    "听您的", "听你的", "您说了算", "你说了算",
)
"""不带方向词的附和（2026-09-27 对抗实验，0.8 温度）：15.2℃ 说"好热啊"，改写成
"你说得对……那咱们就按您的体感来吧"，方向词一个没有，:data:`_CARE_GROUPS` 查不到。
只在模板本身是"体感与读数相反"的调侃句时查（模板里有 :data:`_QUOTED_FEELING` 的转述），
普通改写里一句"没错"无伤大雅，不因此退回。"""


def _advice_problem(template_text: str, candidate: str) -> list[str]:
    """建议措辞检查找到的词：模板没给建议而改写给了，体感方向对不上，
    或者在调侃句里附和了用户。"""
    found: list[str] = []
    if _gives_advice(candidate) and not _gives_advice(template_text):
        found.extend(w for w in ADVICE_WORDS if w in candidate)
    found.extend(_care_words_added(template_text, candidate))
    if _QUOTED_FEELING.search(template_text):
        found.extend(w for w in _AGREEING_WORDS if w in candidate)
    return found


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
    if _advice_problem(template_text, candidate):
        return template_text, AnswerSource.TEMPLATE, CheckVerdict.ADVICE
    if not expanded and _is_padded(template_text, candidate):
        return template_text, AnswerSource.TEMPLATE, CheckVerdict.TOO_LONG
    return candidate, AnswerSource.MODEL, CheckVerdict.ACCEPTED


_CHECK_VERDICTS = {
    "grounding": CheckVerdict.UNGROUNDED_NUMBER,
    "alarm": CheckVerdict.UNSUPPORTED_ALARM,
    "judgement": CheckVerdict.UNSUPPORTED_JUDGEMENT,
    "advice": CheckVerdict.ADVICE,
    "length": CheckVerdict.TOO_LONG,
}
"""Which :class:`CheckVerdict` each of :func:`explain_checks`' results
stands for, in :func:`judge`'s order."""


def explain_checks(
    template_text: str,
    model_text: str | None,
    facts: Facts | None,
    expanded: bool = False,
) -> tuple[CheckResult, ...]:
    """Run each of :func:`judge`'s five checks on its own, for display.

    :func:`judge` stops at the first check that fails, which is all an
    answer needs; a person watching wants to see all five. This evaluates
    every one independently and says what each found. **It decides
    nothing** -- the assistant still acts on :func:`judge` alone -- and a
    test holds that the first failure here is always the check ``judge``
    names. Empty when the reply never reached the checks (none, or shorter
    than two characters). Added 2026-09-26.
    """
    if model_text is None:
        return ()
    candidate = model_text.strip()
    if len(candidate) < 2:
        return ()

    missing = ungrounded_numbers(candidate, facts)
    alarm_words = (
        []
        if facts is not None and facts.triggered is True
        else [w for w in ALARM_CLAIM_WORDS if w in candidate]
    )
    judgement_words = (
        [w for w in STATE_WORDS if w in candidate]
        if _adds_an_unsupported_judgement(template_text, candidate, facts)
        else []
    )
    advice_words = _advice_problem(template_text, candidate)
    limit = len(template_text) * LENGTH_SLACK + LENGTH_MARGIN
    if expanded:
        length = CheckResult("length", True, "解释档不设长度上限")
    else:
        length = CheckResult(
            "length",
            not _is_padded(template_text, candidate),
            f"{len(candidate)} 字 / 上限 {limit:.0f} 字",
        )
    return (
        CheckResult("grounding", not missing, "、".join(missing)),
        CheckResult("alarm", not alarm_words, "、".join(alarm_words)),
        CheckResult("judgement", not judgement_words, "、".join(judgement_words)),
        CheckResult("advice", not advice_words, "、".join(advice_words)),
        length,
    )


_KIND_DESCRIPTIONS: dict[IntentKind, str] = {
    IntentKind.CURRENT_VALUE: "当前读数",
    IntentKind.MAXIMUM: "最高值",
    IntentKind.MINIMUM: "最低值",
    IntentKind.AVERAGE: "平均值",
    IntentKind.ALARM_STATE: "是否超标",
    IntentKind.THRESHOLD_INFO: "报警阈值",
    IntentKind.SAMPLE_COUNT: "记录了多少个读数",
    IntentKind.FAN_STATE: "风扇现在的状态",
    IntentKind.DEVICE_LIST: "在线设备数量",
    IntentKind.FAN_ON: "把风扇切到手动常开",
    IntentKind.FAN_OFF: "把风扇切到手动常关",
    IntentKind.FAN_AUTO: "把风扇交给自动控制",
    IntentKind.SET_VENT_THRESHOLD: "修改通风阈值",
}
"""代码给模型的理解写的说明，用在 ④ 与 ⑤（docs/decisions/03-intent.md）。
这些是**系统真有的能力**的名字，反问里的选项只可能从这里来。"""

_NO_POSSESSIVE = frozenset({IntentKind.ALARM_STATE, IntentKind.SAMPLE_COUNT})
"""说明里不加"的"的两类："湿度是否超标""温度记录了多少个读数"。"""

_CHANNEL_NAMES = {
    TEMPERATURE_CHANNEL: "温度",
    HUMIDITY_CHANNEL: "湿度",
    NOISE_CHANNEL: "噪声",
}


def describe(intents: tuple[Intent, ...] | list[Intent]) -> str:
    """几条同类意图合起来的一句说明："温度、湿度的当前读数"。"""
    if not intents:
        return ""
    what = _KIND_DESCRIPTIONS.get(intents[0].kind, intents[0].kind.value)
    channels = [
        _CHANNEL_NAMES.get(i.channel, str(i.channel)) for i in intents if i.channel
    ]
    if not channels:
        return what
    joiner = "" if intents[0].kind in _NO_POSSESSIVE else "的"
    return f"{'、'.join(channels)}{joiner}{what}"


def interpretation(intents: tuple[Intent, ...] | list[Intent]) -> str:
    """④：模型分类出来的提问，回答前先说明是按什么理解的。

    只在规则没认出、由模型给了标签的回答前加。模型毫不犹豫地选错时不会反问，
    这句话是让错读一眼可见的那道补救——"记录了多少数据"曾被答成设备数，
    而回答本身读起来完全通顺。"""
    return f"我理解你问的是「{describe(intents)}」："


INTERPRETATION_TAIL = "理解错了的话，换个说法再问一次。"

CHOICE_CANCELLED_TEXT = "好，那换个说法再问一次？"


FAN_SPEED_TEXT = REFUSAL_OPENER + "风扇只能开、关或交给自动，调不了转速。"


def absent_notice(
    devices: list[str],
    measures: list[str],
    partial: bool,
    fan_speed: bool = False,
    station_reading: bool = False,
) -> str:
    """说明句子里哪些东西系统没有（2026-09-26，见 ``intent._ABSENT_DEVICES``）。

    2026-09-27 起与其它拒绝同一句式（:data:`REFUSAL_OPENER`）；
    同一句里还有能做的那一半时
    开头换成"这一半我做不了："。

    ``partial`` 为真表示同一句里还有系统能做的那一半，措辞说"这一半"；
    否则说"这件事"。``station_reading`` 为真表示问的是"空调现在几度"这类话，
    后面接的是站内读数。名字只来自那两张表，不会出现句子之外的东西。"""
    if station_reading:
        return f"这个系统里没有{'、'.join(devices)}，下面是站内的读数。"
    reasons: list[str] = []
    if fan_speed:
        reasons.append("风扇只能开、关或交给自动，调不了转速")
    if devices:
        reasons.append(f"系统里没有{'、'.join(devices)}")
    if measures:
        reasons.append(f"系统测不了{'、'.join(measures)}")
    if measures and not devices and not fan_speed:
        able = "它只测站内的温度、湿度和噪声。"
    elif devices:
        able = "我能控制的只有风扇。"
    else:
        able = ""  # 只有调速：原因里已经说了风扇能做什么
    opener = "这一半我做不了：" if partial else REFUSAL_OPENER
    return f"{opener}{'；'.join(reasons)}。{able}"


def choice_text(options: tuple[Intent, ...] | list[Intent]) -> str:
    """⑤：模型拿不准时给了几个候选，由代码写出的反问。

    选项文字只来自 :data:`_KIND_DESCRIPTIONS`，因此不会出现系统没有的能力；
    指令类选项写明动作本身，用户挑它就是授权（见 docs/decisions/03-intent.md）。"""
    labels = [f"「{describe([o])}」" for o in options]
    if len(labels) == 2:
        body = f"{labels[0]}，还是{labels[1]}"
    else:
        body = "、".join(labels[:-1]) + f"，还是{labels[-1]}"
    return f"这句我拿不准。你是想问{body}？回个序号就行。"


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
    if facts.comfort_low is not None and facts.comfort_high is not None:
        lines.append(
            f"舒适区间：{facts.comfort_low:g}~{facts.comfort_high:g}{unit}"
        )
    care = care_line(facts)
    if care and mismatch_kind(facts):
        lines.append(f"用户说的体感与读数相反（照读数说，别附和，别给建议）：{care}")
    elif care:
        lines.append(f"体感提醒（照这个方向说）：{care}")

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
