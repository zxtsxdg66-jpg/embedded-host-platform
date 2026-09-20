"""Stage 1: turn a Chinese question into an :class:`Intent`.

Rules first, and rules alone are enough for every question this system is
expected to answer -- the vocabulary is small and closed (three channels,
one fan, a device list, a few thresholds). A language model is only ever
an accuracy aid for unusual phrasings, never a requirement; see
docs/02_Architecture/Assistant_Design.md section 2.

Matching is keyword-based rather than regex-heavy on purpose. Chinese has
no word boundaries, so substring containment is the natural test, and it
degrades gracefully: an unmatched question falls through to HELP, which
tells the user what *can* be asked instead of guessing wrong.
"""

from __future__ import annotations

import re

from core.models import ChannelId
from device.sensors.channels import (
    HUMIDITY_CHANNEL,
    NOISE_CHANNEL,
    TEMPERATURE_CHANNEL,
)
from service.assistant.models import Intent, IntentKind

_CHANNEL_WORDS: tuple[tuple[ChannelId, tuple[str, ...]], ...] = (
    (
        TEMPERATURE_CHANNEL,
        (
            "温度", "气温", "室温", "热", "冷",
            "temperature", "temp",
        ),
    ),
    (
        HUMIDITY_CHANNEL,
        ("湿度", "湿", "潮", "闷", "干不干", "干燥", "humidity", "humid"),
    ),
    (
        NOISE_CHANNEL,
        (
            "噪声", "噪音", "分贝", "吵", "闹腾", "吵闹", "大声", "声音",
            "安静", "响", "noise", "db",
        ),
    ),
)
"""Channel keywords, most specific first within each group.

Order between groups matters: "湿度" contains no other channel's word, but
the bare "湿" fallback must not be tested before "温度" — a question about
温度 does not contain 湿, so in practice they do not collide, and keeping
温度 first makes that explicit rather than accidental.
"""

_STATISTIC_WORDS: tuple[tuple[IntentKind, tuple[str, ...]], ...] = (
    (IntentKind.AVERAGE, ("平均", "均值", "平时", "一般在", "average", "mean")),
    (
        IntentKind.MAXIMUM,
        ("最高", "最大", "峰值", "最吵", "最闹", "最响", "最湿", "最热", "max"),
    ),
    (
        IntentKind.MINIMUM,
        ("最低", "最小", "最安静", "最静", "最干", "最冷", "min"),
    ),
)
"""Superlatives in the colloquial register too, because the rules were
otherwise reading them as a request for the *current* value -- "这一阵子
最吵到多少" once answered with the reading at that instant. It was not a
wrong number, which is what made it easy to miss.

The list grew twice, both times from measurement rather than guesswork: a
demo dry-run added 最吵/最闹/最响, a 65-question batch added 最干/最湿/平时,
and the batch re-run after the explain job added 最热/最冷. Each addition
turns a question that needed a 3-second model call into one the rules
answer instantly and identically every time -- worth more here than any
amount of prompt tuning."""

_FAN_ON_WORDS = (
    "开", "启动", "转起来", "吹一下", "吹吹", "来风",
)
"""Just 开 carries most of these: 打开／开启／开一下／开起来／开开 all
contain it. The bare word is listed rather than the long forms because the
long forms were what the list held before, and a real user said 开风扇,
把风扇开了, 风扇开, 能开风扇不 and 那你开开呗 -- five phrasings, none of
which matched, all of which contain 开. Enumerating variants loses to
matching the verb; the question/instruction split is handled by
``_FAN_STATE_WORDS`` above instead of by keeping this list narrow."""

_FAN_OFF_WORDS = (
    "关", "停", "别转", "别开", "不用开", "不要开", "无需开",
)
"""Checked before the on-words, so a negated instruction ("别开风扇") is
read as off rather than matching the 开 inside it."""

_FAN_AUTO_WORDS = (
    "自动", "自行决定", "自己决定", "系统决定", "系统来定", "系统控制",
    "交给系统",
)
"""Checked before the off- and on-words, which is what these phrasings need.

2026-09-14 held-out test: "风扇让系统自己决定开关" means *hand it back to
automatic*, but it contains no 自动, so it fell through to the off-words and
the 关 inside 开关 switched the fan to manual-off -- the one misreading in
that run with a side effect. Listing the phrasings is what fixes it; the
on/off lists stay wide.

"自己控制" is deliberately absent: "我自己控制风扇" means the opposite, manual.
A question built from the same words ("风扇是系统决定的吗") is caught by
``_FAN_STATE_WORDS`` first."""

