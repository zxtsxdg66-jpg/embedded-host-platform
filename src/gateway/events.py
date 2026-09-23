"""Serialization of ApiInterface callback payloads into WebSocket messages.

Every field emitted here is taken from an existing PC-side type -- no
invented fields:

- ``data``        <- service.data_models.DataPoint
- ``alarm_status``<- service.sensor_data_processor.ThresholdStatus
- ``statistics``  <- service.sensor_data_processor.ChannelStatistics

The one field that is *not* copied from those types is ``unit``. DataPoint
has no unit (units are a presentation concern). Per
docs/10_AndroidClient/PC_Android_接口设计.md Section 3.1 the server
attaches it, so an Android client does not have to hardcode its own
mapping -- see gateway/channel_units.py for why that mapping is a
deliberate (documented) duplicate of ui/channel_display.py rather than an
import of it. ``unit`` is purely additive: no existing PC-side type gained
a field, and nothing in src/ui/, src/service/, or src/api/ changed.
"""

from __future__ import annotations

import dataclasses
from enum import Enum
from typing import Any

from application.link_monitor import LinkEvent, LinkStatistics
from gateway.channel_units import channel_unit
from service.assistant.models import Answer, Facts
from service.data_models import DataPoint
from service.sensor_data_processor import ChannelStatistics, ThresholdStatus
from service.ventilation_controller import FanDecision, VentilationSettings

MESSAGE_TYPE_DATA = "data"
MESSAGE_TYPE_ALARM_STATUS = "alarm_status"
MESSAGE_TYPE_STATISTICS = "statistics"
MESSAGE_TYPE_ASSISTANT = "assistant"
MESSAGE_TYPE_FAN_DECISION = "fan_decision"
MESSAGE_TYPE_ASSISTANT_DETAIL = "assistant_detail"
MESSAGE_TYPE_LINK_EVENT = "link_event"


def isoformat_or_none(value: Any) -> str | None:
    """Render a datetime as ISO-8601, tolerating None.

    Public rather than underscore-prefixed since 2026-09-17: the history
    endpoint in ``gateway.server`` renders timestamps the same way, and
    two presentations of the same platform must not drift in how they
    spell a moment. A private name imported from another module would say
    "do not depend on this" while being depended on.
    """
    return None if value is None else value.isoformat()


def data_point_message(point: DataPoint) -> dict[str, Any]:
    """Serialize one DataPoint into a ``type: "data"`` WebSocket message."""
    return {
        "type": MESSAGE_TYPE_DATA,
        "device_id": point.device_id,
        "channel": point.channel,
        "value": point.value,
        "unit": channel_unit(point.channel),
        "timestamp": isoformat_or_none(point.timestamp),
        "valid": point.valid,
    }


def alarm_status_message(status: ThresholdStatus) -> dict[str, Any]:
    """Serialize one ThresholdStatus into a ``type: "alarm_status"`` message."""
    return {
        "type": MESSAGE_TYPE_ALARM_STATUS,
        "device_id": status.device_id,
        "channel": status.channel,
        "value": status.value,
        "unit": channel_unit(status.channel),
        "threshold": status.threshold,
        # AlarmKind is an Enum; send its name so the client sees a stable
        # string ("ABOVE_MAX"/"BELOW_MIN") rather than a Python repr.
        "kind": status.kind.name,
        "triggered": status.triggered,
    }


def assistant_answer_message(text: str, source: str) -> dict[str, Any]:
    """Serialize a late assistant answer into a ``type: "assistant"`` message.

    Takes the two strings rather than an :class:`service.assistant.models.Answer`
    because that is what the composition root has: ``make_poll_once``'s sink
    receives ``(text, source)``, the same pair the desktop view gets. Keeping
    the signature at two strings means the launcher can feed the phone and
    the window from one callback without either presentation端 learning about
    the other's types.

    ``source`` is :class:`~service.assistant.models.AnswerSource`'s value --
    "template", "model", "model_intent" or "fallback" -- so the client can
    label how much of the answer the model contributed, exactly as the
    desktop panel does.
    """
    return {
        "type": MESSAGE_TYPE_ASSISTANT,
        "text": text,
        "source": source,
    }


def statistics_message(
    device_id: str, channel: str, statistics: ChannelStatistics
) -> dict[str, Any]:
    """Serialize one ChannelStatistics into a ``type: "statistics"`` message."""
    return {
        "type": MESSAGE_TYPE_STATISTICS,
        "device_id": device_id,
        "channel": channel,
        "unit": channel_unit(channel),
        "current": statistics.current,
        "minimum": statistics.minimum,
        "maximum": statistics.maximum,
        "average": statistics.average,
        "sample_count": statistics.sample_count,
    }


