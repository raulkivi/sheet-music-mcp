import mcp.server.stdio
from mcp.server import Server
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations
from sheet_music_mcp_core.annotations import READ_ONLY, WRITES_FILE_DOWNLOADS
from sheet_music_mcp_core.artifacts import MAX_CHUNK_BYTES, FileArtifactStore, chunk_payload
from sheet_music_mcp_core.content import error_content, file_link, processing_error_content
from sheet_music_mcp_core.errors import ProcessingError
from sheet_music_mcp_core.paths import max_score_bytes
from sheet_music_mcp_core.references import RETURN_PROPERTY, SCORE_MIME_TYPE, deliver_score
from sheet_music_mcp_core.scores import read_score_file, score_summary
from sheet_music_mcp_core.ui import PackageAssetSource, UiRegistry, UiResource
from sheet_music_mcp_core.wiring import make_handlers, make_resource_handlers
import asyncio
import json
import logging
import os
import time

from . import __version__
from .omr_engine import recognize_image, recognize_image_to_file, recognize_images, health_check as _engine_health_check
from .presenter import PREVIEW_OUTPUT_SCHEMA, RECOGNITION_OUTPUT_SCHEMA, present_preview, present_recognition
from .previews import SourcePreviews, write_source_preview
from .staff_estimate import estimate_staves
from .utils import decode_base64_image, SUPPORTED_IMAGE_FORMATS

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Sent to the client at initialize (docs/conventions.md, Server Instructions).
INSTRUCTIONS = (
    "Converts photos or scans of printed sheet music (PNG or JPEG) to MusicXML. "
    "For choir (SATB, multi-staff) scores use engine='audiveris' with 300+ DPI images; the default "
    "oemer engine merges the staves into one part. recognize_sheets merges several pages into one score. "
    "First use downloads models (oemer ~100 MB, Audiveris ~80 MB) and a page can take minutes. "
    "Large results come back as a musicxml_path (a file) plus a short score_summary instead of the "
    "MusicXML text; pass that path on to other servers' tools as their musicxml_path parameter "
    "rather than copying the score."
)

MUSICXML_MIME_TYPE = SCORE_MIME_TYPE
# File name stem of scores that recognize_sheet / recognize_sheets write in 'path' mode.
RECOGNIZED_STEM = "recognized"

RECOGNITION_REVIEW = UiResource(
    "ui://omr/recognition-review",
    "recognition-review.html",
    "Recognition Review",
    "Shows the photographed page next to the recognised score and warns when a choir score was flattened.",
)

# Reads the HTML packaged under omr_mcp/ui/assets/; tests replace ui_registry with in-memory
# assets. Without a UI build the app is hidden and the tools carry no _meta.ui.
DEFAULT_UI_REGISTRY = UiRegistry([RECOGNITION_REVIEW], PackageAssetSource("omr_mcp"))
ui_registry = DEFAULT_UI_REGISTRY

# Source previews live in the output root and are served by opaque id (never by path).
artifact_store = FileArtifactStore()
source_previews = SourcePreviews()


