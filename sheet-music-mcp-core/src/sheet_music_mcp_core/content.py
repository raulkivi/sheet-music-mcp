"""Result content blocks (docs/conventions.md, Result Content)."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from mcp.types import ImageContent, ResourceLink, TextContent

from .errors import error_payload

IMAGE_MAX_BYTES = 1024 * 1024


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
    """The PNG at ``path`` as an inline image, or None if it is larger than ``max_bytes``."""
    data = Path(path).read_bytes()
    if len(data) > max_bytes:
        return None
    return ImageContent(type="image", data=base64.b64encode(data).decode("ascii"), mime_type="image/png")
