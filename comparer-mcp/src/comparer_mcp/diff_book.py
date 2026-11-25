"""The scores of each comparison, kept under an opaque id for the Diff Viewer.

The viewer draws both scores, but ``compare_scores`` returns only the differences. The tool stores
the pair here and returns the id; app-only tools take the id, never a path (proposal §7), and
ids are looked up in a per-process table that expires. No MCP imports.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from sheet_music_mcp_core.errors import ProcessingError
from sheet_music_mcp_core.expiring import EntryNotFound, ExpiringTable

DEFAULT_TTL_SECONDS = 3600.0
DEFAULT_MAX_ENTRIES = 16

_EXPIRED_HINT = "Ids are kept for a limited time and are lost when the server restarts. Run compare_scores again."


@dataclass(frozen=True)
class DiffRecord:
    reference_xml: str
    target_xml: str
    options: dict | None


class DiffBook:
    def __init__(
        self,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._records: ExpiringTable[str, DiffRecord] = ExpiringTable(
            ttl_seconds=ttl_seconds, max_entries=max_entries, clock=clock
        )

    def remember(self, reference_xml: str, target_xml: str, options: dict | None) -> str:
        return self._records.put(DiffRecord(reference_xml, target_xml, options))

    def get(self, diff_id: object) -> DiffRecord:
        """The record for ``diff_id``; raises ProcessingError (INVALID_PARAMETER) if unknown or expired."""
        try:
            return self._records.get(diff_id)
        except EntryNotFound:
            # The id is not echoed: it is caller-chosen text and may be crafted to look like a path.
            raise ProcessingError("Unknown or expired diff_id", "INVALID_PARAMETER", hint=_EXPIRED_HINT) from None