async def list_tools():
    return [
        Tool(
            name="recognize_sheet",
            title="Recognize sheet music",
            annotations=ToolAnnotations(**WRITES_FILE_DOWNLOADS),
            description=(
                "Recognize music notation from an image and return MusicXML. Small scores come back "
                "inline as 'musicxml'; large ones (return='auto', the default) are written to a file "
                "and come back as 'musicxml_path' plus a short 'score_summary' (title, parts with IDs "
                "and ranges, measures, key, time, tempo). Pass that path to other tools as "
                "musicxml_path. Use return='inline' to always get the text, return='path' to always "
                "get a file."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "image": {
                        "type": "string",
                        "description": "File path or base64-encoded image data"
                    },
                    "format": {
                        "type": "string",
                        "enum": ["path", "base64"],
                        "description": "Input format hint: 'path' or 'base64' (auto-detected if omitted)"
                    },
                    "engine": {
                        "type": "string",
                        "enum": ["oemer", "audiveris"],
                        "description": (
                            "OMR backend to use. 'oemer' (default) is fast and works well for "
                            "single/two-staff scores. 'audiveris' correctly separates multi-staff "
                            "choir scores (SATB) into simultaneous parts, where oemer either "
                            "flattens them into one part or fails outright — but requires 300+ DPI "
                            "source images and downloads a much larger (~80 MB) engine on first use."
                        )
                    },
                    **RETURN_PROPERTY,
                },
                "required": ["image"]
            },
            output_schema=RECOGNITION_OUTPUT_SCHEMA,
            meta=ui_registry.meta_for(RECOGNITION_REVIEW),
        ),
        Tool(
            name="recognize_sheet_to_file",
            title="Recognize sheet music to file",
            annotations=ToolAnnotations(**WRITES_FILE_DOWNLOADS),
            description=(
                "Process sheet music image and save MusicXML result to filesystem. Returns the "
                "output_path (pass it to other tools as musicxml_path) and a short score_summary "
                "of the written score."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "input_path": {
                        "type": "string",
                        "description": "Path to input image"
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Path for output MusicXML file (auto-generated if omitted)"
                    },
                    "engine": {
                        "type": "string",
                        "enum": ["oemer", "audiveris"],
                        "description": "OMR backend to use — see recognize_sheet's 'engine' parameter."
                    }
                },
                "required": ["input_path"]
            }
        ),
        Tool(
            name="recognize_sheets",
            title="Recognize multi-page sheet music",
            annotations=ToolAnnotations(**WRITES_FILE_DOWNLOADS),
            description=(
                "Process multiple pages of sheet music in order and return a single merged MusicXML. "
                "Like recognize_sheet, a large merged score (return='auto', the default) comes back "
                "as 'musicxml_path' plus a 'score_summary' instead of inline 'musicxml'; pass that "
                "path to other tools as musicxml_path. return='inline' or 'path' forces either form."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "images": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ordered list of image file paths or base64-encoded images (one per page)"
                    },
                    "engine": {
                        "type": "string",
                        "enum": ["oemer", "audiveris"],
                        "description": "OMR backend to use — see recognize_sheet's 'engine' parameter."
                    },
                    **RETURN_PROPERTY,
                },
                "required": ["images"]
            },
            output_schema=RECOGNITION_OUTPUT_SCHEMA,
            meta=ui_registry.meta_for(RECOGNITION_REVIEW),
        ),
        Tool(
            name="get_source_preview",
            title="Source page preview",
            annotations=ToolAnnotations(**READ_ONLY),
            description=(
                "For the Recognition Review app only: a downscaled JPEG (at most 1600 px) of an input "
                "page of an earlier recognition, read in base64 chunks. Takes the job_id from "
                "recognize_sheet or recognize_sheets, never a path."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "job_id from a recognition result"},
                    "page": {"type": "integer", "minimum": 1, "default": 1, "description": "1-based page"},
                    "offset": {"type": "integer", "minimum": 0, "default": 0, "description": "First byte to read"},
                    "length": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_CHUNK_BYTES,
                        "default": MAX_CHUNK_BYTES,
                        "description": "Bytes to read",
                    },
                },
                "required": ["job_id"],
                "additionalProperties": False,
            },
            output_schema=PREVIEW_OUTPUT_SCHEMA,
            meta=ui_registry.meta_for(RECOGNITION_REVIEW, app_only=True),
        ),
        Tool(
            name="list_capabilities",
            title="OMR capabilities",
            annotations=ToolAnnotations(**READ_ONLY),
            description="List supported formats and available tools for this OMR server",
            input_schema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="list_supported_formats",
            title="OMR formats (deprecated)",
            annotations=ToolAnnotations(**READ_ONLY),
            description="(Deprecated — use list_capabilities) List supported input and output formats",
            input_schema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="health_check",
            title="OMR health check",
            annotations=ToolAnnotations(**READ_ONLY),
            description=(
                "Check that all runtime dependencies are available and return a "
                "human-readable status summary. Use this to verify the server is "
                "set up correctly, especially on first run."
            ),
            input_schema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
    ]

def _detect_input_format(image: str, format_hint: str | None) -> str:
    """Detect if input is a file path or base64 data."""
    if format_hint:
        return format_hint
    # Base64 data typically starts with data: or is very long without path separators
    if image.startswith("data:") or (len(image) > 500 and "/" not in image and "\\" not in image):
        return "base64"
    return "path"