_FAN_STATE_WORDS = (
    "开着", "关着", "转着", "在转", "没转", "转吗", "转没转",
    "开没开", "关没关", "开了没", "关了没", "开了吗", "关了吗",
    "停了吗", "开着没", "状态", "为什么", "为啥", "为何", "怎么回事",
    "什么时候", "多久", "自动吗", "自动的吗", "是自动",
    "决定的吗", "控制的吗", "是系统",
)
"""Markers that a sentence about the fan is asking rather than telling.

Tested before every instruction branch, because the widened word lists
above would otherwise read the 开 in "风扇开着吗" as an order. Chinese
does not separate the two moods by syntax here -- 能开风扇吗 is a request
and 风扇开着吗 is a question, and both end in 吗 -- so the split is drawn
on *state descriptors* (开着/在转/开了没) rather than on question
particles, which appear in both."""
_CONSULTATIVE_WORDS = (
    "是不是该", "是不是要", "是不是得", "该不该", "应不应该",
    "要不要", "需不需要", "会不会",
    "对吧", "对不对", "是吧", "你说呢", "你觉得", "你看呢",
    "假设", "假如", "如果", "要是",
)
"""征询意见与假设的说法：问的是"要不要做"，不是"去做"。

2026-09-14 的 32 句鲁棒性实验里，七句这样的话有五句被直接执行——"风扇是不是该开了"
开了风扇，"太热了是不是该把通风阈值调到 20 度"真把阈值改了。它们与命令在关键词层面同形：
同样含"开"、同样含"调到"，差别只在语气。

判不准时偏向当成提问，理由是两个方向的代价不对称：把命令读成提问，用户再说一句就是了；
把征询读成命令，风扇已经转了。这也正是当初那条原则——用户问"要不要开"，
是在征求系统的建议，而系统不替用户拿主意，该做的是把风扇状态与通风阈值摆出来。

"能不能"刻意不在表内：它读起来像征询，实际是请求的常见说法——`_FAN_ON_WORDS` 的注释里
记着真实用户说过"能开风扇不"。同理不收单字"该"与"要"，它们在"该关了""要开风扇"里
就是命令。"""

_SET_WORDS = (
    "调到", "调成", "调整到", "设为", "设成", "设置为", "改成", "调低", "调高",
)
"""Instruction vocabulary, kept separate from the question vocabulary.

Only consulted once a fan word is present, which is what stops "把灯关掉"
or "停止采集" from being read as a fan command: the rules answer about the
one actuator this system has, and nothing else.
"""

_DEGREE_HINTS = ("℃", "度")
_PERCENT_HINTS = ("%", "％")
"""Fallback channel hints for an instruction that names a unit but not a
channel -- "通风阈值调到 28 度". Only used for threshold setting, where a
missing channel means refusing outright; for a *question* guessing would
be worse than the existing "which channel?" behaviour."""

_ALARM_WORDS = (
    "超标", "超限", "报警", "告警", "正常吗", "有没有超", "超了", "超没超",
    "太大了", "太热了", "太吵了", "太高了", "alarm",
)
""""是不是太大了"问的是有没有越线，不是当前值是多少——2026-09-08 的 65 句评测里
"声音是不是太大了"被答成了当前读数，数字没错但答非所问。

"太……了"这一组放在这里而不放进通道词，是因为它表达的是判断而不是对象；
句子里的通道仍由通道词认出来。指令方向不受影响：风扇分支在通道分支之前，
"太热了让那个吹风的转起来"里的"吹风"先被认出，仍然是一条指令。"""
_THRESHOLD_WORDS = (
    "阈值", "标准", "限值", "上限", "下限", "多少算", "多大声算",
    "低于多少", "高于多少", "超过多少", "threshold",
)
"""阈值词表在报警词表之前被检查（见 :func:`recognise`），因此"湿度低于多少会报警"
里的"报警"不会把它抢成一个关于当前读数的问题——问的是那条线画在哪，不是现在越没越线。"""
_FAN_WORDS = ("风扇", "通风", "换气", "排风", "吹", "fan")
"""吹风 was added after a rehearsal run: "让那个吹风的转起来" names the
actuator in a way none of the other words match, so the sentence fell
through to the model -- which classified it correctly only about half the
time. A word the rules know is answered instantly and identically every
time, which is worth more here than any amount of model coaxing."""
_DEVICE_WORDS = ("设备", "在线", "几台", "device", "online")

