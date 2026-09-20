"""Presentation-only channel display constants, shared across ui/widgets/*.

**2026-09-18: the definitions moved to ``core.channel_display``.** This
module is now a re-export, kept so every existing ``from
ui.channel_display import ...`` keeps working untouched.

Why they moved: the same convention had spread to three consumers --
this module, ``gateway/channel_units.py`` (units only, with a comment
telling a human to keep it in sync by hand), and the archive export in
``scripts/cloud_sync.py``. Hand-synced copies had already failed once
that same day: the phone's ``ChannelFormat`` and the desktop disagreed on
decimals, so one reading rendered as 25.0 on one end and 25.03 on the
other, and the APK had to be rebuilt. The gateway could not simply import
*this* module because ``import ui.channel_display`` executes
``ui/__init__.py``, which imports ``MainController`` and pulls in all of
PyQt6 -- a headless service must not depend on a GUI framework.

The original boundary is unchanged and still holds: these strings are a
**display convenience**, never part of the wire protocol.
``protocol``/``communication`` must not consult them; what travels on the
wire is the channel id. Living in ``core`` makes the one definition
reachable from all three presentation ends -- it does not demote the
convention into the transport layer. See ``core/channel_display.py``.
"""

from __future__ import annotations

from core.channel_display import (
    CHANNEL_DECIMALS,
    CHANNEL_LABELS,
    CHANNEL_UNITS,
    DEFAULT_DECIMALS,
    channel_decimals,
    channel_label,
    channel_unit,
    format_value,
)

__all__ = [
    "CHANNEL_DECIMALS",
    "CHANNEL_LABELS",
    "CHANNEL_UNITS",
    "DEFAULT_DECIMALS",
    "channel_decimals",
    "channel_label",
    "channel_unit",
    "format_value",
]
