"""Remembers recent ``musicxml_to_abc`` results by opaque id, for the ABC Workbench.

The workbench shows the model's edit against the ABC the model started from. The edit arrives as
the ``abc_to_musicxml`` tool input; the original is fetched here by id (proposal 5.6), so the app
never needs a score or a path. Ids are random per call, even for identical input, are bounded in
number and expire, and are lost when the server restarts.

No MCP imports: engine-level code, testable without the MCP stack.
"""

from __future__ import annotations

import copy
import time
from typing import Callable

from sheet_music_mcp_core.errors import ProcessingError
from sheet_music_mcp_core.expiring import EntryNotFound, ExpiringTable

DEFAULT_TTL_SECONDS = 3600.0
DEFAULT_MAX_ENTRIES = 32

_HINT = (
    "Ids are kept for a limited time and are lost when the server restarts. "
    "Run musicxml_to_abc again for a new abc_id."
)


class AbcStore:
    """Ids to ``musicxml_to_abc`` results; the TTL runs from ``put`` and the oldest go first."""

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._entries: ExpiringTable[str, dict] = ExpiringTable(
            ttl_seconds=ttl_seconds, max_entries=max_entries, clock=clock
        )
        # The newest entry outlives all others, so it is live whenever any entry is.
        self._latest: str | None = None

    def put(self, result: dict) -> str:
        """Remember ``{abc, parts_included, warnings}`` and return its new id."""
        self._latest = self._entries.put(copy.deepcopy(result))
        return self._latest

    def get(self, abc_id: object | None = None) -> dict:
        """A copy of the stored result for ``abc_id``, or of the latest one when it is None."""
        return self.fetch(abc_id)[1]

    def fetch(self, abc_id: object | None = None) -> tuple[str, dict]:
        """``(abc_id, copy of the result)``; the latest entry when ``abc_id`` is None."""
        if abc_id is None:
            try:
                if self._latest is None:
                    raise EntryNotFound()
                abc_id = self._latest
                return abc_id, copy.deepcopy(self._entries.get(abc_id))
            except EntryNotFound:
                raise ProcessingError("No ABC has been exported yet", "INVALID_PARAMETER", hint=_HINT) from None
        try:
            entry = self._entries.get(abc_id)
        except EntryNotFound:
            # The id is caller-chosen text, so it is not echoed.
            raise ProcessingError("Unknown or expired abc_id", "INVALID_PARAMETER", hint=_HINT) from None
        return abc_id, copy.deepcopy(entry)