_ANNOUNCE_WORDS = (
    "播报", "播音", "播放", "语音", "喇叭", "发声", "出声", "说句话", "说话",
)
"""Words that name the *speaking* itself. Each is unambiguous on its own:
none of them is a channel keyword, so matching one is enough."""

_SOUND_HINTS = ("响", "叫", "出个声")
_TEST_HINTS = ("测试", "试一下", "试试", "试下", "一声", "能不能")
"""The weaker half. 响 is a noise-channel keyword ("外面很响吗" is a
question about sound level), so it may only be read as a request to speak
when the sentence also asks to *try* something. Both halves are required
precisely because either alone has an ordinary reading."""

_CLOUD_SYNC_WORDS = (
    "传上去", "传上云", "上传", "同步到云", "同步上云", "传到云", "上云",
    "备份到云", "云端备份",
)
"""Words that name *sending the archive up*. Like the delete list, each
names the act on its own.

Deliberately **not** bare 备份 or 同步: 同步 shows up in ordinary talk about
the phone and the desktop showing the same reading ("手机跟电脑同步吗"),
which is a question about the gateway, not a request to upload. Every
entry here either says 云 outright or is 上传, which in this system has
only one meaning."""

_CLOUD_VIEW_WORDS = (
    "云上有什么", "云上有哪些", "云端有什么", "云端有哪些",
    "传了哪些", "传了什么", "传上去的", "已经传的", "传过的",
    "看看云", "查看云", "云上的文件", "云端的文件", "打开控制台",
)
"""Words that ask to *look at* what is already uploaded.

Longer phrases than the other lists on purpose. 单说"云"或"看看"都太泛——
"云端只存不算吗"是在问设计，"看看温度"是在问读数。每一条都把「云」与
「看/传了什么」绑在一起，才读成一次查看请求。

放在 :data:`_CLOUD_SYNC_WORDS` **之前**判定："把传上去的文件看一下"两边都沾，
而它问的是看，不是再传一次。"""

_DELETE_WORDS = (
    "删除", "删掉", "删了", "删一下", "删干净",
    "清空", "清除", "清理", "清一清", "清掉",
    "抹掉", "销毁", "格式化",
)
"""Words that name *destroying data*. Every entry is at least two
characters and each names the act on its own, so one match is enough --
the same bar :data:`_ANNOUNCE_WORDS` meets.

Two exclusions are deliberate, and both would be real regressions:

- **No bare 删 or 清.** 清 alone lives inside 清楚 ("说清楚点"), which is
  an ordinary thing to say to an assistant; a single character would
  turn that into a refusal.
- **No 掉 or 关掉 family.** 关掉 is how people turn the fan off
  ("把风扇关掉"). Only the 删/清-rooted compounds qualify, so a shutdown
  instruction is never read as a deletion request.

Unlike the announce pairing there is no weak half here: none of these
words has an ordinary non-deleting reading in this system's vocabulary,
so requiring a second signal would only create misses."""
_BARE_ON_WORDS = ("打开", "开一下", "开起来", "开开", "启动", "开了吧", "开吧")
_BARE_OFF_WORDS = ("关掉", "关上", "关了", "关一下", "停一下", "停了", "关吧")
"""On-off phrasings that名 no object.

Longer than the fan-branch lists on purpose: those run only after a fan
word has already been matched, so a bare 开 is safe there. Here nothing
has been established yet, and 开/关 alone appear in far too much ordinary
Chinese ("开会了吗"、"关于噪声"), so only phrasings that read as a command
on their own are listed."""

_STRICTLY_PAST_WORDS = (
    "昨天", "昨日", "昨晚", "前天", "前几天",
    "上周", "上个星期", "上个月",
    "今早", "上次", "历史", "小时前", "分钟前",
)
_INCLUDES_NOW_WORDS = ("这周", "本周", "这个月", "今天", "今日")
"""Periods that contain the present moment.

Split out 2026-09-14 after a user asked "今天天气不挺好的 咋地铁站这么热啊
现在是不是都快30度了" and was told the system keeps no earlier data before
getting the current reading. 今天 matters for a statistic -- today's maximum
may predate start-up -- but not for the current reading, which is the same
whatever day it is. So these words mark statistics only; the current-value
branch consults :data:`_STRICTLY_PAST_WORDS` alone."""

_PAST_SCOPE_WORDS = _STRICTLY_PAST_WORDS + _INCLUDES_NOW_WORDS
"""Time ranges this system cannot answer for.

It keeps nothing across a restart -- the statistics start when the process
does. A question scoped to yesterday used to be answered with the numbers
since start-up, which is the worst shape an error can take here: every
figure is real, so nothing downstream can catch it, and the grounding
check least of all -- what is wrong is not a number but the interval it
belongs to.

"今天" is on the list even though a run started this morning would make it
nearly true. Nearly true is exactly the case worth flagging: the answer
stays the same either way, and only the caveat tells the reader which one
they got. Words that mean "since we started watching" (刚才、这一阵子、
平时、一直) are deliberately absent -- those the data really does cover."""

