"""Channel -> display unit mapping for network clients.

**2026-09-18: no longer a copy.** This module now re-exports from
``core.channel_display``, which holds the one definition; the public
names here are unchanged, so every existing import keeps working.

Why it used to be a copy, and why that ended
--------------------------------------------
The original reason for duplicating was sound and still is: importing
``ui.channel_display`` executes ``ui/__init__.py``, which imports
MainWindow/widgets and therefore **PyQt6** (verified empirically on
2026-08-14: 5 PyQt6 modules pulled in). The gateway is a headless
HTTP/WebSocket server that must run without a GUI toolkit -- and
``gateway`` and ``ui`` are architectural *peers*, both consuming
``api.ApiInterface``, so one importing the other would be a sideways
dependency between presentation layers.

Both of those objections are about importing **ui**, not about sharing
the definition. What was missing was a home neither peer owns. When the
archive export (``scripts/cloud_sync.py``) became the third consumer on
2026-09-18, the mapping moved to ``core.channel_display`` -- reachable
from every presentation end, dependency-free, and importing it is a
downward dependency rather than a sideways one.

The comment this file used to carry ("must stay identical to
ui/channel_display.py") is exactly the kind of instruction that fails
quietly: the same day, the phone's ``ChannelFormat`` and the desktop had
drifted apart on decimal places, and one reading showed as 25.0 on one
end and 25.03 on the other.
"""

from __future__ import annotations

from core.channel_display import CHANNEL_UNITS, channel_unit

__all__ = ["CHANNEL_UNITS", "channel_unit"]
