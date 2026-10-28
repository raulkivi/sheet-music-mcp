"""A bounded, thread-safe map whose entries expire a fixed time after they are stored.

Artifact ids use it (``artifacts``), and so can any server state an MCP App refers to by an
opaque handle, such as an edit buffer or a session: ``put`` mints an unguessable token, ``set``
takes the caller's own key. Entries never outlive ``ttl_seconds`` from insertion (reads do not
extend it), the oldest go first past ``max_entries``, and everything is lost on restart.

No MCP imports: engines may use it.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from collections import OrderedDict
from typing import Callable, Generic, Hashable, TypeVar

__all__ = ["EntryNotFound", "ExpiringTable"]

_logger = logging.getLogger(__name__)

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")

# 24 random bytes, 32 URL-safe characters: far beyond guessing, short enough for a tool argument.
_TOKEN_BYTES = 24


class EntryNotFound(KeyError):
    """The key was never stored, has expired, was evicted or discarded.

    One exception for all four, so a caller maps it to a single error. It carries no key: keys may
    come from a client, and the caller decides what to echo.
    """

    def __init__(self) -> None:
        super().__init__("Unknown or expired key")

    def __str__(self) -> str:
        return "Unknown or expired key"


class ExpiringTable(Generic[K, V]):
    """Keys to values with a TTL fixed at insert and a size cap; oldest go first.

    ``on_evict(key, value)`` is called for each entry the table drops on its own (expired or over
    ``max_entries``), so a server can keep a side table in step. It is not called for ``discard``
    or for a ``set`` that replaces a value: the caller made those changes. It runs after the lock is
    released, so it may use the table; its exceptions are logged, not raised, since the table has
    already changed by then.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float,
        max_entries: int,
        clock: Callable[[], float] = time.monotonic,
        on_evict: Callable[[K, V], None] | None = None,
    ):
        if not ttl_seconds > 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self._ttl = ttl_seconds
        self._max = max_entries
        self._clock = clock
        self._on_evict = on_evict
        # Insertion order is creation order (a replaced key moves to the end), so the oldest and
        # all expired entries are at the front.
        self._entries: OrderedDict[K, tuple[float, V]] = OrderedDict()
        # Thread-safe because servers produce entries from worker threads.
        self._lock = threading.Lock()

    def put(self, value: V) -> str:
        """Store ``value`` under a new random token (``secrets.token_urlsafe``) and return it."""
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        self.set(token, value)  # type: ignore[arg-type]
        return token

    def set(self, key: K, value: V) -> None:
        """Store ``value`` under ``key``; an existing entry is replaced and its TTL restarts."""
        with self._lock:
            now = self._clock()
            evicted = self._purge(now)
            self._entries.pop(key, None)
            self._entries[key] = (now, value)
            while len(self._entries) > self._max:
                old_key, (_, old_value) = self._entries.popitem(last=False)
                evicted.append((old_key, old_value))
        self._notify(evicted)

    def get(self, key: object) -> V:
        """The value stored under ``key``; raises ``EntryNotFound`` if there is none."""
        with self._lock:
            evicted = self._purge(self._clock())
            try:
                entry = self._entries.get(key)  # type: ignore[call-overload]
            except TypeError:  # an unhashable key, e.g. a list from JSON arguments
                entry = None
        self._notify(evicted)
        if entry is None:
            raise EntryNotFound()
        return entry[1]

    def discard(self, key: object) -> None:
        """Remove ``key`` if present; never raises and never calls ``on_evict``."""
        with self._lock:
            try:
                self._entries.pop(key, None)  # type: ignore[call-overload]
            except TypeError:
                pass

    def __len__(self) -> int:
        """The number of live (unexpired) entries."""
        with self._lock:
            evicted = self._purge(self._clock())
            size = len(self._entries)
        self._notify(evicted)
        return size

    def _purge(self, now: float) -> list[tuple[K, V]]:
        evicted: list[tuple[K, V]] = []
        while self._entries:
            key, (created, value) = next(iter(self._entries.items()))
            if now - created < self._ttl:
                break
            self._entries.popitem(last=False)
            evicted.append((key, value))
        return evicted

    def _notify(self, evicted: list[tuple[K, V]]) -> None:
        if self._on_evict is None:
            return
        for key, value in evicted:
            try:
                self._on_evict(key, value)
            except Exception:
                _logger.exception("ExpiringTable on_evict hook failed")
