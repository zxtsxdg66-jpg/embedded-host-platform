"""Where experiment recordings live.

One constant, in its own module, because it is the one path that differs
between deployments of this code: the data-collection tools write here
(``collect_experiment_data.py``, ``collect_data_launcher.py``) and the web
console's replay builder reads from here (``build_web_replay.py``). Keeping it
in a single place means moving the recordings is a one-line change.
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = _ROOT / "experiment-data"
"""Raw CSV recordings and their Markdown summaries."""
