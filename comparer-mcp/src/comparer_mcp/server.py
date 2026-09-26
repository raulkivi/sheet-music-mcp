import asyncio
import json
import logging

import jsonschema
import mcp.server.stdio
from mcp.server import Server
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, TextContent, Tool

from . import __version__
from .annotator import annotate
from .engine import ProcessingError, compare, compare_files, health_check
from .report import generate_report
from .utils import validate_musicxml

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_OPTIONS_SCHEMA = {
    "type": "object",
    "description": (
        "Comparison options (docs/architecture.md §8). expand_repeats defaults to "
        "false (opt-in — see docs/PLAN.md 'Changed decisions'); normalize_pitch, "
        "ignore_articulations, part_filter, measure_range all default to off/unset."
    ),
    "properties": {
        "expand_repeats": {"type": "boolean"},
        "normalize_pitch": {"type": "boolean"},
        "ignore_articulations": {"type": "boolean"},
        "part_filter": {"type": "array", "items": {"type": "string"}},
        "measure_range": {"type": "array", "items": {"type": "integer"}},
    },
}


async def list_tools():
    return [
        Tool(
            name="compare_musicxml",
            description=(
                "Full music-aware diff of two MusicXML strings. Returns a structured "
                "ComparisonResult with global similarity score, summary statistics, and "
                "per-part/measure/note detail."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "reference_xml": {
                        "type": "string",
                        "description": "Reference MusicXML document as a string",
                    },
                    "target_xml": {
                        "type": "string",
                        "description": "Target MusicXML document as a string, compared against the reference",
                    },
                    "options": _OPTIONS_SCHEMA,
                },
                "required": ["reference_xml", "target_xml"],
            },
        ),
        Tool(
            name="compare_musicxml_files",
            description=(
                "Full music-aware diff of two MusicXML files on disk (.musicxml, .xml, or "
                "compressed .mxl). Returns the same structured ComparisonResult as "
                "compare_musicxml."
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
        ),
        Tool(
            name="quick_similarity",
            description=(
                "Fast similarity check between two MusicXML strings: returns only the "
                "0.0-1.0 similarity score and summary statistics, without per-note detail."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "reference_xml": {
                        "type": "string",
                        "description": "Reference MusicXML document as a string",
                    },
                    "target_xml": {
                        "type": "string",
                        "description": "Target MusicXML document as a string, compared against the reference",
                    },
                },
                "required": ["reference_xml", "target_xml"],
            },
        ),
        Tool(
            name="list_changes",
            description=(
                "List only the note-level differences (operation != MATCH) between two "
                "MusicXML strings, optionally filtered to one part and/or a measure range. "
                "Useful for targeted queries like 'what changed in the Alto, measures 17-24?'"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "reference_xml": {
                        "type": "string",
                        "description": "Reference MusicXML document as a string",
                    },
                    "target_xml": {
                        "type": "string",
                        "description": "Target MusicXML document as a string, compared against the reference",
                    },
                    "part": {
                        "type": "string",
                        "description": "Restrict results to this part name (case-insensitive). Omit for all parts.",
                    },
                    "measure_range": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 2,
                        "maxItems": 2,
                        "description": "[start, end] measure numbers, inclusive. Omit for all measures.",
                    },
                },
                "required": ["reference_xml", "target_xml"],
            },
        ),
        Tool(
            name="generate_comparison_report",
            description=(
                "Human-readable version comparison report: overall similarity headline, "
                "missing/extra parts, missing/extra measures, key/time signature changes, "
                "and note-level differences grouped into measure-range summaries (e.g. "
                "'transposed by 3 semitones in measures 17-24')."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "reference_xml": {
                        "type": "string",
                        "description": "Reference MusicXML document as a string",
                    },
                    "target_xml": {
                        "type": "string",
                        "description": "Target MusicXML document as a string, compared against the reference",
                    },
                    "options": _OPTIONS_SCHEMA,
                },
                "required": ["reference_xml", "target_xml"],
            },
        ),
        Tool(
            name="export_annotated_musicxml",
            description=(
                "Export both scores as MusicXML with per-note color annotations marking "
                "the diff (pitch changes, duration changes, substitutions, insertions, "
                "deletions). Returns two documents: reference_annotated_musicxml (shows "
                "deletions and pre-change values) and target_annotated_musicxml (shows "
                "insertions and post-change values). Feed either directly into render-mcp's "
                "render_to_pdf or render_to_image to visualize the diff — both take a raw "
                "musicxml string."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "reference_xml": {
                        "type": "string",
                        "description": "Reference MusicXML document as a string",
                    },
                    "target_xml": {
                        "type": "string",
                        "description": "Target MusicXML document as a string, compared against the reference",
                    },
                    "options": _OPTIONS_SCHEMA,
                },
                "required": ["reference_xml", "target_xml"],
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
                "Runs a self-comparison smoke test and returns a structured status summary. "
                "Ask your AI assistant to run this tool to confirm the server is set up correctly."
            ),
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
    ]