_MARGIN_WORDS = (
    "还差", "差多少", "还有多少", "还剩", "快超", "差几",
    "离阈值", "距阈值", "离报警", "距报警", "离上限", "离超标",
)
"""Asking how far the reading is from its limit.

A separate list rather than an intent of its own: "现在多少度，还差多少超限"
is one question with two halves, and the halves share a channel, a reading
and a lookup. Recognising the second half as a *flag on the first* is what
lets one answer serve both -- which was the point of adding the margin in
the first place.

Deliberately multi-character. 离 and 距 alone would match far too much
ordinary prose; the words here only occur when someone is asking about a
distance to a limit."""

_HELP_WORDS = ("能干什么", "会什么", "帮助", "怎么用", "help", "你能")
"""落到 HELP 这一类的词。**只用于分类，不用于判断"用户在问能力"** ——
里面多是片段，"你能"出现在"你能告诉我温度多少吗"里同样命中。"""

_ASKS_CAPABILITY = (
    "能干什么", "会干什么", "能做什么", "会做什么", "有什么功能",
    "能问什么", "可以问什么", "怎么用", "使用说明", "帮助",
    "问你什么", "问你些什么", "问些什么", "问哪些", "哪些问题",
    "能回答什么", "能回答哪些",
    "what can you", "help",
)
"""整句就是在问系统能做什么的说法。

与 :data:`_HELP_WORDS` 分开，是因为两者的判错代价完全不同：分类判宽了，
句子落到 HELP 还能由模型救回来；而这张表判宽了，系统会直接回一张清单
**并且不叫模型**，那一整类问句就永远得不到回答。

"你能"因此不在表内——它是"你能告诉我…""你能看看…"的开头，
而不是"你能干什么"的全部。2026-09-09 就是把它算在内，才让
"你能告诉我现在温度多少吗"变成了一次能力介绍。"""


_AFFIRM_WORDS = (
    "是", "对", "嗯", "好", "可以", "行", "执行", "没错", "确认", "要", "yes", "ok",
)
_DENY_WORDS = (
    "不是", "不用", "不要", "算了", "别", "取消", "不对", "先不", "no",
)
"""确认与否认，用于回答系统的"你是想……吗"。

否认词先于确认词被检查（见 :func:`is_affirmation`）——"不是"里含"是"、
"不要"里含"要"，顺序反了每一句否认都会被读成同意，而这里判错的方向
恰恰是最贵的：确认这一步存在的全部意义就是不误动执行器。

两张表都短，且只在**系统刚问过一句确认**时才被查。脱离那个上下文，
"好"与"行"出现在太多正常句子里。"""

_ELLIPSIS_TAILS = ("呢", "吗", "呀", "啊", "的", "怎么样", "咋样")
"""跟在通道词后面、不改变问法的尾巴。"""

_STATISTIC_ALL = tuple(
    word for _, words in _STATISTIC_WORDS for word in words
)

_CLAUSE_BREAK = re.compile(r"([，,。！!？?；;]+|(?<!\d)\s+(?!\d))")
"""分句的断点：中文与西文的句读，以及空格。

两处刻意不算断点。一是 ASCII 句点——"调到 26.5 度"里的小数点会把数字劈开，
而中文输入里句号本就是"。"。二是紧挨数字的空格——"通风阈值调到 28 度"
两侧的空格一旦算断点，指令就只剩"通风阈值调到"，数值读不到，指令被拒。
"、"也不在内：它连接的是并列的对象（"温度、湿度多少"），不是两句话。"""

_QUESTION_MARKERS = (
    "多少", "多大", "多高", "多低", "多热", "多冷", "多吵", "多湿", "多响",
    "几", "吗", "呢", "？", "?", "怎么样", "咋样", "如何", "是否",
    "没", "是不是", "什么", "啥", "哪",
)
"""一个分句**确实在提问**的标记，只在拆句时使用。

拆句时每一段各自过一遍规则，而规则对问句很宽容："有点热"会被读成问当前温度，
"太热了"会被读成问是否超标——整句处理时这没问题，因为它们只是一句话里的铺垫；
拆开以后却会让"太热了，把风扇打开"凭空多答一句温度。所以提问的那一段
除了被规则认出，还得带一个问句标记；不带的当作语气铺垫，不单独作答。

"么"刻意不收：它出现在"这么热""怎么这么吵"里，那是感叹不是提问。

"没"与正反问（:data:`_A_NOT_A`）是 2026-09-15 两两组合题库补的：87 句基线
两两拼接后，"超了没有""开了没""冷不冷""吵不吵"这类问法在复合句里整段被当成铺垫，
问+问只拆对 65.9%；补上后升到 93.5%。"没"单独收也不会误伤，因为这张表只查
**已经被规则认成提问、且点了通道**的分句——"没问题"落到帮助，根本到不了这一步。"""

