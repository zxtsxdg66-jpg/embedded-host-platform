"""Adapters for local persistent storage.

Peer to ``communication`` and ``llm``, and kept apart from both for the
same reason they are kept apart from each other: each speaks to a
different kind of external resource. ``communication`` speaks to devices
and hands bytes up to ``protocol``; ``llm`` speaks to a local model server
and hands text to ``service.assistant``; this package speaks to the disk
and hands readings back to ``service``.

Depends only on the standard library (``sqlite3``). In particular it does
**not** import ``service``: the ``HistoryStore`` protocol lives with its
consumer (``service.history``), and the stores here satisfy it
structurally, verified by mypy where they are assembled.

Instances may only be created in ``application/`` or ``scripts/`` -- the
same rule that governs ``SerialChannel`` and ``OllamaClient``. See
docs/02_Architecture/History_And_Cloud_Design.md section 3.2 for why this
is a new top-level package rather than a module inside ``application`` or
``service``.
"""
