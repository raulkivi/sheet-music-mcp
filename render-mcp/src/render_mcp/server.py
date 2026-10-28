import asyncio
import json
import logging

import mcp.server.stdio
from mcp.server import Server
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations
from sheet_music_mcp_core.annotations import READ_ONLY, WRITES_FILE
from sheet_music_mcp_core.content import error_content, processing_error_content
from sheet_music_mcp_core.measures import MEASURES_PROPERTY
from sheet_music_mcp_core.references import (
    DESCRIBE_SCORE_TOOL,
    describe_score_tool,
    exactly_one,
    load_score,
    score_input_properties,
)
from sheet_music_mcp_core.ui import PackageAssetSource, UiRegistry, UiResource
from sheet_music_mcp_core.wiring import make_handlers, make_resource_handlers

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
from .presenter import IMAGE_OUTPUT_SCHEMA, PDF_OUTPUT_SCHEMA, present_image, present_pdf
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
    "Output files are written under SHEET_MUSIC_OUTPUT_ROOT and never overwrite an existing file. "
    "PNG pages are also returned inline when the client shows images. "
    "Pass measures=[start, end] (printed bar numbers) to render only those bars. "
    "Prefer musicxml_path over inline musicxml and pass on the score paths other tools return; "
    "use describe_score to learn a score's part IDs and size cheaply."
)

SCORE_VIEWER = UiResource(
    "ui://render/score-viewer",
    "score-viewer.html",
    "Score Viewer",
    "Pages through and zooms the rendered score inline.",
)

# Reads the HTML packaged under render_mcp/ui/assets/; tests replace ui_registry with in-memory
# assets. Without a UI build the viewer is hidden and the tools carry no _meta.ui.
DEFAULT_UI_REGISTRY = UiRegistry([SCORE_VIEWER], PackageAssetSource("render_mcp"))
ui_registry = DEFAULT_UI_REGISTRY


def _score_properties() -> dict:
    """The musicxml / musicxml_path pair; exactly one is required (docs/conventions.md)."""
    properties = score_input_properties("musicxml", "musicxml_path", what="the score to render")
    properties["musicxml"]["description"] = (
        "MusicXML document as a string. Give this or 'musicxml_path', not both."
    )
    return properties


def _measures_argument(arguments: dict) -> dict:
    """``{"measures": ...}`` when the caller passed a range, else ``{}`` (conventions, Measure Ranges).

    The engine cuts the score before backend dispatch; without a range the call is unchanged.
    """
    return {"measures": arguments["measures"]} if arguments.get("measures") is not None else {}


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
                    **_score_properties(),
                    **MEASURES_PROPERTY,
                    "output_path": {
                        "type": "string",
                        "description": "Path to write PDF file (auto-generated if omitted)",
                    },
                },
                **exactly_one("musicxml", "musicxml_path"),
            },
            output_schema=PDF_OUTPUT_SCHEMA,
            meta=ui_registry.meta_for(SCORE_VIEWER),
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
                    **_score_properties(),
                    **MEASURES_PROPERTY,
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
                **exactly_one("musicxml", "musicxml_path"),
            },
            output_schema=IMAGE_OUTPUT_SCHEMA,
            meta=ui_registry.meta_for(SCORE_VIEWER),
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
        DESCRIBE_SCORE_TOOL,
    ]


def _error(content: list) -> CallToolResult:
    # isError, so clients skip output_schema validation of the absent structured content.
    return CallToolResult(content=content, is_error=True)


async def _render_pdf(arguments: dict, ctx) -> CallToolResult:
    try:
        musicxml = await load_score(arguments, ctx)
    except ProcessingError as e:
        return _error(processing_error_content(e))
    output_path = arguments.get("output_path")

    ok, err = validate_musicxml(musicxml)
    if not ok:
        return _error(error_content(err, "INVALID_INPUT"))

    try:
        resolved_output = generate_pdf_path(output_path)
    except ValueError as e:
        return _error(error_content(str(e), "INVALID_PARAMETER"))

    try:
        pdf_path, page_count = render_to_pdf(musicxml, resolved_output, **_measures_argument(arguments))
    except ProcessingError as e:
        return _error(processing_error_content(e))
    except Exception as e:
        logger.error("render_to_pdf unexpected error: %s", e)
        return _error(error_content(f"Rendering failed: {e}", "PROCESSING_FAILED"))

    content, structured = present_pdf(pdf_path, page_count, detect_backend())
    return CallToolResult(content=content, structured_content=structured)


