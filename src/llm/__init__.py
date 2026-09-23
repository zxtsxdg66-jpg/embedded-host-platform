"""Adapters for external language-model services.

Peer to ``communication`` but a different kind of boundary: that package
speaks to *devices* and hands bytes up to ``protocol``; this one speaks to
a local model server and hands text to ``service.assistant``. See
docs/decisions/02-llm.md for why the two are
kept apart.

Depends only on the standard library. In particular it does **not**
import ``service``: the ``LlmClient`` protocol lives with its consumer
(``service.assistant.llm_port``), and the clients here satisfy it
structurally, verified by mypy where they are assembled.
"""
