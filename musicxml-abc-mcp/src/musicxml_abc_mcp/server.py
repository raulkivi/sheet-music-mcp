import asyncio
import json
import logging

import mcp.server.stdio
from mcp.server import Server
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations
from sheet_music_mcp_core.annotations import READ_ONLY, WRITES_FILE
from sheet_music_mcp_core.content import error_content, processing_error_content
from sheet_music_mcp_core.health import HEALTH_OUTPUT_SCHEMA, setup_doctor_resource
from sheet_music_mcp_core.measures import MEASURES_PROPERTY
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
from sheet_music_mcp_core.ui import PackageAssetSource, UiRegistry, UiResource
from sheet_music_mcp_core.wiring import make_handlers, make_resource_handlers

from . import __version__
from .abc_store import AbcStore
from .engine import ProcessingError, abc_to_musicxml, health_check, musicxml_to_abc, validate_abc
from .health import build_health_report
from .presenter import (
    ABC_OUTPUT_SCHEMA,
    CONVERSION_OUTPUT_SCHEMA,
    VALIDATION_OUTPUT_SCHEMA,
    present_abc,
    present_conversion,
    present_stored_abc,
    present_validation,
)
from .utils import validate_abc_str, validate_musicxml

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Sent to the client at initialize (docs/conventions.md, Server Instructions).
INSTRUCTIONS = (
    "Converts MusicXML to compact ABC notation so you can read or edit a score as text "
    "(musicxml_to_abc, optionally one part) and converts edited ABC back to MusicXML "
    "(abc_to_musicxml). Check edits with validate_abc first. The round trip keeps the notes but "
    "drops dynamics and complex articulations. "
    "Pass measures [start, end] (printed bar numbers, pickup 0) to musicxml_to_abc to export only "
    "those bars. "
    "Prefer musicxml_path over inline musicxml text, pass on the musicxml_path that "
    "abc_to_musicxml returns for large scores, and use describe_score to learn part IDs cheaply."
)

ABC_WORKBENCH = UiResource(
    "ui://abc/workbench",
    "abc-workbench.html",
    "ABC Workbench",
    "Shows the model's ABC edit against the original, validates ABC as you type, and converts the accepted text to MusicXML.",
)

# The Setup Doctor renders health_check's structuredContent (docs/conventions.md: Health Reports).
SETUP_DOCTOR = setup_doctor_resource("abc")

# Reads the HTML packaged under musicxml_abc_mcp/ui/assets/; tests replace ui_registry with
# in-memory assets. Without a UI build the apps are hidden and the tools carry no _meta.ui.
DEFAULT_UI_REGISTRY = UiRegistry([ABC_WORKBENCH, SETUP_DOCTOR], PackageAssetSource("musicxml_abc_mcp"))
ui_registry = DEFAULT_UI_REGISTRY

# The ABC each musicxml_to_abc call produced, so the workbench can show it as the "original".
abc_store = AbcStore()


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
                "Optionally filter to a single part and to a range of printed bars (measures). "
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
                    **MEASURES_PROPERTY,
                },
                **exactly_one("musicxml", "musicxml_path"),
            },
            output_schema=ABC_OUTPUT_SCHEMA,
            meta=ui_registry.meta_for(ABC_WORKBENCH),
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
            output_schema=CONVERSION_OUTPUT_SCHEMA,
            meta=ui_registry.meta_for(ABC_WORKBENCH),
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
            output_schema=VALIDATION_OUTPUT_SCHEMA,
        ),
        Tool(
            name="get_abc",
            title="ABC of an export",
            annotations=ToolAnnotations(**READ_ONLY),
            description=(
                "For the ABC Workbench app only: the ABC an earlier musicxml_to_abc call "
                "returned, so the app can show it as the original next to the model's edit. "
                "Takes an abc_id (omit it for the latest export), never a path."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "abc_id": {"type": "string", "description": "abc_id from musicxml_to_abc"},
                },
                "additionalProperties": False,
            },
            output_schema=ABC_OUTPUT_SCHEMA,
            meta=ui_registry.meta_for(ABC_WORKBENCH, app_only=True),
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
            output_schema=HEALTH_OUTPUT_SCHEMA,
            meta=ui_registry.meta_for(SETUP_DOCTOR),
        ),
        DESCRIBE_SCORE_TOOL,
    ]


def _error(content: list) -> CallToolResult:
    # isError, so clients skip output_schema validation of the absent structured content.
    return CallToolResult(content=content, is_error=True)


def _result(presented: tuple[list, dict]) -> CallToolResult:
    content, structured = presented
    return CallToolResult(content=content, structured_content=structured)


