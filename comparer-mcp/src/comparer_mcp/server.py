import asyncio
import json
import logging

import mcp.server.stdio
from mcp.server import Server
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations
from sheet_music_mcp_core.annotations import READ_ONLY, WRITES_FILE
from sheet_music_mcp_core.content import error_content, processing_error_content
from sheet_music_mcp_core.measures import MEASURES_PROPERTY, parse_range
from sheet_music_mcp_core.params import aliased
from sheet_music_mcp_core.parts import PartInfo, resolve_parts
from sheet_music_mcp_core.references import (
    DESCRIBE_SCORE_TOOL,
    RETURN_PROPERTY,
    deliver_score,
    describe_score_tool,
)
from sheet_music_mcp_core.ui import PackageAssetSource, UiRegistry, UiResource
from sheet_music_mcp_core.wiring import make_handlers, make_resource_handlers

from . import __version__
from .annotator import annotate
from .engine import ProcessingError, compare, health_check
from .presenter import (
    COMPARISON_OUTPUT_SCHEMA,
    REPORT_OUTPUT_SCHEMA,
    present_comparison,
    present_report,
)
from .report import generate_report
from .score_inputs import INPUT_PARAMETERS, load_pair, pair_schema

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_OPTIONS_SCHEMA = {
    "type": "object",
    "description": (
        "Comparison options (docs/architecture.md §8). expand_repeats defaults to "
        "false (opt-in — see docs/PLAN.md 'Changed decisions'); normalize_pitch, "
        "ignore_articulations, parts, measures all default to off/unset."
    ),
    "properties": {
        "expand_repeats": {"type": "boolean"},
        "normalize_pitch": {"type": "boolean"},
        "ignore_articulations": {"type": "boolean"},
        "parts": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Compare only these parts: part IDs, names or voices (e.g. 'P1', 'Soprano', 'S').",
        },
        "part_filter": {
            "type": "array",
            "items": {"type": "string"},
            "description": "(Deprecated: use `parts`) Compare only these parts.",
        },
        # Filters the differences by measure number; the scores are not cut (wave 3 plan §3.4).
        **MEASURES_PROPERTY,
        "measure_range": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "(Deprecated: use `measures`) Inclusive [start, end] measure numbers.",
        },
    },
}


# Sent to the client at initialize (docs/conventions.md, Server Instructions).
INSTRUCTIONS = (
    "Music-aware comparison of two MusicXML scores (reference and target). Use quick_similarity "
    "for a 0-1 score, list_changes for targeted questions (one part, a range of measures), "
    "generate_comparison_report for a readable summary and export_annotated_musicxml for "
    "color-marked scores to render. compare_musicxml returns the full structured diff, which can "
    "be large. Prefer reference_path and target_path over inline reference_xml and target_xml, "
    "pass on the paths other tools return (export_annotated_musicxml returns paths for large "
    "scores), and use describe_score to learn part IDs cheaply. options.measures (list_changes: "
    "measures) limits the differences to [start, end] measure numbers without cutting the scores."
)


DIFF_VIEWER = UiResource(
    "ui://comparer/diff-viewer",
    "diff-viewer.html",
    "Diff Viewer",
    "Shows two scores side by side with their differences marked, a filterable change list and the report.",
)

# Reads the HTML packaged under comparer_mcp/ui/assets/; tests replace ui_registry with in-memory
# assets. Without a UI build the viewer is hidden and the tools carry no _meta.ui.
DEFAULT_UI_REGISTRY = UiRegistry([DIFF_VIEWER], PackageAssetSource("comparer_mcp"))
ui_registry = DEFAULT_UI_REGISTRY