def _deliver_recognized(result: dict, mode) -> list:
    """A recognize_sheet(s) result as content: the engine's error dicts as before, successes
    inline or as a musicxml_path + score_summary (docs/conventions.md, Score References).
    Raises ProcessingError for an unknown mode."""
    if "error" in result:
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    return deliver_score(result, field="musicxml", mode=mode, stem=RECOGNIZED_STEM)


def _written_score_summary(path) -> dict | None:
    """The score_summary of a MusicXML file the engine wrote; None if it can't be read or parsed."""
    if not path:
        return None
    try:
        return score_summary(read_score_file(path, max_bytes=max_score_bytes()))
    except (ProcessingError, OSError):
        return None


async def _run_with_progress(fn, *args, ctx=None, message_prefix: str, interval_seconds: float = 5.0, **kwargs):
    """Run a blocking, long-running engine call off the event loop, emitting periodic MCP
    progress notifications when the client supplied a progress token (PLAN.md Phase 2). oemer
    exposes no internal progress callback, so this is an elapsed-time heartbeat, not a true
    percentage. Also keeps the event loop responsive during the multi-minute oemer run, which a
    direct synchronous call would otherwise block entirely."""
    task = asyncio.create_task(asyncio.to_thread(fn, *args, **kwargs))

    # ctx is None when call_tool() is invoked directly, as in unit tests.
    progress_token = (ctx.meta or {}).get("progress_token") if ctx else None
    if progress_token is None:
        return await task

    start = time.monotonic()
    tick = 0
    while True:
        done, _ = await asyncio.wait({task}, timeout=interval_seconds)
        if task in done:
            return task.result()
        tick += 1
        elapsed = int(time.monotonic() - start)
        await ctx.session.send_progress_notification(
            progress_token,
            progress=tick,
            message=f"{message_prefix} ({elapsed}s elapsed)...",
            related_request_id=ctx.request_id,
        )

def _error(content: list) -> CallToolResult:
    # isError, so clients skip output_schema validation of the absent structured content.
    return CallToolResult(content=content, is_error=True)


def _prepare_review(image_paths: list[str]) -> tuple[list, list[int | None]]:
    """Per page image, its stored-preview file (None if unreadable) and staff count. Blocking."""
    previews, estimates = [], []
    for path in image_paths:
        try:
            previews.append(write_source_preview(path))
        except ProcessingError as e:
            logger.warning("No source preview for %s: %s", path, e)
            previews.append(None)
        estimates.append(estimate_staves(path))
    return previews, estimates


async def _present_recognition(result: dict, mode, image_paths: list[str]) -> CallToolResult:
    """content as before plus the Recognition Review's structuredContent; errors are isError."""
    if "error" in result:
        return _error(_deliver_recognized(result, mode))
    # The per-page detail is for structuredContent only; content must stay what it was.
    text_result = {key: value for key, value in result.items() if key != "_pages"}
    content = _deliver_recognized(text_result, mode)
    previews, estimates = await asyncio.to_thread(_prepare_review, image_paths)
    job_id = source_previews.register(artifact_store, previews)
    content, structured = present_recognition(
        result,
        content,
        job_id=job_id,
        previews=source_previews.available_pages(job_id),
        staff_estimates=estimates,
    )
    return CallToolResult(content=content, structured_content=structured)


async def _recognize_sheet(arguments: dict, ctx) -> CallToolResult:
    image = arguments["image"]
    format_hint = arguments.get("format")
    engine = arguments.get("engine", "oemer")
    input_format = _detect_input_format(image, format_hint)

    logger.info(f"Processing sheet music recognition (format: {input_format}, engine: {engine})")

    try:
        if input_format == "base64":
            # Decode base64 to temporary file
            success, path_or_error = decode_base64_image(image)
            if not success:
                return _error(error_content(path_or_error, "INVALID_INPUT"))
            image_path = path_or_error
        else:
            image_path = image

        result = await _run_with_progress(
            recognize_image, image_path, engine=engine, ctx=ctx, message_prefix="Running OMR recognition"
        )
        return await _present_recognition(result, arguments.get("return"), [image_path])
    except ProcessingError as e:
        return _error(processing_error_content(e))
    except Exception as e:
        logger.error(f"Error processing image: {str(e)}")
        return _error(error_content(f"Failed to process image: {str(e)}", "PROCESSING_FAILED"))


