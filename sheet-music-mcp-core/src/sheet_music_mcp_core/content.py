"""Result content blocks (docs/conventions.md, Result Content)."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from mcp.types import AudioContent, ImageContent, ResourceLink, TextContent

from .errors import ProcessingError, error_payload

IMAGE_MAX_BYTES = 1024 * 1024
AUDIO_MAX_BYTES = 200 * 1024


def error_content(
    message: str,
    error_code: str,
    *,
    hint: str | None = None,
    choices: list[str] | None = None,
) -> list[TextContent]:
    """The error envelope as the single text block a tool returns."""
    payload = error_payload(message, error_code, hint=hint, choices=choices)
    return [TextContent(type="text", text=json.dumps(payload))]


def processing_error_content(error: ProcessingError) -> list[TextContent]:
    """A raised ProcessingError as the error block, keeping its hint and choices."""
    return error_content(str(error), error.error_code, hint=error.hint, choices=error.choices)


def file_link(path: str, mime_type: str) -> ResourceLink:
    """A link to a file the tool wrote, so hosts can offer to open it."""
    resolved = Path(path).resolve()
    return ResourceLink(
        type="resource_link",
        uri=resolved.as_uri(),
        name=resolved.name,
        mime_type=mime_type,
        size=resolved.stat().st_size,
    )


def png_block(path: str, *, max_bytes: int = IMAGE_MAX_BYTES) -> ImageContent | None:
    """The PNG at ``path`` as an inline image, or None if it is larger than ``max_bytes``.

    The size is checked before reading, so an oversize file is never loaded into memory.
    """
    file = Path(path)
    if file.stat().st_size > max_bytes:
        return None
    data = file.read_bytes()
    return ImageContent(type="image", data=base64.b64encode(data).decode("ascii"), mime_type="image/png")


def audio_block(path: str, *, max_bytes: int = AUDIO_MAX_BYTES) -> AudioContent | None:
    """The WAV at ``path`` as inline audio, or None if it is larger than ``max_bytes``.

    The size is checked before reading, so an oversize file is never loaded into memory.
    """
    file = Path(path)
    if file.stat().st_size > max_bytes:
        return None
    data = file.read_bytes()
    return AudioContent(type="audio", data=base64.b64encode(data).decode("ascii"), mime_type="audio/wav")