async def list_tools():
    return [
        Tool(
            name="compare_musicxml",
            title="Compare scores",
            annotations=ToolAnnotations(**READ_ONLY),
            description=(
                "Full music-aware diff of two MusicXML scores, given inline or as file paths. "
                "Returns a structured "
                "ComparisonResult with global similarity score, summary statistics, and "
                "per-part/measure/note detail."
            ),
            input_schema=pair_schema({"options": _OPTIONS_SCHEMA}),
            output_schema=COMPARISON_OUTPUT_SCHEMA,
            meta=ui_registry.meta_for(DIFF_VIEWER),
        ),
        Tool(
            name="compare_musicxml_files",
            title="Compare score files",
            annotations=ToolAnnotations(**READ_ONLY),
            description=(
                "Full music-aware diff of two MusicXML files on disk (.musicxml, .xml, or "
                "compressed .mxl). Returns the same structured ComparisonResult as "
                "compare_musicxml. Files must be inside the allowed folders (the output folder, "
                "the client's roots or SHEET_MUSIC_INPUT_ROOTS)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "reference_path": {
                        "type": "string",
                        "description": "Path to the reference MusicXML/.mxl file",
                    },
                    "target_path": {
                        "type": "string",
                        "description": "Path to the target MusicXML/.mxl file, compared against the reference",
                    },
                    "options": _OPTIONS_SCHEMA,
                },
                "required": ["reference_path", "target_path"],
            },
            output_schema=COMPARISON_OUTPUT_SCHEMA,
            meta=ui_registry.meta_for(DIFF_VIEWER),
        ),
        Tool(
            name="quick_similarity",
            title="Score similarity",
            annotations=ToolAnnotations(**READ_ONLY),
            description=(
                "Fast similarity check between two MusicXML strings: returns only the "
                "0.0-1.0 similarity score and summary statistics, without per-note detail."
            ),
            input_schema=pair_schema(),
        ),
        Tool(
            name="list_changes",
            title="List score changes",
            annotations=ToolAnnotations(**READ_ONLY),
            description=(
                "List only the note-level differences (operation != MATCH) between two "
                "MusicXML strings, optionally filtered to one part and/or a measure range. "
                "Useful for targeted queries like 'what changed in the Alto, measures 17-24?'"
            ),
            input_schema=pair_schema(
                {
                    "part": {
                        "type": "string",
                        "description": "Restrict results to this part: a part ID, name or voice (e.g. 'P1', 'Alto', 'A'). Omit for all parts.",
                    },
                    **MEASURES_PROPERTY,
                    "measure_range": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 2,
                        "maxItems": 2,
                        "description": "(Deprecated: use `measures`) [start, end] measure numbers, inclusive.",
                    },
                }
            ),
        ),
        Tool(
            name="generate_comparison_report",
            title="Comparison report",
            annotations=ToolAnnotations(**READ_ONLY),
            description=(
                "Human-readable version comparison report: overall similarity headline, "
                "missing/extra parts, missing/extra measures, key/time signature changes, "
                "and note-level differences grouped into measure-range summaries (e.g. "
                "'transposed by 3 semitones in measures 17-24')."
            ),
            input_schema=pair_schema({"options": _OPTIONS_SCHEMA}),
            output_schema=REPORT_OUTPUT_SCHEMA,
            meta=ui_registry.meta_for(DIFF_VIEWER),
        ),
        Tool(
            name="export_annotated_musicxml",
            title="Export color-annotated diff",
            annotations=ToolAnnotations(**WRITES_FILE),
            description=(
                "Export both scores as MusicXML with per-note color annotations marking "
                "the diff (pitch changes, duration changes, substitutions, insertions, "
                "deletions): the reference shows deletions and pre-change values, the target "
                "insertions and post-change values. Small results come back inline as "
                "reference_annotated_musicxml and target_annotated_musicxml; large ones "
                "(return: 'auto', the default) are written to files and returned as "
                "reference_annotated_musicxml_path and target_annotated_musicxml_path plus a "
                "score_summary. Feed the returned paths to render-mcp's render_to_pdf or "
                "render_to_image as musicxml_path to visualize the diff."
            ),
            input_schema=pair_schema({"options": _OPTIONS_SCHEMA, **RETURN_PROPERTY}),
        ),
        Tool(
            name="list_capabilities",
            title="Comparer capabilities",
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
            title="Comparer health check",
            annotations=ToolAnnotations(**READ_ONLY),
            description=(
                "Check that the server and all its dependencies are working correctly. "
                "Runs a self-comparison smoke test and returns a structured status summary. "
                "Ask your AI assistant to run this tool to confirm the server is set up correctly."
            ),
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        DESCRIBE_SCORE_TOOL,
    ]


