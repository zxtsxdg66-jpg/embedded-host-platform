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

from typing import Any

from gateway.channel_units import channel_unit
from service.data_models import DataPoint
from service.sensor_data_processor import ChannelStatistics, ThresholdStatus

MESSAGE_TYPE_DATA = "data"
MESSAGE_TYPE_ALARM_STATUS = "alarm_status"
MESSAGE_TYPE_STATISTICS = "statistics"
MESSAGE_TYPE_ASSISTANT = "assistant"


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
