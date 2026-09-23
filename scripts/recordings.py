"""Where experiment recordings live.

In their own module because these are the paths that differ between
deployments of this code: the data-collection tools write sensor recordings
here (``collect_experiment_data.py``, ``collect_data_launcher.py``) and the web
console's replay builder reads both kinds from here (``build_web_replay.py``).
Keeping them in a single place means moving the recordings is a one-line change.
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = _ROOT / "experiment-data"
"""Raw CSV recordings and their Markdown summaries."""

ASSISTANT_RECORDINGS_DIR = _ROOT / "experiment-data" / "assistant"
"""Assistant evaluation baselines and recorded model Q&A sessions."""