def _filter_changes(result, part, measures) -> list[dict]:
    wanted = None
    if part:
        # ID, name or voice, resolved against the compared parts by their stable reference IDs
        compared = [PartInfo(pd.reference_part_id, pd.part_name) for pd in result.part_diffs]
        wanted = set(resolve_parts([part], compared))
    changes = []
    for part_diff in result.part_diffs:
        if wanted is not None and part_diff.reference_part_id not in wanted:
            continue
        for measure_diff in part_diff.measure_diffs:
            if measures and not (measures[0] <= measure_diff.measure_number <= measures[1]):
                continue
            for note_diff in measure_diff.note_diffs:
                if note_diff.operation == "MATCH":
                    continue
                entry = note_diff.to_dict()
                entry["part_name"] = part_diff.part_name
                changes.append(entry)
    return changes


def _error(message: str, code: str) -> CallToolResult:
    # isError, so clients skip output_schema validation of the absent structured content.
    return CallToolResult(content=error_content(message, code), is_error=True)


def _processing_error(error: ProcessingError) -> CallToolResult:
    return CallToolResult(content=processing_error_content(error), is_error=True)


def _result(presented: tuple[list, dict]) -> CallToolResult:
    content, structured = presented
    return CallToolResult(content=content, structured_content=structured)


async def call_tool(name: str, arguments: dict, ctx=None) -> list:
    """The tool's text content blocks; ``call_tool_result`` also carries structuredContent."""
    return (await call_tool_result(name, arguments, ctx)).content


async def call_tool_result(name: str, arguments: dict, ctx=None) -> CallToolResult:
    result = await _dispatch(name, arguments, ctx)
    return result if isinstance(result, CallToolResult) else CallToolResult(content=result)


