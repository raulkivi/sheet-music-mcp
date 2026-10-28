"""The MusicXML each synthesized track was made from, keyed by audio id.

The Practice Player draws the score while the WAV plays and fetches it with ``get_score_xml``.
A score is only ever looked up through the artifact store, so it lives exactly as long as its
WAV: ``get`` asks the store first (same TTL, same unknown-id error), and the entries use the
store's default TTL and cap so they go when their WAV does. No MCP imports.
"""

from __future__ import annotations

import time
from typing import Callable

from sheet_music_mcp_core.artifacts import (
    DEFAULT_MAX_ENTRIES,
    DEFAULT_TTL_SECONDS,
    ArtifactError,
    ArtifactStore,
)
from sheet_music_mcp_core.expiring import EntryNotFound, ExpiringTable


class ScoreBook:
    def __init__(
        self,
        store: Callable[[], ArtifactStore],
        max_entries: int = DEFAULT_MAX_ENTRIES,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        # A getter, not a store: tests and the server may swap the store after construction.
        self._store = store
        self._scores: ExpiringTable[str, str] = ExpiringTable(
            ttl_seconds=ttl_seconds, max_entries=max_entries, clock=clock
        )

    def __len__(self) -> int:
        return len(self._scores)

    def remember(self, audio_id: str, musicxml: str) -> None:
        self._scores.set(audio_id, musicxml)

    def get(self, audio_id: object) -> str:
        """The score for ``audio_id``; raises ArtifactError (INVALID_PARAMETER) if unknown or expired."""
        self._store().info(audio_id)  # raises the store's own unknown/expired error
        try:
            return self._scores.get(audio_id)
        except EntryNotFound:
            # The WAV exists but this server never stored its score (made by another code path).
            raise ArtifactError("Unknown or expired artifact id", "INVALID_PARAMETER") from None