async def _recognize_sheet_to_file(arguments: dict, ctx) -> CallToolResult:
    input_path = arguments["input_path"]
    output_path = arguments.get("output_path")
    engine = arguments.get("engine", "oemer")

    logger.info(f"Processing sheet music to file: {input_path} (engine: {engine})")

    try:
        result = await _run_with_progress(
            recognize_image_to_file,
            input_path,
            output_path,
            engine=engine,
            ctx=ctx,
            message_prefix="Running OMR recognition",
        )
        # docs/conventions.md, Result Content. The engine returns (not raises) error dicts.
        failed = "error" in result
        written = None if failed else result.get("output_path")
        if not failed:
            result = {**result, "score_summary": _written_score_summary(written)}
        content = [TextContent(type="text", text=json.dumps(result, indent=2))]
        if written and os.path.isfile(written):
            content.append(file_link(written, MUSICXML_MIME_TYPE))
        return CallToolResult(content=content, is_error=failed)
    except Exception as e:
        logger.error(f"Error processing image: {str(e)}")
        return _error(error_content(f"Failed to process image: {str(e)}", "PROCESSING_FAILED"))


async def _recognize_sheets(arguments: dict, ctx) -> CallToolResult:
    images = arguments.get("images", [])
    engine = arguments.get("engine", "oemer")
    if not isinstance(images, list):
        return _error(error_content("'images' must be a list", "INVALID_PARAMETER"))

    logger.info(f"Processing {len(images)} sheet music page(s) (engine: {engine})")

    # Resolve any base64 inputs to temp files
    resolved_paths = []
    resolution_error = None
    for img in images:
        input_format = _detect_input_format(img, None)
        if input_format == "base64":
            success, path_or_error = decode_base64_image(img)
            if not success:
                resolution_error = path_or_error
                break
            resolved_paths.append(path_or_error)
        else:
            resolved_paths.append(img)

    if resolution_error:
        return _error(error_content(resolution_error, "INVALID_INPUT"))

    try:
        result = await _run_with_progress(
            recognize_images,
            resolved_paths,
            engine=engine,
            ctx=ctx,
            message_prefix=f"Running OMR recognition on {len(resolved_paths)} page(s)",
        )
        return await _present_recognition(result, arguments.get("return"), resolved_paths)
    except ProcessingError as e:
        return _error(processing_error_content(e))
    except Exception as e:
        logger.error(f"Error processing images: {str(e)}")
        return _error(error_content(f"Failed to process images: {str(e)}", "PROCESSING_FAILED"))


async def _get_source_preview(arguments: dict, ctx) -> CallToolResult:
    job_id = arguments.get("job_id")
    page = arguments.get("page", 1)
    try:
        artifact_id = source_previews.artifact_id(job_id, page)
        chunk = chunk_payload(
            artifact_store, artifact_id, arguments.get("offset", 0), arguments.get("length", MAX_CHUNK_BYTES)
        )
        content, structured = present_preview(job_id, page, chunk)
        return CallToolResult(content=content, structured_content=structured)
    except ProcessingError as e:
        return _error(processing_error_content(e))


_RESULT_TOOLS = {
    "recognize_sheet": _recognize_sheet,
    "recognize_sheet_to_file": _recognize_sheet_to_file,
    "recognize_sheets": _recognize_sheets,
    "get_source_preview": _get_source_preview,
}


async def call_tool(name: str, arguments: dict, ctx=None) -> list:
    """The tool's content blocks: what every client sees, structured content aside."""
    return (await call_tool_result(name, arguments, ctx)).content


async def call_tool_result(name: str, arguments: dict, ctx=None) -> CallToolResult:
    """The full result the server sends, ``structuredContent`` and ``isError`` included."""
    if name in _RESULT_TOOLS:
        return await _RESULT_TOOLS[name](arguments, ctx)
    return CallToolResult(content=await _plain_tool(name, arguments, ctx))


