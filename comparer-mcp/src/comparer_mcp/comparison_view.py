"""The ``compare_scores`` result: one engine result cut to a detail level.

Pure data, no MCP imports. The levels are cumulative, so a lower level is a subset of ``full``.
"""

from __future__ import annotations

from sheet_music_mcp_core.errors import ProcessingError
from sheet_music_mcp_core.measures import parse_range
from sheet_music_mcp_core.params import aliased

from .models import ComparisonResult, ComparisonSummary, NoteDiff, PartDiff
from .report import generate_report
from .result_schema import json_schema_for

DETAILS = ("summary", "changes", "report", "full")
DEFAULT_DETAIL = "summary"

# The kinds a change can have: NoteDiff.operation without MATCH, which is not a change.
CHANGE_KINDS = ["PITCH_CHANGE", "DURATION_CHANGE", "SUBSTITUTION", "INSERTION", "DELETION"]


def merged_options(arguments: dict) -> dict | None:
    """``options`` with the top-level ``parts`` and ``measures`` folded in.

    The same filter given in both places must agree. Raises ProcessingError(INVALID_PARAMETER).
    """
    options = dict(arguments.get("options") or {})
    parts = arguments.get("parts")
    measures = parse_range(arguments.get("measures"))
    if parts is not None:
        _fold(options, "parts", parts, aliased(options, "parts", "part_filter"))
        options.pop("part_filter", None)
    if measures is not None:
        existing = parse_range(aliased(options, "measures", "measure_range"), param="options.measures")
        _fold(options, "measures", list(measures), list(existing) if existing else None)
        options.pop("measure_range", None)
    return options or None


def _fold(options: dict, name: str, value, existing) -> None:
    if existing is not None and existing != value:
        raise ProcessingError(
            f"'{name}' and 'options.{name}' were both given with different values.",
            "INVALID_PARAMETER",
            hint=f"Pass only '{name}'.",
        )
    options[name] = value


def changes_of(result: ComparisonResult) -> list[dict]:
    """Every note-level difference (operation != MATCH) with the name of its part."""
    changes = []
    for part_diff in result.part_diffs:
        for measure_diff in part_diff.measure_diffs:
            for note_diff in measure_diff.note_diffs:
                if note_diff.operation == "MATCH":
                    continue
                entry = note_diff.to_dict()
                entry["part_name"] = part_diff.part_name
                changes.append(entry)
    return changes


def view_of(result: ComparisonResult, detail: str) -> dict:
    """``result`` as the ``compare_scores`` payload for ``detail`` (one of DETAILS)."""
    view = {
        "detail": detail,
        "similarity_score": result.similarity_score,
        "summary": result.summary.to_dict(),
    }
    if detail in ("changes", "full"):
        changes = changes_of(result)
        view["changes"] = changes
        view["count"] = len(changes)
    if detail in ("report", "full"):
        view["report"] = generate_report(result)
    if detail == "full":
        view["part_diffs"] = [part_diff.to_dict() for part_diff in result.part_diffs]
    return view


def _change_schema() -> dict:
    schema = json_schema_for(NoteDiff)
    schema["properties"]["operation"] = {"type": "string", "enum": CHANGE_KINDS}
    schema["properties"]["part_name"] = {"type": "string"}
    schema["required"] = [*schema["required"], "part_name"]
    return schema


COMPARE_SCORES_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "detail": {"type": "string", "enum": list(DETAILS)},
        "similarity_score": {"type": "number", "minimum": 0, "maximum": 1},
        "summary": json_schema_for(ComparisonSummary),
        "changes": {"type": "array", "items": _change_schema()},
        "count": {"type": "integer", "minimum": 0},
        "report": {"type": "string", "description": "Human-readable comparison report"},
        "part_diffs": {"type": "array", "items": json_schema_for(PartDiff)},
    },
    "required": ["detail", "similarity_score", "summary"],
}