async def _render_image(arguments: dict, ctx) -> CallToolResult:
    try:
        musicxml = await load_score(arguments, ctx)
    except ProcessingError as e:
        return _error(processing_error_content(e))
    page = arguments.get("page", PAGE_DEFAULT)
    fmt = arguments.get("format", "png")
    dpi = arguments.get("dpi", DPI_DEFAULT)
    output_path = arguments.get("output_path")

    ok, err = validate_musicxml(musicxml)
    if not ok:
        return _error(error_content(err, "INVALID_INPUT"))

    for ok, err in (validate_page(page), validate_image_format(fmt), validate_dpi(dpi)):
        if not ok:
            return _error(error_content(err, "INVALID_PARAMETER"))

    try:
        resolved_output = generate_image_path(output_path, fmt)
    except ValueError as e:
        return _error(error_content(str(e), "INVALID_PARAMETER"))

    try:
        result = render_to_image(musicxml, page, fmt, dpi, resolved_output, **_measures_argument(arguments))
    except ProcessingError as e:
        return _error(processing_error_content(e))
    except Exception as e:
        logger.error("render_to_image unexpected error: %s", e)
        return _error(error_content(f"Rendering failed: {e}", "PROCESSING_FAILED"))

    content, structured = present_image(result)
    return CallToolResult(content=content, structured_content=structured)


_RESULT_TOOLS = {"render_to_pdf": _render_pdf, "render_to_image": _render_image}


async def call_tool(name: str, arguments: dict, ctx=None) -> list:
    """The tool's content blocks: what every client sees, structured content aside."""
    return (await call_tool_result(name, arguments, ctx)).content


async def call_tool_result(name: str, arguments: dict, ctx=None) -> CallToolResult:
    """The full result the server sends, ``structuredContent`` included."""
    if name in _RESULT_TOOLS:
        return await _RESULT_TOOLS[name](arguments, ctx)
    return CallToolResult(content=await _plain_tool(name, arguments, ctx))


async def _plain_tool(name: str, arguments: dict, ctx) -> list:
    if name == "list_capabilities":
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
                        "input_formats": ["musicxml", "mxl"],
                        "input_parameters": ["musicxml", "musicxml_path", "measures"],
                        "output_formats": ["pdf", "png", "svg"],
                        "tools": [
                            "render_to_pdf",
                            "render_to_image",
                            "describe_score",
                            "list_capabilities",
                        ],
                        "backend": backend,
                        "backend_version": backend_version,
                        "musescore_available": ms_available,
                        "verovio_available": vr_available,
                    },
                    indent=2,
                ),
            )
        ]

    elif name == "describe_score":
        try:
            return await describe_score_tool(arguments, ctx)
        except ProcessingError as e:
            return processing_error_content(e)

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


class _CurrentUiRegistry:
    """Serves whichever registry ``ui_registry`` holds at request time, so tests can swap it."""

    def list_resources(self):
        return ui_registry.list_resources()

    def read(self, uri: str):
        return ui_registry.read(uri)


_on_list_tools, _on_call_tool = make_handlers(
    list_tools, call_tool_result, pass_context=True, logger=logger
)
_on_list_resources, _on_read_resource = make_resource_handlers(_CurrentUiRegistry(), logger=logger)

app = Server(
    "render-mcp",
    instructions=INSTRUCTIONS,
    on_list_tools=_on_list_tools,
    on_call_tool=_on_call_tool,
    on_list_resources=_on_list_resources,
    on_read_resource=_on_read_resource,
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
