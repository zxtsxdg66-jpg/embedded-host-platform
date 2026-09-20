"""Stage 1b: let a language model classify what the rules could not.

The rules in :mod:`service.assistant.intent` cover the phrasings this
system was designed around, and they answer instantly. What they cannot do
is absorb the ways a person actually asks -- "这半天里最闹腾的时候到底是
多少" names neither a channel nor a statistic in any word the rules know,
so it falls through to HELP and the user is told what they *could* have
asked instead.

This module is what that case escalates to. The model is asked for one
thing only: **a label**. It never sees a reading, never produces a number,
and never writes a sentence a user reads -- once a label comes back, the
existing retrieval and template stages run exactly as they do for a rule
match. The model widens what can be understood; it does not touch what is
answered. See docs/02_Architecture/Assistant_Design.md section 12.

Why a bare label rather than JSON
---------------------------------
A 4B model asked for JSON produces JSON most of the time, and markdown
fences, apologies or a trailing comma the rest of the time -- each of
which is a parse failure for a task that has at most eleven possible
answers. So the reply is scanned for known tokens instead of parsed. Any
formatting the model wraps them in is irrelevant, which removes the entire
class of failure rather than handling its instances.

The one thing that scanning cannot survive is a reply that *echoes the
menu* ("可以是 current_value、maximum 或 average"), which would otherwise
be read as whichever label came first. That is why
:func:`parse_reply` rejects a reply mentioning several labels rather than
picking one: an ambiguous answer is worth less than no answer, because no
answer costs nothing -- the help text has already been shown.
"""

from __future__ import annotations

from core.models import ChannelId
from device.sensors.channels import (
    HUMIDITY_CHANNEL,
    NOISE_CHANNEL,
    TEMPERATURE_CHANNEL,
)
from service.assistant.models import Intent, IntentKind

PARSE_SYSTEM_PROMPT = (
    "你是地铁站环境监测系统的语句分类器。只输出一行：一个标签；"
    "若涉及某个测量通道，再加一个空格和通道名。不要解释。\n"
    "提问类：current_value 当前读数 / maximum 最高 / minimum 最低 / "
    "average 平均 / alarm_state 是否超标 / threshold_info 报警阈值 / "
    "fan_state 风扇状态 / device_list 在线设备\n"
    "指令类：fan_on 开风扇 / fan_off 关风扇 / fan_auto 风扇转自动 / "
    "set_vent_threshold 修改通风阈值\n"
    "无法归类：unknown\n"
    "通道：temperature 冷热气温 / humidity 干湿潮气 / noise 吵闹分贝声音\n"
    "必须以标签开头，只给通道名是错的。不要输出句子里的数字。\n"
    "例：现在多热 -> current_value temperature\n"
    "例：最吵的时候有多少 -> maximum noise\n"
    "例：风扇转着吗 -> fan_state\n"
    "例：太闷了让风扇转起来 -> fan_on\n"
    "例：通风阈值调到 28 度 -> set_vent_threshold temperature\n"
    "例：明天下雨吗 -> unknown"
)
"""Fixed, for the same reason :data:`assistant.REPHRASE_SYSTEM_PROMPT` is:
an unchanging prefix is what lets Ollama reuse its KV cache between
requests. Note the two prompts alternate, so a run that mixes parsing and
rephrasing loses some of that benefit -- acceptable, because parsing only
happens for questions the rules already failed, which are the minority."""

MODEL_INTENT_CONFIDENCE = 0.6
"""What a model-derived intent scores, against 1.0 for a rule match.

The field exists on :class:`Intent` for exactly this; nothing branches on
it today, but it is what a future "did you mean ...?" confirmation would
read, and recording provenance costs nothing now and cannot be
reconstructed later.
"""

_LABELS: dict[str, IntentKind] = {
    "current_value": IntentKind.CURRENT_VALUE,
    "maximum": IntentKind.MAXIMUM,
    "minimum": IntentKind.MINIMUM,
    "average": IntentKind.AVERAGE,
    "alarm_state": IntentKind.ALARM_STATE,
    "threshold_info": IntentKind.THRESHOLD_INFO,
    "fan_state": IntentKind.FAN_STATE,
    "device_list": IntentKind.DEVICE_LIST,
    "fan_on": IntentKind.FAN_ON,
    "fan_off": IntentKind.FAN_OFF,
    "fan_auto": IntentKind.FAN_AUTO,
    "set_vent_threshold": IntentKind.SET_VENT_THRESHOLD,
}
"""Questions and instructions share one label set because they share one
model call: the user types both into the same box, and asking twice would
double the wait for nothing. What differs is downstream --
:mod:`service.assistant.assistant` routes an instruction to
``control.ControlExecutor``, which owns the whitelist and the range
checks."""

_UNKNOWN_LABEL = "unknown"
"""An explicit way for the model to decline, which it needs: without one,
a question genuinely outside the system's scope gets forced into whichever
label looks closest."""

_CHANNELS: dict[str, ChannelId] = {
    "temperature": TEMPERATURE_CHANNEL,
    "humidity": HUMIDITY_CHANNEL,
    "noise": NOISE_CHANNEL,
}

_CHANNEL_REQUIRED = frozenset(
    {
        IntentKind.SET_VENT_THRESHOLD,
        IntentKind.CURRENT_VALUE,
        IntentKind.MAXIMUM,
        IntentKind.MINIMUM,
        IntentKind.AVERAGE,
        IntentKind.ALARM_STATE,
        IntentKind.THRESHOLD_INFO,
    }
)
"""Kinds that mean nothing without a channel.

Retrieval already refuses to guess one (it returns ``available=False``),
so accepting a channel-less label here would replace the help text with a
worse message -- "没有可用的数据" for a question the system simply did not
understand. Rejecting keeps the help text, which at least tells the user
what to ask.
"""

_MAX_DISTINCT_LABELS = 1
"""How many different labels a reply may mention. See the module docstring:
more than one means the model listed options instead of choosing."""


def build_prompt(question: str) -> str:
    """The user half of the request. Kept trivial so the prefix stays fixed."""
    return question.strip()


def parse_reply(reply: str) -> Intent | None:
    """Turn a model reply into an :class:`Intent`, or None if unusable.

    None is returned -- rather than a HELP intent -- whenever the reply is
    empty, declines, names several labels, or names a kind that needs a
    channel without giving one. The caller has already shown the help text,
    so None means "leave it as it was", and no second answer appears.
    """
    text = reply.strip().lower()
    if not text:
        return None

    matched = {label for label in _LABELS if label in text}
    if not matched or len(matched) > _MAX_DISTINCT_LABELS:
        return None
    if _UNKNOWN_LABEL in text:
        # Present alongside a real label only if the model hedged; either
        # way it declined, and a hedged classification is not one.
        return None

    kind = _LABELS[next(iter(matched))]
    channel = _match_channel(text)
    if kind in _CHANNEL_REQUIRED and channel is None:
        return None

    return Intent(kind=kind, channel=channel, confidence=MODEL_INTENT_CONFIDENCE)


def _match_channel(text: str) -> ChannelId | None:
    found = {name for name in _CHANNELS if name in text}
    if len(found) != 1:
        # Zero is normal (whole-system questions); more than one is the
        # menu-echo case again, and picking either would be a coin toss.
        return None
    return _CHANNELS[next(iter(found))]


__all__ = [
    "MODEL_INTENT_CONFIDENCE",
    "PARSE_SYSTEM_PROMPT",
    "build_prompt",
    "parse_reply",
]