_A_NOT_A = re.compile(r"(.)不\1")
"""正反问："冷不冷""潮不潮""开不开"。不写成词表，是因为 X 可以是任何形容词。"""


def split_clauses(text: str) -> list[str]:
    """把一句话按句读与空格切成分句，句末的问号留在所属分句上。

    问号要留着，是因为 :func:`is_question_clause` 靠它判断那一段是不是提问。
    """
    pieces = _CLAUSE_BREAK.split(text.strip())
    clauses: list[str] = []
    for index in range(0, len(pieces), 2):
        body = pieces[index].strip()
        if not body:
            continue
        tail = pieces[index + 1].strip() if index + 1 < len(pieces) else ""
        clauses.append(body + tail)
    return clauses


def is_question_clause(text: str) -> bool:
    """分句里有没有问句标记，见 :data:`_QUESTION_MARKERS` 与 :data:`_A_NOT_A`。"""
    stripped = normalise(text.strip().lower())
    return _contains(stripped, _QUESTION_MARKERS) or bool(_A_NOT_A.search(stripped))


def is_bare_channel_question(text: str) -> bool:
    """句子是不是"只点了个通道"——除通道词与语气词外几乎没别的内容。

    "噪声呢""那湿度""温度的"属于此类：它们把问法整个省了，靠上一句撑着。
    "现在噪声多少""噪声最高"不属于——它们自己说清了要问什么，
    用上一轮的问法覆盖掉它们，就成了篡改。
    """
    stripped = text.strip().lower()
    if len(stripped) > 8:
        return False
    if _contains(stripped, _STATISTIC_ALL) or _contains(stripped, _ALARM_WORDS):
        return False
    if _contains(stripped, _THRESHOLD_WORDS) or _contains(stripped, _FAN_WORDS):
        return False
    for _, words in _CHANNEL_WORDS:
        for word in words:
            if word in stripped:
                rest = stripped.replace(word, "", 1)
                for tail in _ELLIPSIS_TAILS:
                    rest = rest.replace(tail, "")
                rest = re.sub(r"[\s，。、？?！!那这个]", "", rest)
                if not rest:
                    return True
    return False


def _is_past_scoped(text: str) -> bool:
    """Whether the sentence asks about a period outside this run."""
    return _contains(text, _PAST_SCOPE_WORDS)


def _is_strictly_past(text: str) -> bool:
    """Whether the sentence names a period that has already ended.

    The test for a current-value question: "昨天温度多少" cannot be answered
    with the reading now, "今天温度多少" can."""
    return _contains(text, _STRICTLY_PAST_WORDS)


def bare_switch_direction(text: str) -> IntentKind | None:
    """一句没点名对象的话里，是要开还是要关。

    只在**话题已经定死在风扇上**时使用——要么系统刚反问过"是要开关风扇吗"，
    要么上一句就在操作风扇。脱离了这个前提，"关了吧"可能在说任何东西，
    这也正是它默认不被当成指令的原因。
    """
    stripped = normalise(text.strip().lower())
    if _contains(stripped, _BARE_OFF_WORDS) or _contains(stripped, _FAN_OFF_WORDS):
        return IntentKind.FAN_OFF
    if _contains(stripped, _BARE_ON_WORDS) or _contains(stripped, _FAN_ON_WORDS):
        return IntentKind.FAN_ON
    return None


def _wants_margin(text: str) -> bool:
    """Did the sentence ask how far the reading is from the limit?"""
    return _contains(text, _MARGIN_WORDS)


def _announce_requested(text: str) -> bool:
    """Is the user asking the system to speak on demand?

    Two ways to qualify: naming the act outright (播报/语音/喇叭...), or
    pairing a sound word with a trial word ("让它响一声试试"). The pairing
    is what separates a request from a question -- "现在响吗" asks for a
    reading and must keep reaching the noise channel.
    """
    if _contains(text, _ANNOUNCE_WORDS):
        return True
    return _contains(text, _SOUND_HINTS) and _contains(text, _TEST_HINTS)


