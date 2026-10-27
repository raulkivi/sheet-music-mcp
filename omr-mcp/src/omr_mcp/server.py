import mcp.server.stdio
from mcp.server import Server
from mcp.types import TextContent, Tool, ToolAnnotations
from sheet_music_mcp_core.annotations import READ_ONLY, READ_ONLY_DOWNLOADS, WRITES_FILE_DOWNLOADS
from sheet_music_mcp_core.content import error_content, file_link
from sheet_music_mcp_core.wiring import make_handlers
import asyncio
import json
import logging
import os
import time

from . import __version__
from .omr_engine import recognize_image, recognize_image_to_file, recognize_images, health_check as _engine_health_check
from .utils import decode_base64_image, SUPPORTED_IMAGE_FORMATS

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Sent to the client at initialize (docs/conventions.md, Server Instructions).
INSTRUCTIONS = (
    "Converts photos or scans of printed sheet music (PNG or JPEG) to MusicXML. "
    "For choir (SATB, multi-staff) scores use engine='audiveris' with 300+ DPI images; the default "
    "oemer engine merges the staves into one part. recognize_sheets merges several pages into one score. "
    "First use downloads models (oemer ~100 MB, Audiveris ~80 MB) and a page can take minutes."
)

MUSICXML_MIME_TYPE = "application/vnd.recordare.musicxml+xml"


async def list_tools():
    return [
        Tool(
            name="recognize_sheet",
            title="Recognize sheet music",
            annotations=ToolAnnotations(**READ_ONLY_DOWNLOADS),
            description="Recognize music notation from an image and return MusicXML",
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
                    }
                },
                "required": ["image"]
            }
        ),
        Tool(
            name="recognize_sheet_to_file",
            title="Recognize sheet music to file",
            annotations=ToolAnnotations(**WRITES_FILE_DOWNLOADS),
            description="Process sheet music image and save MusicXML result to filesystem",
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
            annotations=ToolAnnotations(**READ_ONLY_DOWNLOADS),
            description="Process multiple pages of sheet music in order and return a single merged MusicXML",
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
                    }
                },
                "required": ["images"]
            }
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

async def call_tool(name: str, arguments: dict, ctx=None):
    if name == "recognize_sheet":
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
                    return error_content(path_or_error, "INVALID_INPUT")
                image_path = path_or_error
            else:
                image_path = image

            result = await _run_with_progress(
                recognize_image, image_path, engine=engine, ctx=ctx, message_prefix="Running OMR recognition"
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except Exception as e:
            logger.error(f"Error processing image: {str(e)}")
            return error_content(f"Failed to process image: {str(e)}", "PROCESSING_FAILED")

    elif name == "recognize_sheet_to_file":
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
            content = [TextContent(type="text", text=json.dumps(result, indent=2))]
            # docs/conventions.md, Result Content. The engine returns (not raises) error dicts.
            written = result.get("output_path") if "error" not in result else None
            if written and os.path.isfile(written):
                content.append(file_link(written, MUSICXML_MIME_TYPE))
            return content
        except Exception as e:
            logger.error(f"Error processing image: {str(e)}")
            return error_content(f"Failed to process image: {str(e)}", "PROCESSING_FAILED")
    
    elif name == "recognize_sheets":
        images = arguments.get("images", [])
        engine = arguments.get("engine", "oemer")
        if not isinstance(images, list):
            return error_content("'images' must be a list", "INVALID_PARAMETER")

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
            return error_content(resolution_error, "INVALID_INPUT")

        try:
            result = await _run_with_progress(
                recognize_images,
                resolved_paths,
                engine=engine,
                ctx=ctx,
                message_prefix=f"Running OMR recognition on {len(resolved_paths)} page(s)",
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except Exception as e:
            logger.error(f"Error processing images: {str(e)}")
            return error_content(f"Failed to process images: {str(e)}", "PROCESSING_FAILED")

    elif name in ("list_capabilities", "list_supported_formats"):
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

_on_list_tools, _on_call_tool = make_handlers(list_tools, call_tool, pass_context=True, logger=logger)

app = Server(
    "omr-mcp",
    instructions=INSTRUCTIONS,
    on_list_tools=_on_list_tools,
    on_call_tool=_on_call_tool,
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