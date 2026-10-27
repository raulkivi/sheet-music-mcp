import asyncio
import json
import logging

import mcp.server.stdio
from mcp.server import Server
from mcp.types import TextContent, Tool
from sheet_music_mcp_core.content import error_content
from sheet_music_mcp_core.wiring import make_handlers

from . import __version__
from .engine import ProcessingError, abc_to_musicxml, health_check, musicxml_to_abc, validate_abc
from .utils import validate_abc_str, validate_musicxml

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def list_tools():
    return [
        Tool(
            name="musicxml_to_abc",
            description=(
                "Convert a MusicXML document to ABC notation. "
                "ABC is compact and human-readable — ideal for Claude to read and edit scores directly. "
                "Optionally filter to a single part."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "musicxml": {
                        "type": "string",
                        "description": "MusicXML document as a string",
                    },
                    "part_id": {
                        "type": "string",
                        "description": (
                            "Export only this part (e.g. 'Soprano'). "
                            "Omit to include all parts."
                        ),
                    },
                },
                "required": ["musicxml"],
            },
        ),
        Tool(
            name="abc_to_musicxml",
            description=(
                "Convert an ABC notation string back to MusicXML. "
                "Use this after Claude has read or edited an ABC score to produce "
                "MusicXML for synthesis or rendering."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "abc": {
                        "type": "string",
                        "description": "ABC notation string",
                    },
                },
                "required": ["abc"],
            },
        ),
        Tool(
            name="validate_abc",
            description=(
                "Validate an ABC notation string. "
                "Returns whether the ABC is parseable and lists any errors or warnings."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "abc": {
                        "type": "string",
                        "description": "ABC notation string to validate",
                    },
                },
                "required": ["abc"],
            },
        ),
        Tool(
            name="list_capabilities",
            description="List supported formats and available tools for this server",
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="health_check",
            description=(
                "Check that the server and all its dependencies are working correctly. "
                "Runs a short MusicXML → ABC → MusicXML round-trip and returns a "
                "human-readable status summary. Ask your AI assistant to run this tool "
                "to confirm the server is set up correctly."
            ),
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
    ]


async def call_tool(name: str, arguments: dict):
    if name == "musicxml_to_abc":
        musicxml = arguments.get("musicxml", "")
        part_id = arguments.get("part_id")  # optional

        ok, err = validate_musicxml(musicxml)
        if not ok:
            return error_content(err, "INVALID_INPUT")

        try:
            result = musicxml_to_abc(musicxml, part_id)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except ProcessingError as e:
            return error_content(str(e), e.error_code)
        except Exception as e:
            logger.error("musicxml_to_abc unexpected error: %s", e)
            return error_content(f"Unexpected error: {e}", "PROCESSING_FAILED")

    elif name == "abc_to_musicxml":
        abc = arguments.get("abc", "")

        ok, err = validate_abc_str(abc)
        if not ok:
            return error_content(err, "INVALID_INPUT")

        try:
            result = abc_to_musicxml(abc)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except ProcessingError as e:
            return error_content(str(e), e.error_code)
        except Exception as e:
            logger.error("abc_to_musicxml unexpected error: %s", e)
            return error_content(f"Unexpected error: {e}", "PROCESSING_FAILED")

    elif name == "validate_abc":
        abc = arguments.get("abc", "")
        # validate_abc handles empty string itself
        try:
            result = validate_abc(abc)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except ProcessingError as e:
            return error_content(str(e), e.error_code)
        except Exception as e:
            logger.error("validate_abc unexpected error: %s", e)
            return error_content(f"Unexpected error: {e}", "PROCESSING_FAILED")

    elif name == "list_capabilities":
        backend_version = "unknown"
        try:
            import music21
            backend_version = music21.__version__
        except ImportError:
            pass

        result = {
            "server": "musicxml-abc-mcp",
            "version": __version__,
            "input_formats": ["musicxml", "abc"],
            "output_formats": ["abc", "musicxml"],
            "tools": ["musicxml_to_abc", "abc_to_musicxml", "validate_abc", "list_capabilities", "health_check"],
            "backend": "music21",
            "backend_version": backend_version,
            "abc_standard": "2.1",
            "notes": (
                "ABC output is generated by a custom serializer (music21 9.x has no ABC writer). "
                "Round-trips preserve notes; dynamics and complex articulations are dropped."
            ),
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "health_check":
        try:
            result = health_check()
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except Exception as e:
            logger.error("health_check unexpected error: %s", e)
            return error_content(f"Unexpected error: {e}", "PROCESSING_FAILED")

    raise ValueError(f"Unknown tool: {name}")


_on_list_tools, _on_call_tool = make_handlers(list_tools, call_tool, logger=logger)

app = Server("musicxml-abc-mcp", on_list_tools=_on_list_tools, on_call_tool=_on_call_tool)


def main():
    """Entry point for musicxml-abc-mcp."""
    logger.info("musicxml-abc-mcp starting…")

    try:
        import music21
        logger.info("music21 %s ready", music21.__version__)
    except ImportError:
        logger.warning(
            "music21 is not installed — all conversion tools will fail. "
            "Run: uv sync --extra dev"
        )

    logger.info(
        "musicxml-abc-mcp ready. Tools: musicxml_to_abc, abc_to_musicxml, "
        "validate_abc, list_capabilities, health_check"
    )

    async def _run():
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