def _delete_requested(text: str) -> bool:
    """Is the user asking for data to be destroyed?"""
    return _contains(text, _DELETE_WORDS)


def _cloud_sync_requested(text: str) -> bool:
    """Is the user asking for the archive to be sent up?"""
    return _contains(text, _CLOUD_SYNC_WORDS)


def _cloud_view_requested(text: str) -> bool:
    """Is the user asking to look at what is already uploaded?"""
    return _contains(text, _CLOUD_VIEW_WORDS)


_TYPOS: tuple[tuple[str, str], ...] = (
    ("多少读", "多少度"),
    ("几读", "几度"),
    ("阀值", "阈值"),
    ("燥音", "噪音"),
    ("躁音", "噪音"),
    ("分被", "分贝"),
)
"""Pinyin-IME misspellings, corrected before anything else runs.

Every left-hand side is a string with **no legitimate meaning in Chinese**,
which is what makes rewriting it lossless. That property is why the table
is keyed on phrases rather than characters: 读 alone had to become 度 for
"现在多少读" to work, but 读 also spells 读数 -- a word this system uses
constantly -- so a character-level rule would break "噪声读数是多少" to fix
a typo. 多少读 spells nothing at all, and "我在读书" does not contain it.

阀值 earns its place for the opposite reason: it is not a slip but a
widespread misconception (阀 is a valve; the word is 阈值), so it arrives
typed confidently and would otherwise be met with the help text.
"""


def normalise(text: str) -> str:
    """Apply :data:`_TYPOS`. Idempotent, and a no-op for well-typed input."""
    for wrong, right in _TYPOS:
        text = text.replace(wrong, right)
    return text


def asks_for_help(question: str) -> bool:
    """Whether the sentence is explicitly asking what the system can do.

    HELP is two different situations wearing one label: "你能干什么" wants
    the capability list, and everything the rules failed on merely landed
    there. Only the first should be answered with the list -- the second
    gets a placeholder while the model looks at it.
    """
    text = normalise(question.strip().lower())
    if not _contains(text, _ASKS_CAPABILITY):
        return False
    # "帮助""怎么用"这两个词自己也能出现在正经问句里（"帮助我查湿度"），
    # 所以再要求句子里没有别的实质内容——问能力的话不会同时点名通道。
    if _match_channel(text) is not None or _contains(text, _FAN_WORDS):
        return False
    return True


def channel_vocabulary() -> tuple[tuple[ChannelId, tuple[str, ...]], ...]:
    """The channel keyword table, for callers that need to recognise a bare
    channel name rather than classify a sentence. Read-only by construction
    (tuples all the way down)."""
    return _CHANNEL_WORDS


def _match_channel(text: str) -> ChannelId | None:
    for channel, words in _CHANNEL_WORDS:
        if any(word in text for word in words):
            return channel
    return None


