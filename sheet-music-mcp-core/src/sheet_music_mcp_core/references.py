"""Score references: scores passed and returned as file paths (docs/conventions.md, Score References).

Servers use these functions instead of resolving roots or opening score files themselves.
"""

from __future__ import annotations

import asyncio
import json
import os
import warnings
from pathlib import Path
from types import MappingProxyType
from typing import Any, Sequence
from urllib.parse import urlparse
from urllib.request import url2pathname

from mcp.types import TextContent, Tool, ToolAnnotations

from .annotations import READ_ONLY
from .content import file_link
from .errors import ProcessingError
from .paths import SCORE_SUFFIXES, confine_read_path, max_score_bytes, new_output_path, read_roots
from .scores import ScoreFormatError, describe_score, parse_score, read_score_file, score_summary

__all__ = [
    "SCORE_MIME_TYPE",
    "RETURN_MODES",
    "RETURN_PROPERTY",
    "score_input_properties",
    "exactly_one",
    "inline_max_bytes",
    "client_roots",
    "load_score",
    "deliver_score",
    "DESCRIBE_SCORE_TOOL",
    "describe_score_tool",
]

SCORE_MIME_TYPE = "application/vnd.recordare.musicxml+xml"
RETURN_MODES = ("auto", "path", "inline")
DEFAULT_INLINE_MAX_BYTES = 8192
ROOTS_TIMEOUT_SECONDS = 2.0

RETURN_PROPERTY = MappingProxyType(
    {
        "return": {
            "type": "string",
            "enum": list(RETURN_MODES),
            "default": "auto",
            "description": (
                "How to return the score: 'inline' as MusicXML text, 'path' as a file path plus a "
                "short score_summary, 'auto' (default) inline for small scores and a path for "
                "large ones. Pass returned paths to other tools as musicxml_path."
            ),
        }
    }
)


# --- Input schema ----------------------------------------------------------------------------


def score_input_properties(
    inline: str = "musicxml", path: str = "musicxml_path", *, what: str = "the score"
) -> dict:
    """JSON Schema ``properties`` for an inline/path pair; combine with ``exactly_one``."""
    return {
        inline: {
            "type": "string",
            "description": f"MusicXML text of {what}. Give this or '{path}', not both.",
        },
        path: {
            "type": "string",
            "description": (
                f"Path to {what} as a .musicxml, .xml or .mxl file, such as a path another tool "
                f"returned. Preferred over '{inline}': the score is not copied into the "
                f"conversation. Give this or '{inline}', not both."
            ),
        },
    }


def exactly_one(inline: str = "musicxml", path: str = "musicxml_path") -> dict:
    """``{"oneOf": ...}`` requiring exactly one of the pair. Combine two pairs with ``allOf``."""
    return {"oneOf": [{"required": [inline]}, {"required": [path]}]}


# --- Reading ---------------------------------------------------------------------------------


async def client_roots(ctx) -> list[Path]:
    """The client's ``file://`` MCP roots as paths.

    ``[]`` when ``ctx`` is None, the client does not declare the roots capability, the request
    fails or takes longer than ``ROOTS_TIMEOUT_SECONDS``. Connections on protocol 2026-07-28 or
    later cannot send server requests at all, so they always give ``[]``.
    """
    if ctx is None:
        return []
    try:
        session = ctx.session
        capabilities = session.client_capabilities
        if capabilities is None or getattr(capabilities, "roots", None) is None:
            return []
        if getattr(session, "can_send_request", True) is False:
            return []
        with warnings.catch_warnings():
            # mcp 2.x marks roots deprecated (SEP-2577) and warns on every call.
            warnings.simplefilter("ignore")
            request = session.list_roots()
        result = await asyncio.wait_for(request, ROOTS_TIMEOUT_SECONDS)
        uris = [str(root.uri) for root in result.roots]
    except Exception:
        return []
    return [path for uri in uris if (path := _file_uri_path(uri)) is not None]