async def _plain_tool(name: str, arguments: dict, ctx=None) -> list:
    if name in ("list_capabilities", "list_supported_formats"):
        try:
            from importlib.metadata import version as pkg_version
            backend_version = pkg_version("oemer")
        except Exception:
            backend_version = "unknown"

        _engine_status = _engine_health_check()["checks"].get("audiveris", {})

        result = {
            "server": "omr-mcp",
            "version": __version__,
            "input_formats": list(ext.lstrip(".") for ext in SUPPORTED_IMAGE_FORMATS),
            "output_formats": ["musicxml"],
            "tools": [
                "recognize_sheet",
                "recognize_sheet_to_file",
                "recognize_sheets",
                "list_capabilities",
            ],
            "backend": "oemer",
            "backend_version": backend_version,
            "engines": {
                "oemer": {
                    "status": "ok",
                    "note": "Default engine. Fast; flattens multi-staff (SATB) scores into one part.",
                },
                "audiveris": {
                    "status": _engine_status.get("status", "not_installed"),
                    "note": (
                        "Opt-in via engine=\"audiveris\". Correctly separates SATB scores into "
                        "simultaneous parts. Requires 300+ DPI input; downloads ~80 MB on first use."
                    ),
                },
            },
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "health_check":
        result = _engine_health_check()
        lines = [f"omr-mcp health status: {result['status'].upper()}", ""]
        for dep, info in result["checks"].items():
            if info["status"] == "ok":
                status_icon = "✓"
            elif info["status"] == "not_installed":
                # Optional dependency (e.g. audiveris) in its expected default state — not an error.
                status_icon = "○"
            else:
                status_icon = "✗"
            line = f"  {status_icon} {dep}: {info['status']}"
            if info.get("version"):
                line += f" (v{info['version']})"
            if info.get("path"):
                line += f"\n      path: {info['path']}"
            if info.get("note"):
                line += f"\n      {info['note']}"
            if info.get("error"):
                line += f"\n      error: {info['error']}"
            if info.get("hint"):
                line += f"\n      hint: {info['hint']}"
            lines.append(line)
        return [TextContent(type="text", text="\n".join(lines))]

    raise ValueError(f"Unknown tool: {name}")

class _CurrentUiRegistry:
    """Serves whichever registry ``ui_registry`` holds at request time, so tests can swap it."""

    def list_resources(self):
        return ui_registry.list_resources()

    def read(self, uri: str):
        return ui_registry.read(uri)


_on_list_tools, _on_call_tool = make_handlers(list_tools, call_tool_result, pass_context=True, logger=logger)
_on_list_resources, _on_read_resource = make_resource_handlers(_CurrentUiRegistry(), logger=logger)

app = Server(
    "omr-mcp",
    instructions=INSTRUCTIONS,
    on_list_tools=_on_list_tools,
    on_call_tool=_on_call_tool,
    on_list_resources=_on_list_resources,
    on_read_resource=_on_read_resource,
)


def main():
    """Main entry point for the OMR MCP server."""
    import asyncio

    # Startup banner — visible in the LLM client's server log
    logger.info("omr-mcp: starting OMR MCP server (sheet music → MusicXML)")

    # Quick dependency probe so users see warnings before the first tool call
    from .omr_engine import health_check as _hc
    _status = _hc()
    if _status["status"] == "ok":
        logger.info("omr-mcp: all dependencies OK — ready to accept connections")
    else:
        for dep, info in _status["checks"].items():
            if info["status"] == "not_installed":
                # Optional dependency (audiveris) in its expected default state — not a
                # degraded-state cause, so not worth a startup warning.
                continue
            if info["status"] != "ok":
                if dep == "model_cache":
                    logger.warning(
                        "omr-mcp: oemer model cache not found — on first use, "
                        "oemer will download ~100 MB of model checkpoints "
                        "(this may take 5–10 minutes; subsequent runs are fast)"
                    )
                else:
                    logger.warning(
                        "omr-mcp: dependency '%s' is not available: %s",
                        dep,
                        info.get("error", "unknown error"),
                    )
        logger.info("omr-mcp: server starting in degraded state — some tools may fail")

    async def _run():
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

    asyncio.run(_run())

if __name__ == "__main__":
    main()