def fan_decision_message(decision: FanDecision) -> dict[str, Any]:
    """Serialize one FanDecision into a ``type: "fan_decision"`` message.

    ``reason`` is presentation text by the controller's own contract (see
    FanDecision's docstring): clients may show it but must not parse it.
    """
    return {
        "type": MESSAGE_TYPE_FAN_DECISION,
        "should_run": decision.should_run,
        "mode": decision.mode.name,
        "reason": decision.reason,
    }


def ventilation_payload(
    settings: VentilationSettings, decision: FanDecision | None
) -> dict[str, Any]:
    """Body of GET /ventilation: current settings plus the latest decision.

    ``decision`` is None until the first reading has been evaluated -- a
    freshly started server has settings but has not decided anything yet,
    and saying so is more honest than inventing an initial state.
    """
    return {
        "temperature_max": settings.temperature_max,
        "humidity_max": settings.humidity_max,
        "mode": settings.mode.name,
        "decision": None
        if decision is None
        else {
            "should_run": decision.should_run,
            "mode": decision.mode.name,
            "reason": decision.reason,
        },
    }


def _plain(value: Any) -> Any:
    """JSON-ready form of a Facts field: enums by name, tuples as lists."""
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, tuple | list):
        return [_plain(v) for v in value]
    return value


def facts_payload(facts: Facts | None) -> dict[str, Any] | None:
    """Every populated field of a Facts object, generically.

    Iterates the dataclass fields rather than naming them, so a field added
    to Facts later reaches the web console without a change here. Empty
    values (None, "") are dropped: Facts carries fields for every kind of
    question, and most are unset for any one of them.
    """
    if facts is None:
        return None
    out: dict[str, Any] = {}
    for field in dataclasses.fields(facts):
        value = getattr(facts, field.name)
        if value is None or value == "":
            continue
        out[field.name] = _plain(value)
    return out


def answer_detail(answer: Answer) -> dict[str, Any]:
    """How an answer came about: the recognised intent, the facts it was
    built from, and every model rewording with the exit checks' verdict.

    Added 2026-09-23 for the web console's trace view
    (docs/02_Architecture/Web_Console_Design.md section 6). Additive: the
    Android client reads ``text``/``source`` and ignores the rest.
    """
    intent = answer.intent
    return {
        "intent": None
        if intent is None
        else {"kind": intent.kind.name, "channel": intent.channel},
        "facts": facts_payload(answer.facts),
        "trace": [
            {
                "template": attempt.template,
                "reply": attempt.reply,
                "verdict": attempt.verdict.value,
                "retry": attempt.retry,
            }
            for attempt in answer.trace
        ],
    }


def assistant_detail_message(answer: Answer) -> dict[str, Any]:
    """A late answer with its trace, as a ``type: "assistant_detail"`` message.

    Sent alongside the plain ``assistant`` message, not instead of it: the
    phone keeps reading the message it always read.
    """
    return {
        "type": MESSAGE_TYPE_ASSISTANT_DETAIL,
        "text": answer.text,
        "source": answer.source.value,
        **answer_detail(answer),
    }


def link_event_message(event: LinkEvent) -> dict[str, Any]:
    """One frame or link anomaly as a ``type: "link_event"`` message.

    ``raw`` is sent as spaced hex ("AA 55 01 ...") because that is how a
    person reads a frame, and it is what the inspector displays; a client
    that wants bytes can split it.
    """
    return {
        "type": MESSAGE_TYPE_LINK_EVENT,
        "kind": event.kind,
        "timestamp": isoformat_or_none(event.timestamp),
        "raw": event.raw.hex(" ").upper(),
        "length": len(event.raw),
        "device_id": event.device_id,
        "command_type": event.command_type,
        "payload": event.payload,
        "detail": event.detail,
    }


def link_statistics_payload(stats: LinkStatistics) -> dict[str, Any]:
    """Body of GET /link/statistics."""
    return {
        "active": stats.active,
        "bytes_received": stats.bytes_received,
        "frames": stats.frames,
        "resyncs": stats.resyncs,
        "checksum_errors": stats.checksum_errors,
        "decode_errors": stats.decode_errors,
        "ignored": stats.ignored,
        "payload_errors": stats.payload_errors,
        "last_frame_at": isoformat_or_none(stats.last_frame_at),
    }

