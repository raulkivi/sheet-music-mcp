import asyncio
import json
import logging

import mcp.server.stdio
from mcp.server import Server
from mcp.types import TextContent, Tool, ToolAnnotations
from sheet_music_mcp_core.annotations import READ_ONLY, WRITES_FILE
from sheet_music_mcp_core.content import error_content, processing_error_content
from sheet_music_mcp_core.params import aliased
from sheet_music_mcp_core.references import (
    DESCRIBE_SCORE_TOOL,
    RETURN_PROPERTY,
    deliver_score,
    describe_score_tool,
    exactly_one,
    load_score,
    score_input_properties,
)
from sheet_music_mcp_core.wiring import make_handlers

from . import __version__
from .engine import ProcessingError, abc_to_musicxml, health_check, musicxml_to_abc, validate_abc
from .utils import validate_abc_str, validate_musicxml

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Sent to the client at initialize (docs/conventions.md, Server Instructions).
INSTRUCTIONS = (
    "Converts MusicXML to compact ABC notation so you can read or edit a score as text "
    "(musicxml_to_abc, optionally one part) and converts edited ABC back to MusicXML "
    "(abc_to_musicxml). Check edits with validate_abc first. The round trip keeps the notes but "
    "drops dynamics and complex articulations. "
    "Prefer musicxml_path over inline musicxml text, pass on the musicxml_path that "
    "abc_to_musicxml returns for large scores, and use describe_score to learn part IDs cheaply."
)


def _musicxml_input_properties() -> dict:
    """musicxml / musicxml_path, keeping this server's inline description."""
    properties = score_input_properties("musicxml", "musicxml_path", what="the score")
    properties["musicxml"]["description"] = (
        "MusicXML document as a string. Give this or 'musicxml_path', not both."
    )
    return properties


async def list_tools():
    return [
        Tool(
            name="musicxml_to_abc",
            title="MusicXML to ABC",
            annotations=ToolAnnotations(**READ_ONLY),
            description=(
                "Convert a MusicXML document to ABC notation. "
                "ABC is compact and human-readable — ideal for Claude to read and edit scores directly. "
                "Optionally filter to a single part. "
                "Pass the score as musicxml_path (preferred) or as musicxml text."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    **_musicxml_input_properties(),
                    "part": {
                        "type": "string",
                        "description": (
                            "Export only this part: a part ID, name or voice "
                            "(e.g. 'P1', 'Soprano', 'S'). Omit to include all parts."
                        ),
                    },
                    "part_id": {
                        "type": "string",
                        "description": "(Deprecated: use `part`) Export only this part.",
                    },
                },
                **exactly_one("musicxml", "musicxml_path"),
            },
        ),
        Tool(
            name="abc_to_musicxml",
            title="ABC to MusicXML",
            # Writes the score to a file in 'auto' mode when it is large (Wave 2, W2-5).
            annotations=ToolAnnotations(**WRITES_FILE),
            description=(
                "Convert an ABC notation string back to MusicXML. "
                "Use this after Claude has read or edited an ABC score to produce "
                "MusicXML for synthesis or rendering. With return 'auto' (default) a small "
                "score comes back as musicxml text and a large one as musicxml_path plus a "
                "short score_summary; 'inline' always returns the text, 'path' always writes "
                "a file. Pass musicxml_path on to other tools."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "abc": {
                        "type": "string",
                        "description": "ABC notation string",
                    },
                    **RETURN_PROPERTY,
                },
                "required": ["abc"],
            },
        ),
        Tool(
            name="validate_abc",
            title="Validate ABC",
            annotations=ToolAnnotations(**READ_ONLY),
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
            title="ABC capabilities",
            annotations=ToolAnnotations(**READ_ONLY),
            description="List supported formats and available tools for this server",
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="health_check",
            title="ABC health check",
            annotations=ToolAnnotations(**READ_ONLY),
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
        DESCRIBE_SCORE_TOOL,
    ]


async def call_tool(name: str, arguments: dict, ctx=None):
    if name == "musicxml_to_abc":
        try:
            musicxml = await load_score(arguments, ctx)
        except ProcessingError as e:
            return processing_error_content(e)
        ok, err = validate_musicxml(musicxml)
        if not ok:
            return error_content(err, "INVALID_INPUT")

        try:
            part = aliased(arguments, "part", "part_id")  # optional
            result = musicxml_to_abc(musicxml, part)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except ProcessingError as e:
            return processing_error_content(e)
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
            return deliver_score(result, field="musicxml", mode=arguments.get("return"), stem="from-abc")
        except ProcessingError as e:
            return processing_error_content(e)
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
            return processing_error_content(e)
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
            "input_formats": ["musicxml", "mxl", "abc"],
            "output_formats": ["abc", "musicxml"],
            # Scores are taken as inline text or as a .musicxml/.xml/.mxl file path.
            "input_parameters": ["musicxml", "musicxml_path"],
            "tools": [
                "musicxml_to_abc",
                "abc_to_musicxml",
                "validate_abc",
                "list_capabilities",
                "health_check",
                "describe_score",
            ],
            "backend": "music21",
            "backend_version": backend_version,
            "abc_standard": "2.1",
            "notes": (
                "ABC output is generated by a custom serializer (music21 9.x has no ABC writer). "
                "Round-trips preserve notes; dynamics and complex articulations are dropped."
            ),
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "describe_score":
        try:
            return await describe_score_tool(arguments, ctx)
        except ProcessingError as e:
            return processing_error_content(e)

    elif name == "health_check":
        try:
            result = health_check()
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except Exception as e:
            logger.error("health_check unexpected error: %s", e)
            return error_content(f"Unexpected error: {e}", "PROCESSING_FAILED")

    raise ValueError(f"Unknown tool: {name}")


_on_list_tools, _on_call_tool = make_handlers(list_tools, call_tool, pass_context=True, logger=logger)

app = Server(
    "musicxml-abc-mcp",
    instructions=INSTRUCTIONS,
    on_list_tools=_on_list_tools,
    on_call_tool=_on_call_tool,
)


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
        "validate_abc, list_capabilities, health_check, describe_score"
    )

    async def _run():
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