def _file_uri_path(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    if parsed.netloc in ("", "localhost"):
        return Path(url2pathname(parsed.path))
    if os.name == "nt":  # UNC share: file://server/share/folder
        return Path(url2pathname(f"//{parsed.netloc}{parsed.path}"))
    return None


async def load_score(arguments: dict, ctx, *, inline: str = "musicxml", path: str = "musicxml_path") -> str:
    """The MusicXML text given as ``arguments[inline]`` or read from ``arguments[path]``.

    Inline text is returned as is; servers keep their own inline validation. A path is confined to
    the read roots (output root, the client's roots, ``SHEET_MUSIC_INPUT_ROOTS``), size-checked,
    read (``.mxl`` too) and checked to be well-formed MusicXML. Raises ProcessingError:
    INVALID_PARAMETER for both or neither parameter or a path outside the roots, FILE_NOT_FOUND,
    FILE_TOO_LARGE or INVALID_INPUT.
    """
    has_inline = arguments.get(inline) is not None
    has_path = arguments.get(path) is not None
    if has_inline and has_path:
        raise ProcessingError(f"Give only one of '{inline}' and '{path}'.", "INVALID_PARAMETER")
    if not has_inline and not has_path:
        raise ProcessingError(f"One of '{inline}' or '{path}' is required.", "INVALID_PARAMETER")
    if has_inline:
        return arguments[inline]

    value = arguments[path]
    if not isinstance(value, str):
        raise ProcessingError(f"{path} must be a string.", "INVALID_PARAMETER")
    limit = max_score_bytes()
    roots = read_roots(await client_roots(ctx))
    file = confine_read_path(value, roots=roots, suffixes=SCORE_SUFFIXES, max_bytes=limit, param=path)
    try:
        text = read_score_file(file, max_bytes=limit)
        parse_score(text)
    except ScoreFormatError as error:
        raise ScoreFormatError(f"{path}: {error}", hint=error.hint) from None
    return text


# --- Returning -------------------------------------------------------------------------------


def inline_max_bytes() -> int:
    """``SHEET_MUSIC_INLINE_MAX_BYTES``; 8192 when unset, not a number or negative."""
    try:
        value = int(os.environ.get("SHEET_MUSIC_INLINE_MAX_BYTES", ""))
    except ValueError:
        return DEFAULT_INLINE_MAX_BYTES
    return value if value >= 0 else DEFAULT_INLINE_MAX_BYTES


def deliver_score(
    payload: dict,
    *,
    field: str | Sequence[str] = "musicxml",
    musicxml: str | Sequence[str] | None = None,
    mode: str | None = "auto",
    stem: str = "score",
) -> list:
    """The content blocks for a tool result carrying one or more scores.

    ``payload[field]`` holds the MusicXML text unless ``musicxml`` gives it. ``mode``:

    - ``inline``: ``content[0]`` is ``json.dumps(payload, indent=2)``, exactly as before.
    - ``path``: the score is written to ``<output root>/scores/<stem>-<timestamp>.musicxml``. In
      ``content[0]`` the field is replaced, in place, by ``<field>_path``, and ``score_summary`` is
      added (null if the score does not parse); a ``ResourceLink`` follows for each file.
    - ``auto`` (also None): ``inline`` if every score is at most ``SHEET_MUSIC_INLINE_MAX_BYTES``
      UTF-8 bytes (default 8192), else ``path``.

    ``field`` may be a tuple of fields, with ``musicxml`` then a tuple of the same length, for
    tools returning several scores (comparer's annotated pair). In ``auto`` mode they are written
    together when any one exceeds the limit; each file's stem is ``<stem>-<field>``, and
    ``score_summary`` maps each field to its summary. A payload without the field (an error
    result) is returned inline. ``payload`` itself is never changed. Unknown modes raise
    ProcessingError (INVALID_PARAMETER).
    """
    mode = mode or "auto"
    if mode not in RETURN_MODES:
        raise ProcessingError(
            f"Unknown return mode '{mode}'.", "INVALID_PARAMETER", choices=list(RETURN_MODES)
        )
    several = not isinstance(field, str)
    fields = tuple(field) if several else (field,)
    if musicxml is None:
        texts = tuple(payload.get(name) for name in fields)
    else:
        texts = tuple(musicxml) if several else (musicxml,)

    if any(not isinstance(text, str) for text in texts):
        mode = "inline"
    elif mode == "auto":
        limit = inline_max_bytes()
        mode = "path" if any(len(text.encode("utf-8")) > limit for text in texts) else "inline"
    if mode == "inline":
        return [_json_block(payload)]

    written = {
        name: _write_score(text, f"{stem}-{name}" if several else stem) for name, text in zip(fields, texts)
    }
    result = {}
    for key, value in payload.items():
        if key in written:
            result[f"{key}_path"] = str(written[key])
        else:
            result[key] = value
    for name in fields:  # fields that the payload did not hold
        result.setdefault(f"{name}_path", str(written[name]))
    summaries = {name: _summary_or_none(text) for name, text in zip(fields, texts)}
    result["score_summary"] = summaries if several else summaries[field]
    return [_json_block(result), *(file_link(str(path), SCORE_MIME_TYPE) for path in written.values())]


def _write_score(text: str, stem: str) -> Path:
    """Write ``text`` to a new file readable only by this user (0600, like the 0700 folder),
    never replacing one that appeared in the meantime."""
    while True:
        path = new_output_path(stem, ".musicxml")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as file:
            file.write(text)
        return path


def _summary_or_none(text: str) -> dict | None:
    try:
        return score_summary(text)
    except ScoreFormatError:
        return None


def _json_block(payload: Any) -> TextContent:
    # Servers emitted json.dumps(result, indent=2); keep content[0] byte-identical.
    return TextContent(type="text", text=json.dumps(payload, indent=2))


# --- The shared describe_score tool ----------------------------------------------------------

DESCRIBE_SCORE_TOOL = Tool(
    name="describe_score",
    title="Describe score",
    description=(
        "Summarize a score cheaply, without music21 or rendering: title, composer, key, time "
        "signature, tempo, parts (ID, name, abbreviation, clef, sounding range), number of "
        "measures, whether it has lyrics, and duration in quarter notes and seconds. Returns "
        "small JSON and does not return the score itself, so call it first to learn the part IDs "
        "and size of a score. Pass musicxml_path (preferred) or musicxml."
    ),
    input_schema={
        "type": "object",
        "properties": score_input_properties("musicxml", "musicxml_path", what="the score"),
        **exactly_one("musicxml", "musicxml_path"),
    },
    annotations=ToolAnnotations(**READ_ONLY),
)


async def describe_score_tool(arguments: dict, ctx) -> list[TextContent]:
    """Run ``describe_score`` for a tool call. Raises ProcessingError, which ``make_handlers``
    returns as an error result."""
    text = await load_score(arguments, ctx)
    return [_json_block(describe_score(text))]
