"""Engine results to tool results: ``content`` for every client, ``structuredContent`` for apps.

``content`` is exactly what the render tools returned before MCP Apps (a JSON text block, then
the file blocks), so text-only clients see no change. ``structuredContent`` carries the same data
as that JSON text, which the MCP spec asks for and the Score Viewer reads.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.types import TextContent
from sheet_music_mcp_core.content import file_link, png_block

IMAGE_MIME_TYPES = {"png": "image/png", "svg": "image/svg+xml"}

PDF_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "pdf_path": {"type": "string", "description": "Where the PDF was written"},
        "page_count": {"type": "integer", "minimum": 0},
        "backend": {"type": ["string", "null"], "description": "'verovio' or 'musescore'"},
    },
    "required": ["pdf_path", "page_count", "backend"],
}

IMAGE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "image_path": {"type": "string", "description": "Where the image was written"},
        "format": {"type": "string", "enum": list(IMAGE_MIME_TYPES)},
        "page": {"type": "integer", "minimum": 1},
        "total_pages": {"type": "integer", "minimum": 0},
        "backend": {"type": "string"},
        "width_px": {"type": "integer", "description": "PNG only"},
        "height_px": {"type": "integer", "description": "PNG only"},
    },
    "required": ["image_path", "format", "page"],
}

PAGE_SVG_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "svg": {"type": "string", "description": "The page as an SVG document"},
        "page": {"type": "integer", "minimum": 1},
        "page_count": {"type": "integer", "minimum": 1, "description": "Pages at this width and zoom"},
    },
    "required": ["svg", "page", "page_count"],
}


def present_pdf(pdf_path: str, page_count: int, backend: str | None) -> tuple[list, dict]:
    """``(content, structured_content)`` for a rendered PDF."""
    data = {"pdf_path": pdf_path, "page_count": page_count, "backend": backend}
    return _json_then_files(data, pdf_path, "application/pdf"), dict(data)


def present_image(result: dict) -> tuple[list, dict]:
    """``(content, structured_content)`` for the engine's ``render_to_image`` result."""
    mime_type = IMAGE_MIME_TYPES[result["format"]]
    return _json_then_files(result, result["image_path"], mime_type), dict(result)


def _json_then_files(data: dict, path: str, mime_type: str) -> list:
    return [TextContent(type="text", text=json.dumps(data, indent=2)), *_file_blocks(path, mime_type)]


def _file_blocks(path: str, mime_type: str) -> list:
    """Blocks after the JSON text for a written file (conventions, Result Content).

    A PNG of at most 1 MB is also sent inline; SVG and PDF get only the link.
    """
    if not Path(path).is_file():
        return []
    blocks = []
    if mime_type == "image/png":
        image = png_block(path)
        if image is not None:
            blocks.append(image)
    blocks.append(file_link(path, mime_type))
    return blocks


def present_page_svg(page: dict) -> tuple[list, dict]:
    """``(content, structured_content)`` for one viewer page.

    Only the app reads the SVG, so the text block just says what was rendered and keeps the
    markup out of any model context.
    """
    size_kb = max(1, round(len(page["svg"].encode("utf-8")) / 1024))
    text = f"Page {page['page']} of {page['page_count']} rendered as SVG ({size_kb} kB) for the Score Viewer."
    return [TextContent(type="text", text=text)], dict(page)
