"""Opaque handles to output files, read back in bounded chunks by MCP Apps.

An app iframe cannot open ``audio_path``, and a whole WAV is too large for one tool result
(mcp-apps-ux-proposal.md §5.2). So the producing tool calls ``put`` and returns the id; an app-only
tool returns ``chunk_payload(...)``. App-only tools never take paths (proposal §7): an id is a random
token looked up in a per-process table, so a traversal-looking id is just an unknown id.

No MCP imports: engines may use it.
"""

from __future__ import annotations

import base64
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from . import paths
from .errors import ProcessingError
from .expiring import EntryNotFound, ExpiringTable

__all__ = [
    "MAX_CHUNK_BYTES",
    "DEFAULT_TTL_SECONDS",
    "DEFAULT_MAX_ENTRIES",
    "ArtifactError",
    "ArtifactInfo",
    "ArtifactStore",
    "FileArtifactStore",
    "InMemoryArtifactStore",
    "chunk_payload",
]

MAX_CHUNK_BYTES = 1_048_576
DEFAULT_TTL_SECONDS = 3600.0
DEFAULT_MAX_ENTRIES = 64

_EXPIRED_HINT = (
    "Ids are kept for a limited time and are lost when the server restarts. "
    "Run the tool that produced it again for a new id."
)


class ArtifactError(ProcessingError):
    """An unknown, expired or vanished id, a bad chunk range, or a file ``put`` refuses."""


@dataclass(frozen=True)
class ArtifactInfo:
    """What an app may learn about an artifact; deliberately no path."""

    artifact_id: str
    kind: str
    byte_length: int


@runtime_checkable
class ArtifactStore(Protocol):
    """What tools depend on, so tests can inject ``InMemoryArtifactStore`` (proposal §6.4)."""

    def put(self, path: Path, kind: str) -> str: ...

    def info(self, artifact_id: str) -> ArtifactInfo: ...

    def read_chunk(self, artifact_id: str, offset: int, length: int) -> bytes: ...


def chunk_payload(store: ArtifactStore, artifact_id: str, offset: int, length: int) -> dict:
    """The result of every app-only chunk tool, so all servers return the same shape.

    ``length`` is the number of bytes actually returned (short at the end, 0 past it); ``eof`` is
    true once ``offset + length`` reaches ``byte_length``.
    """
    byte_length = store.info(artifact_id).byte_length
    data = store.read_chunk(artifact_id, offset, length)
    return {
        "artifact_id": artifact_id,
        "offset": offset,
        "length": len(data),
        "byte_length": byte_length,
        "eof": offset + len(data) >= byte_length,
        "data_b64": base64.b64encode(data).decode("ascii"),
    }


def _unknown() -> ArtifactError:
    # The id is not echoed: it is caller-chosen text and may be crafted to look like a path.
    return ArtifactError("Unknown or expired artifact id", "INVALID_PARAMETER", hint=_EXPIRED_HINT)


def _gone() -> ArtifactError:
    return ArtifactError("The artifact is no longer available", "INVALID_PARAMETER", hint=_EXPIRED_HINT)


def _check_range(offset: object, length: object) -> tuple[int, int]:
    for name, value in (("offset", offset), ("length", length)):
        # bool is an int subclass; True as an offset is a caller bug, not 1.
        if not isinstance(value, int) or isinstance(value, bool):
            raise ArtifactError(f"{name} must be an integer", "INVALID_PARAMETER")
        if value < 0:
            raise ArtifactError(f"{name} must not be negative", "INVALID_PARAMETER")
    if length > MAX_CHUNK_BYTES:
        raise ArtifactError(
            f"length {length} is larger than the chunk limit",
            "INVALID_PARAMETER",
            hint=f"Request at most {MAX_CHUNK_BYTES} bytes per call and continue from offset + length.",
        )
    return offset, length


class _BaseStore:
    """Shared lookup and range checks; subclasses decide how bytes are kept and read.

    Ids live in an ``ExpiringTable``: a fixed TTL from ``put`` (reads do not extend it, so an id's
    lifetime is predictable) and a size cap, oldest first.
    """

    def __init__(self, ttl_seconds: float, max_entries: int, clock: Callable[[], float]):
        self._records: ExpiringTable[str, Any] = ExpiringTable(
            ttl_seconds=ttl_seconds, max_entries=max_entries, clock=clock
        )

    def info(self, artifact_id: str) -> ArtifactInfo:
        record = self._record(artifact_id)
        return ArtifactInfo(artifact_id, record.kind, record.byte_length)

    def read_chunk(self, artifact_id: str, offset: int, length: int) -> bytes:
        record = self._record(artifact_id)
        offset, length = _check_range(offset, length)
        length = min(length, max(record.byte_length - offset, 0))
        try:
            return self._read(record, offset, length)
        except _Vanished:
            self._records.discard(artifact_id)
            raise _gone() from None

    def _record(self, artifact_id: object):
        # Ids are always tokens; anything else (a number, a list) is just an unknown id.
        if not isinstance(artifact_id, str):
            raise _unknown()
        try:
            return self._records.get(artifact_id)
        except EntryNotFound:
            raise _unknown() from None

    def _add(self, record) -> str:
        return self._records.put(record)

    def _read(self, record, offset: int, length: int) -> bytes:
        raise NotImplementedError