async def _musicxml_to_abc(arguments: dict, ctx) -> CallToolResult:
    try:
        musicxml = await load_score(arguments, ctx)
    except ProcessingError as e:
        return _error(processing_error_content(e))
    ok, err = validate_musicxml(musicxml)
    if not ok:
        return _error(error_content(err, "INVALID_INPUT"))

    try:
        part = aliased(arguments, "part", "part_id")  # optional
        result = musicxml_to_abc(musicxml, part, arguments.get("measures"))
        # Remembered for every client: the id is cheap, and only the app ever asks for it.
        return _result(present_abc(result, abc_store.put(result)))
    except ProcessingError as e:
        return _error(processing_error_content(e))
    except Exception as e:
        logger.error("musicxml_to_abc unexpected error: %s", e)
        return _error(error_content(f"Unexpected error: {e}", "PROCESSING_FAILED"))


async def _abc_to_musicxml(arguments: dict, ctx) -> CallToolResult:
    abc = arguments.get("abc", "")

    ok, err = validate_abc_str(abc)
    if not ok:
        return _error(error_content(err, "INVALID_INPUT"))

    try:
        result = abc_to_musicxml(abc)
        content = deliver_score(result, field="musicxml", mode=arguments.get("return"), stem="from-abc")
        return _result(present_conversion(content, result))
    except ProcessingError as e:
        return _error(processing_error_content(e))
    except Exception as e:
        logger.error("abc_to_musicxml unexpected error: %s", e)
        return _error(error_content(f"Unexpected error: {e}", "PROCESSING_FAILED"))


async def _validate_abc(arguments: dict, ctx) -> CallToolResult:
    # validate_abc handles an empty string itself
    try:
        return _result(present_validation(validate_abc(arguments.get("abc", ""))))
    except ProcessingError as e:
        return _error(processing_error_content(e))
    except Exception as e:
        logger.error("validate_abc unexpected error: %s", e)
        return _error(error_content(f"Unexpected error: {e}", "PROCESSING_FAILED"))


async def _get_abc(arguments: dict, ctx) -> CallToolResult:
    try:
        abc_id, stored = abc_store.fetch(arguments.get("abc_id"))
        return _result(present_stored_abc(stored, abc_id))
    except ProcessingError as e:
        return _error(processing_error_content(e))
    except Exception as e:
        logger.error("get_abc unexpected error: %s", e)
        return _error(error_content(f"Unexpected error: {e}", "PROCESSING_FAILED"))


_RESULT_TOOLS = {
    "musicxml_to_abc": _musicxml_to_abc,
    "abc_to_musicxml": _abc_to_musicxml,
    "validate_abc": _validate_abc,
    "get_abc": _get_abc,
}


async def call_tool(name: str, arguments: dict, ctx=None) -> list:
    """The tool's content blocks: what every client sees, structured content aside."""
    return (await call_tool_result(name, arguments, ctx)).content


async def call_tool_result(name: str, arguments: dict, ctx=None) -> CallToolResult:
    """The full result the server sends, ``structuredContent`` included."""
    if name in _RESULT_TOOLS:
        return await _RESULT_TOOLS[name](arguments, ctx)
    result = await _plain_tool(name, arguments, ctx)
    # health_check returns a full result (it carries structured content); the others return blocks.
    return result if isinstance(result, CallToolResult) else CallToolResult(content=result)


async def _plain_tool(name: str, arguments: dict, ctx) -> list:
    """Tools without structured content: content blocks only (health_check returns a full result)."""
    if name == "list_capabilities":
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
            # Scores are taken as inline text or as a .musicxml/.xml/.mxl file path;
            # musicxml_to_abc can export a range of printed bars (measures).
            "input_parameters": ["musicxml", "musicxml_path", "measures"],
            "tools": [
                "musicxml_to_abc",
                "abc_to_musicxml",
                "validate_abc",
                "list_capabilities",
                "health_check",
                "describe_score",
                "get_abc",
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
            raw = health_check()
            # structuredContent is derived from the raw dict; the text stays byte-identical.
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(raw, indent=2))],
                structured_content=build_health_report(raw),
            )
        except Exception as e:
            logger.error("health_check unexpected error: %s", e)
            return _error(error_content(f"Unexpected error: {e}", "PROCESSING_FAILED"))

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
    "musicxml-abc-mcp",
    instructions=INSTRUCTIONS,
    on_list_tools=_on_list_tools,
    on_call_tool=_on_call_tool,
    on_list_resources=_on_list_resources,
    on_read_resource=_on_read_resource,
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
        "validate_abc, list_capabilities, health_check, describe_score (app-only: get_abc)"
    )

    async def _run():
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