async def _dispatch(name: str, arguments: dict, ctx=None):
    if name == "compare_musicxml":
        options = arguments.get("options")

        try:
            reference_xml, target_xml = await load_pair(arguments, ctx)
        except ProcessingError as e:
            return _processing_error(e)

        try:
            result = compare(reference_xml, target_xml, options)
            return _result(present_comparison(result))
        except ProcessingError as e:
            return _processing_error(e)
        except Exception as e:
            logger.error("compare_musicxml unexpected error: %s", e)
            return _error(f"Unexpected error: {e}", "PROCESSING_FAILED")

    elif name == "compare_musicxml_files":
        reference_path = arguments.get("reference_path", "")
        target_path = arguments.get("target_path", "")
        options = arguments.get("options")

        if not reference_path:
            return _error("reference_path is required.", "INVALID_PARAMETER")
        if not target_path:
            return _error("target_path is required.", "INVALID_PARAMETER")

        try:
            # Same read policy as every score path (plan decision W2-2), then the text engine:
            # compare_files() gives the same result for the same content (.mxl included).
            reference_xml, target_xml = await load_pair(arguments, ctx)
            result = compare(reference_xml, target_xml, options)
            return _result(present_comparison(result))
        except ProcessingError as e:
            return _processing_error(e)
        except Exception as e:
            logger.error("compare_musicxml_files unexpected error: %s", e)
            return _error(f"Unexpected error: {e}", "PROCESSING_FAILED")

    elif name == "quick_similarity":

        try:
            reference_xml, target_xml = await load_pair(arguments, ctx)
        except ProcessingError as e:
            return _processing_error(e)

        try:
            result = compare(reference_xml, target_xml)
            payload = {
                "similarity_score": result.similarity_score,
                "summary": result.summary.to_dict(),
            }
            return [TextContent(type="text", text=json.dumps(payload, indent=2))]
        except ProcessingError as e:
            return _processing_error(e)
        except Exception as e:
            logger.error("quick_similarity unexpected error: %s", e)
            return _error(f"Unexpected error: {e}", "PROCESSING_FAILED")

    elif name == "list_changes":
        part = arguments.get("part")

        try:
            reference_xml, target_xml = await load_pair(arguments, ctx)
            measures = parse_range(aliased(arguments, "measures", "measure_range"))
        except ProcessingError as e:
            return _processing_error(e)

        try:
            result = compare(reference_xml, target_xml)
            changes = _filter_changes(result, part, measures)
            payload = {"changes": changes, "count": len(changes)}
            return [TextContent(type="text", text=json.dumps(payload, indent=2))]
        except ProcessingError as e:
            return _processing_error(e)
        except Exception as e:
            logger.error("list_changes unexpected error: %s", e)
            return _error(f"Unexpected error: {e}", "PROCESSING_FAILED")

    elif name == "generate_comparison_report":
        options = arguments.get("options")

        try:
            reference_xml, target_xml = await load_pair(arguments, ctx)
        except ProcessingError as e:
            return _processing_error(e)

        try:
            result = compare(reference_xml, target_xml, options)
            payload = {"report": generate_report(result), "similarity_score": result.similarity_score}
            return _result(present_report(payload))
        except ProcessingError as e:
            return _processing_error(e)
        except Exception as e:
            logger.error("generate_comparison_report unexpected error: %s", e)
            return _error(f"Unexpected error: {e}", "PROCESSING_FAILED")

    elif name == "export_annotated_musicxml":
        options = arguments.get("options")

        try:
            reference_xml, target_xml = await load_pair(arguments, ctx)
        except ProcessingError as e:
            return _processing_error(e)

        try:
            payload = annotate(reference_xml, target_xml, options)
            return deliver_score(
                payload,
                field=("reference_annotated_musicxml", "target_annotated_musicxml"),
                mode=arguments.get("return"),
                stem="annotated",
            )
        except ProcessingError as e:
            return _processing_error(e)
        except Exception as e:
            logger.error("export_annotated_musicxml unexpected error: %s", e)
            return _error(f"Unexpected error: {e}", "PROCESSING_FAILED")

    elif name == "list_capabilities":
        backend_version = "unknown"
        try:
            import music21
            backend_version = music21.__version__
        except ImportError:
            pass

        result = {
            "server": "comparer-mcp",
            "version": __version__,
            "input_formats": ["musicxml", "mxl"],
            "input_parameters": INPUT_PARAMETERS,
            "output_formats": ["json"],
            "tools": [
                "compare_musicxml",
                "compare_musicxml_files",
                "quick_similarity",
                "list_changes",
                "generate_comparison_report",
                "export_annotated_musicxml",
                "list_capabilities",
                "health_check",
                "describe_score",
            ],
            "backend": "music21",
            "backend_version": backend_version,
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "describe_score":
        try:
            return await describe_score_tool(arguments, ctx)
        except ProcessingError as e:
            return _processing_error(e)

    elif name == "health_check":
        try:
            result = health_check()
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except Exception as e:
            logger.error("health_check unexpected error: %s", e)
            return _error(f"Unexpected error: {e}", "PROCESSING_FAILED")

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
    "comparer-mcp",
    instructions=INSTRUCTIONS,
    on_list_tools=_on_list_tools,
    on_call_tool=_on_call_tool,
    on_list_resources=_on_list_resources,
    on_read_resource=_on_read_resource,
)


def main():
    """Entry point for comparer-mcp."""
    logger.info("comparer-mcp starting…")

    try:
        import music21
        logger.info("music21 %s ready", music21.__version__)
    except ImportError:
        logger.warning(
            "music21 is not installed — all comparison tools will fail. Run: uv sync"
        )

    logger.info(
        "comparer-mcp ready. Tools: compare_musicxml, compare_musicxml_files, "
        "quick_similarity, list_changes, generate_comparison_report, "
        "export_annotated_musicxml, list_capabilities, health_check, describe_score"
    )

    async def _run():
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