def _check_kind(kind: object) -> str:
    if not isinstance(kind, str) or not kind:
        raise ValueError("kind must be a non-empty string, for example 'audio/wav'")
    return kind


class _Vanished(Exception):
    """The stored file was deleted, swapped or changed since ``put``."""


@dataclass(frozen=True)
class _FileRecord:
    kind: str
    byte_length: int
    path: Path
    root: Path
    device: int
    inode: int


_OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)


class FileArtifactStore(_BaseStore):
    """Artifacts are files inside the output root, re-checked on every read.

    ``put`` refuses symlinks anywhere in the path (not just escaping ones): the stored path must be
    the file's real path, so a later swap of any component is detectable. Each read reopens the file
    with ``O_NOFOLLOW`` and compares device, inode and size with what ``put`` saw, so a replaced,
    grown or symlinked file reads as "no longer available" rather than as someone else's bytes.
    """

    def __init__(
        self,
        output_root: str | os.PathLike | None = None,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ):
        super().__init__(ttl_seconds, max_entries, clock)
        # None follows SHEET_MUSIC_OUTPUT_ROOT at each put, like paths.new_output_path does.
        self._root = None if output_root is None else Path(output_root).expanduser().resolve()

    def put(self, path: Path, kind: str) -> str:
        kind = _check_kind(kind)
        root = self._root or paths.output_root()
        candidate = Path(path).expanduser()
        absolute = Path(os.path.abspath(candidate if candidate.is_absolute() else root / candidate))
        try:
            resolved = absolute.resolve()
        except (OSError, RuntimeError):
            raise ArtifactError("Artifact path is not usable", "INVALID_PARAMETER") from None
        if not resolved.is_relative_to(root):
            raise ArtifactError(
                f"Artifact files must be inside the output root {root}",
                "INVALID_PARAMETER",
                hint="Write the file with paths.new_output_path() before storing it.",
            )
        if resolved != absolute:
            raise ArtifactError(f"Artifact path must not contain symlinks: {absolute}", "INVALID_PARAMETER")
        try:
            fd = os.open(resolved, _OPEN_FLAGS)
        except OSError:
            raise ArtifactError(f"Artifact file does not exist: {resolved}", "FILE_NOT_FOUND") from None
        try:
            status = os.fstat(fd)
        finally:
            os.close(fd)
        if not stat.S_ISREG(status.st_mode):
            raise ArtifactError(f"Artifact path is not a regular file: {resolved}", "FILE_NOT_FOUND")
        return self._add(_FileRecord(kind, status.st_size, resolved, root, status.st_dev, status.st_ino))

    def _read(self, record: _FileRecord, offset: int, length: int) -> bytes:
        # A folder swapped for a symlink changes the resolved path; O_NOFOLLOW covers the file name.
        try:
            if record.path.resolve() != record.path or not record.path.is_relative_to(record.root):
                raise _Vanished
            fd = os.open(record.path, _OPEN_FLAGS)
        except (OSError, RuntimeError):
            raise _Vanished from None
        try:
            status = os.fstat(fd)
            if (
                not stat.S_ISREG(status.st_mode)
                or (status.st_dev, status.st_ino) != (record.device, record.inode)
                or status.st_size != record.byte_length
            ):
                raise _Vanished
            return _read_at(fd, offset, length)
        finally:
            os.close(fd)


def _read_at(fd: int, offset: int, length: int) -> bytes:
    """Read ``length`` bytes at ``offset`` without relying on one call returning them all."""
    parts: list[bytes] = []
    while length > 0:
        if hasattr(os, "pread"):
            block = os.pread(fd, length, offset)
        else:  # Windows
            os.lseek(fd, offset, os.SEEK_SET)
            block = os.read(fd, length)
        if not block:
            break
        parts.append(block)
        offset += len(block)
        length -= len(block)
    return b"".join(parts)


@dataclass(frozen=True)
class _BytesRecord:
    kind: str
    data: bytes

    @property
    def byte_length(self) -> int:
        return len(self.data)


class InMemoryArtifactStore(_BaseStore):
    """Test double: keeps bytes in memory, with the same ids, expiry and errors as the file store.

    ``put`` copies the file without confinement checks; ``put_bytes`` needs no file at all.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ):
        super().__init__(ttl_seconds, max_entries, clock)

    def put(self, path: Path, kind: str) -> str:
        return self.put_bytes(Path(path).read_bytes(), kind)

    def put_bytes(self, data: bytes, kind: str) -> str:
        return self._add(_BytesRecord(_check_kind(kind), bytes(data)))

    def _read(self, record: _BytesRecord, offset: int, length: int) -> bytes:
        return record.data[offset : offset + length]
