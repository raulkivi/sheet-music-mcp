"""Remembers recent ``musicxml_to_abc`` results by opaque id, for the ABC Workbench.

The workbench shows the model's edit against the ABC the model started from. The edit arrives as
the ``abc_to_musicxml`` tool input; the original is fetched here by id (proposal 5.6), so the app
never needs a score or a path. Ids are random per call, even for identical input, are bounded in
number and expire, and are lost when the server restarts.

No MCP imports: engine-level code, testable without the MCP stack.
"""

from __future__ import annotations

import copy
import secrets
import threading
import time
from collections import OrderedDict
from typing import Callable

from sheet_music_mcp_core.errors import ProcessingError

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
        if not ttl_seconds > 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self._ttl = ttl_seconds
        self._max = max_entries
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, result: dict) -> str:
        """Remember ``{abc, parts_included, warnings}`` and return its new id."""
        abc_id = secrets.token_urlsafe(18)
        with self._lock:
            now = self._clock()
            self._purge(now)
            self._entries[abc_id] = (now, copy.deepcopy(result))
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)
        return abc_id

    def get(self, abc_id: object | None = None) -> dict:
        """A copy of the stored result for ``abc_id``, or of the latest one when it is None."""
        return self.fetch(abc_id)[1]

    def fetch(self, abc_id: object | None = None) -> tuple[str, dict]:
        """``(abc_id, copy of the result)``; the latest entry when ``abc_id`` is None."""
        with self._lock:
            self._purge(self._clock())
            if abc_id is None:
                if not self._entries:
                    raise ProcessingError("No ABC has been exported yet", "INVALID_PARAMETER", hint=_HINT)
                abc_id, entry = next(reversed(self._entries.items()))
            else:
                entry = self._entries.get(abc_id) if isinstance(abc_id, str) else None
                if entry is None:
                    # The id is caller-chosen text, so it is not echoed.
                    raise ProcessingError("Unknown or expired abc_id", "INVALID_PARAMETER", hint=_HINT)
        return abc_id, copy.deepcopy(entry[1])

    def _purge(self, now: float) -> None:
        # Insertion order is creation order, so expired entries are all at the front.
        while self._entries:
            created, _ = next(iter(self._entries.values()))
            if now - created < self._ttl:
                return
            self._entries.popitem(last=False)