def _error(message: str, code: str) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps({"error": message, "error_code": code}))]


def _filter_changes(result, part, measure_range) -> list[dict]:
    changes = []
    for part_diff in result.part_diffs:
        if part and part_diff.part_name.lower() != part.lower():
            continue
        for measure_diff in part_diff.measure_diffs:
            if measure_range and not (
                measure_range[0] <= measure_diff.measure_number <= measure_range[1]
            ):
                continue
            for note_diff in measure_diff.note_diffs:
                if note_diff.operation == "MATCH":
                    continue
                entry = note_diff.to_dict()
                entry["part_name"] = part_diff.part_name
                changes.append(entry)
    return changes


async def call_tool(name: str, arguments: dict):
    if name == "compare_musicxml":
        reference_xml = arguments.get("reference_xml", "")
        target_xml = arguments.get("target_xml", "")
        options = arguments.get("options")

        ok, err = validate_musicxml(reference_xml)
        if not ok:
            return _error(f"reference_xml: {err}", "INVALID_INPUT")
        ok, err = validate_musicxml(target_xml)
        if not ok:
            return _error(f"target_xml: {err}", "INVALID_INPUT")

        try:
            result = compare(reference_xml, target_xml, options)
            return [TextContent(type="text", text=json.dumps(result.to_dict(), indent=2))]
        except ProcessingError as e:
            return _error(str(e), e.error_code)
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
            result = compare_files(reference_path, target_path, options)
            return [TextContent(type="text", text=json.dumps(result.to_dict(), indent=2))]
        except ProcessingError as e:
            return _error(str(e), e.error_code)
        except Exception as e:
            logger.error("compare_musicxml_files unexpected error: %s", e)
            return _error(f"Unexpected error: {e}", "PROCESSING_FAILED")

    elif name == "quick_similarity":
        reference_xml = arguments.get("reference_xml", "")
        target_xml = arguments.get("target_xml", "")

        ok, err = validate_musicxml(reference_xml)
        if not ok:
            return _error(f"reference_xml: {err}", "INVALID_INPUT")
        ok, err = validate_musicxml(target_xml)
        if not ok:
            return _error(f"target_xml: {err}", "INVALID_INPUT")

        try:
            result = compare(reference_xml, target_xml)
            payload = {
                "similarity_score": result.similarity_score,
                "summary": result.summary.to_dict(),
            }
            return [TextContent(type="text", text=json.dumps(payload, indent=2))]
        except ProcessingError as e:
            return _error(str(e), e.error_code)
        except Exception as e:
            logger.error("quick_similarity unexpected error: %s", e)
            return _error(f"Unexpected error: {e}", "PROCESSING_FAILED")

    elif name == "list_changes":
        reference_xml = arguments.get("reference_xml", "")
        target_xml = arguments.get("target_xml", "")
        part = arguments.get("part")
        measure_range = arguments.get("measure_range")

        ok, err = validate_musicxml(reference_xml)
        if not ok:
            return _error(f"reference_xml: {err}", "INVALID_INPUT")
        ok, err = validate_musicxml(target_xml)
        if not ok:
            return _error(f"target_xml: {err}", "INVALID_INPUT")

        if measure_range is not None:
            if (
                not isinstance(measure_range, list)
                or len(measure_range) != 2
                or not all(isinstance(n, int) and not isinstance(n, bool) for n in measure_range)
                or measure_range[0] > measure_range[1]
            ):
                return _error(
                    "measure_range must be a [start, end] pair of integers with start <= end.",
                    "INVALID_PARAMETER",
                )

        try:
            result = compare(reference_xml, target_xml)
            changes = _filter_changes(result, part, measure_range)
            payload = {"changes": changes, "count": len(changes)}
            return [TextContent(type="text", text=json.dumps(payload, indent=2))]
        except ProcessingError as e:
            return _error(str(e), e.error_code)
        except Exception as e:
            logger.error("list_changes unexpected error: %s", e)
            return _error(f"Unexpected error: {e}", "PROCESSING_FAILED")

    elif name == "generate_comparison_report":
        reference_xml = arguments.get("reference_xml", "")
        target_xml = arguments.get("target_xml", "")
        options = arguments.get("options")

        ok, err = validate_musicxml(reference_xml)
        if not ok:
            return _error(f"reference_xml: {err}", "INVALID_INPUT")
        ok, err = validate_musicxml(target_xml)
        if not ok:
            return _error(f"target_xml: {err}", "INVALID_INPUT")

        try:
            result = compare(reference_xml, target_xml, options)
            payload = {"report": generate_report(result), "similarity_score": result.similarity_score}
            return [TextContent(type="text", text=json.dumps(payload, indent=2))]
        except ProcessingError as e:
            return _error(str(e), e.error_code)
        except Exception as e:
            logger.error("generate_comparison_report unexpected error: %s", e)
            return _error(f"Unexpected error: {e}", "PROCESSING_FAILED")

    elif name == "export_annotated_musicxml":
        reference_xml = arguments.get("reference_xml", "")
        target_xml = arguments.get("target_xml", "")
        options = arguments.get("options")

        ok, err = validate_musicxml(reference_xml)
        if not ok:
            return _error(f"reference_xml: {err}", "INVALID_INPUT")
        ok, err = validate_musicxml(target_xml)
        if not ok:
            return _error(f"target_xml: {err}", "INVALID_INPUT")

        try:
            payload = annotate(reference_xml, target_xml, options)
            return [TextContent(type="text", text=json.dumps(payload, indent=2))]
        except ProcessingError as e:
            return _error(str(e), e.error_code)
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
            "input_formats": ["musicxml"],
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
            ],
            "backend": "music21",
            "backend_version": backend_version,
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "health_check":
        try:
            result = health_check()
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except Exception as e:
            logger.error("health_check unexpected error: %s", e)
            return _error(f"Unexpected error: {e}", "PROCESSING_FAILED")

    raise ValueError(f"Unknown tool: {name}")


def _error_result(message: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=message)], is_error=True)


async def _on_list_tools(ctx, params) -> ListToolsResult:
    return ListToolsResult(tools=await list_tools())


async def _on_call_tool(ctx, params: CallToolRequestParams) -> CallToolResult:
    # mcp 2.x low-level handlers neither validate input nor catch tool errors;
    # keep the 1.x decorator behaviour clients rely on.
    arguments = params.arguments or {}
    tool = next((t for t in await list_tools() if t.name == params.name), None)
    if tool is not None:
        try:
            jsonschema.validate(instance=arguments, schema=tool.input_schema)
        except jsonschema.ValidationError as e:
            return _error_result(f"Input validation error: {e.message}")
    try:
        return CallToolResult(content=await call_tool(params.name, arguments))
    except Exception as e:
        logger.error("Tool %s failed: %s", params.name, e)
        return _error_result(str(e))


app = Server("comparer-mcp", on_list_tools=_on_list_tools, on_call_tool=_on_call_tool)


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
        "export_annotated_musicxml, list_capabilities, health_check"
    )

    async def _run():
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
