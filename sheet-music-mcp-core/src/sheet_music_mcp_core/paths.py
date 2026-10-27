"""Read and write confinement for paths the model chooses (docs/conventions.md, Score References).

No MCP imports: engines may use it. Other input kinds (images, audio) reuse ``confine_read_path``
with their own suffix list.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from .errors import ProcessingError

__all__ = [
    "SCORE_SUFFIXES",
    "PathPolicyError",
    "max_score_bytes",
    "output_root",
    "input_roots",
    "read_roots",
    "confine_read_path",
    "confine_output_path",
    "new_output_path",
]

SCORE_SUFFIXES = (".musicxml", ".xml", ".mxl")
DEFAULT_MAX_SCORE_BYTES = 16 * 1024 * 1024


class PathPolicyError(ProcessingError, ValueError):
    """A path outside the allowed folders, of the wrong type, missing or too large.

    Also a ValueError, so ``except ValueError`` handlers written for the old server copies keep
    working.
    """


def max_score_bytes() -> int:
    """``SHEET_MUSIC_MAX_SCORE_BYTES``; 16 MiB when unset, not a number or not positive."""
    try:
        value = int(os.environ.get("SHEET_MUSIC_MAX_SCORE_BYTES", ""))
    except ValueError:
        return DEFAULT_MAX_SCORE_BYTES
    return value if value > 0 else DEFAULT_MAX_SCORE_BYTES


def output_root() -> Path:
    """``SHEET_MUSIC_OUTPUT_ROOT``, default the working directory, resolved."""
    return Path(os.environ.get("SHEET_MUSIC_OUTPUT_ROOT") or Path.cwd()).resolve()


def input_roots() -> list[Path]:
    """The folders in ``SHEET_MUSIC_INPUT_ROOTS`` (split on ``os.pathsep``), resolved."""
    entries = os.environ.get("SHEET_MUSIC_INPUT_ROOTS", "").split(os.pathsep)
    return [Path(entry.strip()).expanduser().resolve() for entry in entries if entry.strip()]


def read_roots(client_roots: Iterable[str | os.PathLike] = ()) -> list[Path]:
    """Output root, then client roots, then input roots: resolved, without duplicates."""
    roots: list[Path] = []
    for root in [output_root(), *client_roots, *input_roots()]:
        resolved = Path(root).expanduser().resolve()
        if resolved not in roots:
            roots.append(resolved)
    return roots


def confine_read_path(
    path: str | os.PathLike,
    *,
    roots: Sequence[str | os.PathLike],
    suffixes: Sequence[str],
    max_bytes: int,
    param: str,
) -> Path:
    """Return ``path`` resolved, if it is a readable file inside one of ``roots``.

    ``~``, relative paths (against the output root) and symlinks are resolved first. Then, in this
    order: outside every root, or a wrong suffix, is INVALID_PARAMETER; missing or not a file is
    FILE_NOT_FOUND; larger than ``max_bytes`` is FILE_TOO_LARGE. The root check comes first, so a
    path outside the roots never reveals whether it exists. ``param`` names the parameter in the
    messages, which never include file contents.
    """
    allowed = [Path(root).expanduser().resolve() for root in roots]
    try:
        candidate = Path(path).expanduser()
        resolved = (candidate if candidate.is_absolute() else output_root() / candidate).resolve()
    except (OSError, RuntimeError, ValueError):
        # Symlink loops, unknown users in "~user" and NUL bytes.
        raise PathPolicyError(f"{param} is not a usable path", "INVALID_PARAMETER") from None

    if not any(resolved.is_relative_to(root) for root in allowed):
        folders = ", ".join(str(root) for root in allowed) or "none"
        raise PathPolicyError(
            f"{param} must be inside one of the allowed folders",
            "INVALID_PARAMETER",
            hint=(
                f"Allowed folders: {folders}. Move the file into one of them, or add its folder to "
                "SHEET_MUSIC_INPUT_ROOTS in the server configuration."
            ),
        )
    if resolved.suffix.lower() not in suffixes:
        raise PathPolicyError(f"{param} must end with one of {', '.join(suffixes)}", "INVALID_PARAMETER")
    try:
        size = resolved.stat().st_size
    except OSError:
        size = None
    if size is None or not resolved.is_file():
        raise PathPolicyError(f"{param} does not exist or is not a file: {resolved}", "FILE_NOT_FOUND")
    if size > max_bytes:
        raise PathPolicyError(
            f"{param} is {size} bytes, larger than the limit of {max_bytes} bytes", "FILE_TOO_LARGE"
        )
    return resolved


def confine_output_path(output_path: str, suffixes: tuple[str, ...]) -> str:
    """Return *output_path* resolved inside the output root, or raise PathPolicyError.

    The path is chosen by the model, so it must not escape SHEET_MUSIC_OUTPUT_ROOT
    (default: the server's working directory), carry another file type, or
    overwrite an existing file.
    """
    root = output_root()
    candidate = Path(output_path).expanduser()
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise PathPolicyError(f"output_path must be inside {root}", "INVALID_PARAMETER")
    if resolved.suffix.lower() not in suffixes:
        raise PathPolicyError(f"output_path must end with one of {', '.join(suffixes)}", "INVALID_PARAMETER")
    if resolved.exists():
        raise PathPolicyError(f"output_path already exists: {resolved}", "INVALID_PARAMETER")
    return str(resolved)


def new_output_path(stem: str, suffix: str, *, subdir: str = "scores") -> Path:
    """A new file name ``<output root>/<subdir>/<stem>-<YYYYmmdd-HHMMSS-ffffff><suffix>``.

    The folder is created with mode 0700. An existing name gets a counter (``-1``, ``-2`` …), so
    nothing is overwritten. The stem is reduced to letters, digits, ``.``, ``_`` and ``-``.
    """
    root = output_root()
    folder = (root / subdir).resolve()
    if not folder.is_relative_to(root):
        raise PathPolicyError(f"Output folder {subdir!r} must be inside {root}", "INVALID_PARAMETER")
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)

    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-") or "score"
    base = f"{safe_stem}-{_timestamp()}"
    path = folder / f"{base}{suffix}"
    counter = 0
    while path.exists():
        counter += 1
        path = folder / f"{base}-{counter}{suffix}"
    return path


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")
