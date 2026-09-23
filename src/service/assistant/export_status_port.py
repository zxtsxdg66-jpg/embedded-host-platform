"""The port through which the assistant learns what is waiting to be uploaded.

Defined here -- in the consumer -- rather than beside the SQLite ledger,
following the same convention as ``service.assistant.llm_port.LlmClient``
and ``service.history.HistoryStore``: the layer that needs a capability
declares its shape, and whoever composes the application injects
something that fits. The concrete ledger therefore lives outside
``service/`` (in the ``storage`` package) and is never imported by it.

Why it returns a plain ``int`` rather than the ledger's own records:
``storage.export_ledger.ExportRecord`` is a storage type, and taking it
here would drag the storage package into ``service/`` through the type
annotation alone. The assistant needs one number -- how many finished
hours have not been uploaded -- and asking for exactly that keeps the
dependency direction intact.

Design: docs/decisions/06-history.md.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ExportStatus(Protocol):
    """How many exported time slots are still waiting to go up."""

    def pending_upload_count(self) -> int:
        """Finished hours that have been exported but not yet uploaded.

        Must never raise: the assistant asks this while composing an
        answer, and a ledger that cannot be opened is a reason to say
        "I don't know how many", not a reason for the question to fail.
        Implementations return 0 when they cannot tell -- the caller
        cannot distinguish "nothing pending" from "could not read", and
        deliberately does not try: both mean there is nothing to offer.
        """
        ...
