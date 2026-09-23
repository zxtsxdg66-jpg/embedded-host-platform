"""Adapter: the export ledger, seen through the assistant's port.

Lives in ``application`` rather than in ``storage`` or ``service`` because
it is the only place allowed to touch both sides -- ``service`` may not
import ``storage`` (see ``CONTRIBUTING.md`` and
docs/decisions/06-history.md), and
``storage`` should not know what a conversational assistant is.

Same shape as :class:`application.history_recorder.HistoryRecorder`: a
thin object that turns a storage capability into the narrow thing a
service-layer port asks for. Here that is one integer.

Design: docs/decisions/06-history.md.
"""

from __future__ import annotations

from storage.export_ledger import SqliteExportLedger


class LedgerExportStatus:
    """Counts the exported hours that have not been uploaded yet.

    Implements ``service.assistant.export_status_port.ExportStatus``
    structurally; it deliberately does not inherit from the Protocol, so
    the dependency runs one way only -- ``service`` never learns this
    class exists.
    """

    def __init__(self, ledger: SqliteExportLedger) -> None:
        self._ledger = ledger

    def pending_upload_count(self) -> int:
        """How many finished hours are waiting to go up.

        **Never raises**, which is the port's contract. The ledger reports
        a failed open through its own counters rather than by throwing,
        but the guard is kept anyway: this is called while composing an
        answer to a question, and a chat panel that raises because a file
        is missing is worse than one that says it cannot tell.

        Returns 0 on failure, which the caller reads as "nothing to
        offer". That conflates "all uploaded" with "could not read", and
        that conflation is deliberate: both mean there is no button worth
        showing, and inventing a number for the other case is exactly what
        this system does not do.
        """
        try:
            return len(self._ledger.pending_uploads())
        except Exception:  # noqa: BLE001 -- the port forbids raising
            return 0