def _contains(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def _has_number(text: str) -> bool:
    return any(ch.isdigit() for ch in text)


def _unit_hint_channel(text: str) -> ChannelId | None:
    """Channel implied by a unit alone: 度 -> 温度，% -> 湿度。"""
    if _contains(text, _DEGREE_HINTS):
        return TEMPERATURE_CHANNEL
    if _contains(text, _PERCENT_HINTS):
        return HUMIDITY_CHANNEL
    return None


def _threshold_channel(text: str) -> ChannelId | None:
    """Which channel a threshold instruction is about, unit hints included."""
    return _match_channel(text) or _unit_hint_channel(text)


def is_affirmation(text: str) -> bool:
    """一句话是不是在回答"是"。否认优先，理由见 :data:`_DENY_WORDS`。"""
    stripped = normalise(text.strip().lower())
    if not stripped or len(stripped) > 10:
        # 长句不是在答话，是新问题——"是不是该开风扇"里也有"是"。
        return False
    if _contains(stripped, _DENY_WORDS):
        return False
    return _contains(stripped, _AFFIRM_WORDS)


def is_denial(text: str) -> bool:
    """一句话是不是在回答"不是"。"""
    stripped = normalise(text.strip().lower())
    if not stripped or len(stripped) > 10:
        return False
    return _contains(stripped, _DENY_WORDS)


def _is_consultative(text: str) -> bool:
    """句子是在征询意见或作假设，而不是在下命令。"""
    return _contains(text, _CONSULTATIVE_WORDS)


def _fan_intent(text: str) -> Intent:
    """Distinguish an instruction about the fan from a question about it.

    Threshold setting is tested first because "把通风阈值调到 28 度" also
    contains 调到, and because it is the only branch that carries a value:
    reading it as a plain "turn on" would act on the wrong thing entirely.

    A sentence that names the fan but no instruction is a question --
    "风扇在转吗" -- which is the pre-existing behaviour and stays the
    default.

    State-question words are tested **before** the instruction branches,
    which is the reverse of what the narrow word lists used to need. The
    lists now match bare 开 and 关, so "风扇开着吗" would otherwise be
    obeyed as an order; the guard is what buys the width.

    征询语气（:data:`_CONSULTATIVE_WORDS`）比状态词还要靠前，因为它要拦的是
    另一类句子："风扇是不是该开了"里没有任何状态词，有的只是一个"开"。
    它答风扇状态，问到阈值时答阈值，两种情况都不动执行器。

    Note that a threshold instruction is recognised **without requiring a
    number**: "把通风温度阈值调低一点" is understood, and then refused by
    ``control`` for not saying how far. Demanding the number here instead
    would classify it as a plain fan question, and the user would get the
    fan's state as the answer to a sentence that asked to change a setting
    -- which is what the demo dry-run actually did before this was fixed.
    """
    about_threshold = _contains(text, _THRESHOLD_WORDS)
    instructed = _contains(text, _SET_WORDS)
    if _is_consultative(text):
        # 征询语气先于每一条指令分支被判定，和 ``_FAN_STATE_WORDS`` 同一个思路：
        # 词表宽到能认出各种说法之后，唯一还能把提问与命令分开的就是语气。
        # 落点选 FAN_STATE 而不是 HELP，是因为它取到的事实里本就带着通风阈值与
        # 当前读数（见 ``ThresholdRetriever._fan_facts``），正好是"要不要开"
        # 这个问题需要的两样东西；问到阈值的那半句则答阈值本身。
        if about_threshold:
            return Intent(
                kind=IntentKind.THRESHOLD_INFO,
                channel=_threshold_channel(text),
            )
        return Intent(kind=IntentKind.FAN_STATE)
    if (about_threshold and (instructed or _has_number(text))) or (
        instructed and _has_number(text)
    ):
        return Intent(
            kind=IntentKind.SET_VENT_THRESHOLD,
            channel=_threshold_channel(text),
        )
    if _contains(text, _FAN_STATE_WORDS):
        return Intent(kind=IntentKind.FAN_STATE)
    if _contains(text, _FAN_AUTO_WORDS):
        return Intent(kind=IntentKind.FAN_AUTO)
    if _contains(text, _FAN_OFF_WORDS):
        return Intent(kind=IntentKind.FAN_OFF)
    if _contains(text, _FAN_ON_WORDS):
        return Intent(kind=IntentKind.FAN_ON)
    return Intent(kind=IntentKind.FAN_STATE)


def recognise(question: str, default_channel: ChannelId | None = None) -> Intent:
    """Classify ``question``. Never raises; unrecognised input yields HELP.

    ``default_channel`` is the channel the *previous* question was about,
    supplied by :class:`~service.assistant.assistant.Assistant`. It fills
    in for a sentence that names none -- "最高呢" right after "现在噪声多少"
    -- and is deliberately consulted last, after both the channel words and
    the unit hints, so it can never override a channel the sentence states
    itself. It is also read only below the fan branch: an *instruction*
    that does not say what it acts on must stay unrecognised rather than
    inherit a topic, because acting on the wrong channel is not something
    the user can undo by rephrasing.

    The sentence is first passed through :func:`normalise`, which fixes a
    short list of pinyin-IME misspellings. It runs on every input rather
    than only on ones that fail to match, because each entry is a string
    that means nothing when spelled that way -- there is no correct
    sentence for it to damage.

    Ordering of the checks encodes precedence, and two of them are worth
    stating because they are not arbitrary:

    - **Threshold before alarm state.** "噪声阈值是多少" contains 阈值 but
      also reads like a question about limits; asking for the threshold is
      a request for a configured constant, while asking about 超标 is a
      request about the current reading. Getting this backwards would
      answer "是的，超标了" to a question about the standard.
    - **Fan before channel.** "风扇为什么在转" mentions no channel, but
      "温度高了风扇会转吗" mentions both; the user is asking about the fan.

    Instructions ("把风扇打开") are recognised inside the fan branch, by
    :func:`_fan_intent`. They are kept there rather than given a branch of
    their own so that a sentence must name the fan before any word in it
    can be read as a command -- see ``_FAN_ON_WORDS``.
    """
    text = normalise(question.strip().lower())
    if not text:
        return Intent(kind=IntentKind.HELP)
    past_scoped = _is_past_scoped(text)

    # Before both the help branch and the channel words: "你能播报一下吗"
    # contains 你能 (help), and 响/声音 are noise keywords, so either would
    # otherwise claim the sentence first and answer something else.
    if _announce_requested(text):
        return Intent(kind=IntentKind.ANNOUNCE_REQUEST)

    # Alongside the announce branch and for the same reason: "把噪声数据
    # 清一清" carries a channel word, so the channel branch would claim it
    # and answer a request to delete with a real sound level. It also
    # sits before the fan branch, because "清空" and the on-off words can
    # share a sentence ("清空历史记录，顺便把风扇关了") and destroying data
    # is the half that must not be acted on. Instructions are unaffected:
    # no entry in _DELETE_WORDS appears in a fan command.
    if _delete_requested(text):
        return Intent(kind=IntentKind.DELETE_REQUEST)

    # 在上云分支之前：查看与上传的说法有重叠（"把传上去的文件看一下"），
    # 而看比传轻——读错方向最多是少看一眼，反过来则是把一个外部动作
    # 摆到用户面前。
    if _cloud_view_requested(text):
        return Intent(kind=IntentKind.CLOUD_VIEW_HINT)

    # After the delete branch on purpose: "把云上的数据删了" names both,
    # and the half that must not be mistaken for an offer is the delete.
    # Losing an upload offer costs one more sentence; reading a deletion
    # request as an upload offer puts a button under it.
    if _cloud_sync_requested(text):
        return Intent(kind=IntentKind.CLOUD_SYNC_HINT)

    if _contains(text, _HELP_WORDS):
        return Intent(kind=IntentKind.HELP)

    if _contains(text, _FAN_WORDS):
        return _fan_intent(text)

    # 没点名对象的开关动作。放在通道匹配之前：句子里若同时有通道词，
    # 那就不是一句裸指令了，该走原来的路。
    if _match_channel(text) is None and (
        _contains(text, _BARE_ON_WORDS) or _contains(text, _BARE_OFF_WORDS)
    ):
        return Intent(kind=IntentKind.BARE_SWITCH)

    channel = _match_channel(text)
    if channel is None:
        # 没点名通道，但带了单位——"这一阵子平均多少度"里的"度"就足以定位到温度。
        # 只在问句里做这一步兜底，指令侧另有 _threshold_channel()：把"多少度"读成温度
        # 是常识，而把一条没说清对象的指令猜成某个通道是危险的。
        channel = _unit_hint_channel(text)

    # 上一轮的通道只补给**已经匹配到别的关键词**的句子——"最高呢"里有"最高"、
    # "超标了吗"里有"超标"。它不足以让一个什么都没匹配上的句子变成一次提问：
    # 第一版就是那么写的，结果"帮我订张票"被答成了当前湿度，而它本该落到帮助文案
    # 或交给模型分类。记忆的作用是补全一次追问，不是替一句话找个话题。
    followed = channel if channel is not None else default_channel

    # 余量先于阈值与报警被判定。"现在温度多少，还差多少超限"里同时有"超限"
    # （报警词）和"还差"（余量词），而问的是距离而非是否越线；答成 ALARM_STATE
    # 只会回一句"未超过"，恰好把人问的那个数丢掉。余量答案本身同时给出读数与
    # 距离，因此对这三类问法都是更完整的回答。
    if _wants_margin(text):
        return Intent(
            kind=IntentKind.CURRENT_VALUE,
            channel=followed,
            wants_margin=True,
        )

    if _contains(text, _THRESHOLD_WORDS):
        return Intent(kind=IntentKind.THRESHOLD_INFO, channel=followed)

    if _contains(text, _ALARM_WORDS):
        return Intent(kind=IntentKind.ALARM_STATE, channel=followed)

    if _contains(text, _DEVICE_WORDS):
        return Intent(kind=IntentKind.DEVICE_LIST)

    for kind, words in _STATISTIC_WORDS:
        if _contains(text, words):
            # Channel may still be None here, and that is deliberate: a
            # bare "最高呢" with nothing to inherit is a question this
            # system understands and can ask back about. Returning HELP
            # instead would throw away the one thing it did establish.
            return Intent(kind=kind, channel=followed, past_scoped=past_scoped)

    if channel is not None:
        return Intent(
            kind=IntentKind.CURRENT_VALUE,
            channel=channel,
            past_scoped=_is_strictly_past(text),
        )

    return Intent(kind=IntentKind.HELP)
