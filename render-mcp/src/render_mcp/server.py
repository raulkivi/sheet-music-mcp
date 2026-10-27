import asyncio
import json
import logging

import mcp.server.stdio
from mcp.server import Server
from mcp.types import TextContent, Tool, ToolAnnotations
from sheet_music_mcp_core.annotations import READ_ONLY, WRITES_FILE
from sheet_music_mcp_core.content import error_content
from sheet_music_mcp_core.wiring import make_handlers

from . import __version__
from .engine import (
    ProcessingError,
    cairosvg_available,
    detect_backend,
    get_health_status,
    musescore_available,
    render_to_image,
    render_to_pdf,
    verovio_available,
)
from .utils import (
    DPI_DEFAULT,
    PAGE_DEFAULT,
    generate_image_path,
    generate_pdf_path,
    validate_dpi,
    validate_image_format,
    validate_musicxml,
    validate_page,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Sent to the client at initialize (docs/conventions.md, Server Instructions).
INSTRUCTIONS = (
    "Renders a MusicXML score to PDF (render_to_pdf) or one page to PNG or SVG (render_to_image). "
    "Output files are written under SHEET_MUSIC_OUTPUT_ROOT and never overwrite an existing file."
)


async def list_tools():
    return [
        Tool(
            name="render_to_pdf",
            title="Render score to PDF",
            annotations=ToolAnnotations(**WRITES_FILE),
            description="Render a MusicXML score to a PDF file",
            input_schema={
                "type": "object",
                "properties": {
                    "musicxml": {
                        "type": "string",
                        "description": "MusicXML document as a string",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Path to write PDF file (auto-generated if omitted)",
                    },
                },
                "required": ["musicxml"],
            },
        ),
        Tool(
            name="render_to_image",
            title="Render score page to image",
            annotations=ToolAnnotations(**WRITES_FILE),
            description=(
                "Render a single page of a MusicXML score to PNG or SVG"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "musicxml": {
                        "type": "string",
                        "description": "MusicXML document as a string",
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number to render, 1-indexed (default: 1)",
                    },
                    "format": {
                        "type": "string",
                        "enum": ["png", "svg"],
                        "description": "Output format: 'png' or 'svg' (default: 'png')",
                    },
                    "dpi": {
                        "type": "integer",
                        "description": (
                            "Resolution for PNG output in dots per inch "
                            "(default: 150, range: 72–600)"
                        ),
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Path to write image file (auto-generated if omitted)",
                    },
                },
                "required": ["musicxml"],
            },
        ),
        Tool(
            name="list_capabilities",
            title="Render capabilities",
            annotations=ToolAnnotations(**READ_ONLY),
            description="List supported formats and available backends for this render server",
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="health_check",
            title="Render health check",
            annotations=ToolAnnotations(**READ_ONLY),
            description=(
                "Check whether all runtime dependencies are available and the server "
                "is ready to render scores. Returns a human-readable status summary."
            ),
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
    ]


async def call_tool(name: str, arguments: dict):
    if name == "render_to_pdf":
        musicxml = arguments.get("musicxml", "")
        output_path = arguments.get("output_path")

        ok, err = validate_musicxml(musicxml)
        if not ok:
            return error_content(err, "INVALID_INPUT")

        try:
            resolved_output = generate_pdf_path(output_path)
        except ValueError as e:
            return error_content(str(e), "INVALID_PARAMETER")

        try:
            pdf_path, page_count = render_to_pdf(musicxml, resolved_output)
        except ProcessingError as e:
            return error_content(str(e), e.error_code)
        except Exception as e:
            logger.error("render_to_pdf unexpected error: %s", e)
            return error_content(f"Rendering failed: {e}", "PROCESSING_FAILED")

        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "pdf_path": pdf_path,
                        "page_count": page_count,
                        "backend": detect_backend(),
                    },
                    indent=2,
                ),
            )
        ]

    elif name == "render_to_image":
        musicxml = arguments.get("musicxml", "")
        page = arguments.get("page", PAGE_DEFAULT)
        fmt = arguments.get("format", "png")
        dpi = arguments.get("dpi", DPI_DEFAULT)
        output_path = arguments.get("output_path")

        ok, err = validate_musicxml(musicxml)
        if not ok:
            return error_content(err, "INVALID_INPUT")

        ok, err = validate_page(page)
        if not ok:
            return error_content(err, "INVALID_PARAMETER")

        ok, err = validate_image_format(fmt)
        if not ok:
            return error_content(err, "INVALID_PARAMETER")

        ok, err = validate_dpi(dpi)
        if not ok:
            return error_content(err, "INVALID_PARAMETER")

        try:
            resolved_output = generate_image_path(output_path, fmt)
        except ValueError as e:
            return error_content(str(e), "INVALID_PARAMETER")

        try:
            result = render_to_image(musicxml, page, fmt, dpi, resolved_output)
        except ProcessingError as e:
            return error_content(str(e), e.error_code)
        except Exception as e:
            logger.error("render_to_image unexpected error: %s", e)
            return error_content(f"Rendering failed: {e}", "PROCESSING_FAILED")

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "list_capabilities":
        backend = detect_backend()
        ms_available = musescore_available()
        vr_available = verovio_available()

        backend_version = "unknown"
        if ms_available:
            try:
                import subprocess
                r = subprocess.run(
                    [backend, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                first_line = (r.stdout + r.stderr).strip().split("\n")[0]
                backend_version = first_line.strip() or "unknown"
            except Exception:
                pass
        elif vr_available:
            try:
                import importlib.metadata
                backend_version = importlib.metadata.version("verovio")
            except Exception:
                pass

        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "server": "render-mcp",
                        "version": __version__,
                        "input_formats": ["musicxml"],
                        "output_formats": ["pdf", "png", "svg"],
                        "tools": ["render_to_pdf", "render_to_image", "list_capabilities"],
                        "backend": backend,
                        "backend_version": backend_version,
                        "musescore_available": ms_available,
                        "verovio_available": vr_available,
                    },
                    indent=2,
                ),
            )
        ]

    elif name == "health_check":
        status = get_health_status()
        lines = [
            f"render-mcp status: {status['status'].upper()}",
            f"  Backend:   {status['backend'] or 'none'}",
            f"  MuseScore: {'✓' if status['musescore_available'] else '✗'}",
            f"  Verovio:   {'✓' if status['verovio_available'] else '✗'}",
            f"  cairosvg:  {'✓' if status['cairosvg_available'] else '✗'}",
        ]
        if status["notes"]:
            lines.append("")
            lines.append("Warnings:")
            for note in status["notes"]:
                lines.append(f"  - {note}")
        return [TextContent(type="text", text="\n".join(lines))]

    raise ValueError(f"Unknown tool: {name}")


_on_list_tools, _on_call_tool = make_handlers(list_tools, call_tool, logger=logger)

app = Server(
    "render-mcp",
    instructions=INSTRUCTIONS,
    on_list_tools=_on_list_tools,
    on_call_tool=_on_call_tool,
)


def main():
    """Entry point for render-mcp."""
    logger.info("render-mcp starting…")

    backend = detect_backend()
    if backend is None:
        logger.warning(
            "No rendering backend available. "
            "Install MuseScore 4 or run: uv add verovio cairosvg"
        )
    else:
        logger.info("Active backend: %s", backend)
        if musescore_available():
            from .engine import _MUSESCORE_CMD
            logger.info("MuseScore command: %s", _MUSESCORE_CMD)
        if verovio_available():
            logger.info("Verovio: available")

    if not cairosvg_available():
        logger.warning(
            "cairosvg could not be imported (libcairo2 may be missing). "
            "PNG and PDF output via Verovio will fail. "
            "Install libcairo2 and run: uv add cairosvg"
        )
    else:
        logger.info("cairosvg: available")

    logger.info("render-mcp ready — use the health_check tool to verify setup")

    async def _run():
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
