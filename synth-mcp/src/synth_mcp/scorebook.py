"""The MusicXML each synthesized track was made from, keyed by audio id.

The Practice Player draws the score while the WAV plays and fetches it with ``get_score_xml``.
A score is only ever looked up through the artifact store, so it lives exactly as long as its
WAV: ``get`` asks the store first (same TTL, same unknown-id error), and ``remember`` forgets
entries the store has dropped and keeps no more than the store's own cap. No MCP imports.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Callable

from sheet_music_mcp_core.artifacts import DEFAULT_MAX_ENTRIES, ArtifactError, ArtifactStore


class ScoreBook:
    def __init__(self, store: Callable[[], ArtifactStore], max_entries: int = DEFAULT_MAX_ENTRIES):
        # A getter, not a store: tests and the server may swap the store after construction.
        self._store = store
        self._max = max_entries
        self._scores: OrderedDict[str, str] = OrderedDict()

    def __len__(self) -> int:
        return len(self._scores)

    def remember(self, audio_id: str, musicxml: str) -> None:
        self._forget_dropped()
        self._scores[audio_id] = musicxml
        while len(self._scores) > self._max:
            self._scores.popitem(last=False)

    def get(self, audio_id: object) -> str:
        """The score for ``audio_id``; raises ArtifactError (INVALID_PARAMETER) if unknown or expired."""
        self._store().info(audio_id)  # raises the store's own unknown/expired error
        score = self._scores.get(audio_id) if isinstance(audio_id, str) else None
        if score is None:
            # The WAV exists but this server never stored its score (made by another code path).
            raise ArtifactError("Unknown or expired artifact id", "INVALID_PARAMETER")
        return score

    def _forget_dropped(self) -> None:
        store = self._store()
        for audio_id in list(self._scores):
            try:
                store.info(audio_id)
            except ArtifactError:
                del self._scores[audio_id]
