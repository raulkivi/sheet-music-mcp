"""Engine results to tool results: ``content`` for every client, ``structuredContent`` for apps.

``content`` is exactly the JSON text these tools returned before MCP Apps, so text-only clients
see no change (tests/test_content_golden.py). ``structuredContent`` is what the Diff Viewer
reads: the full ``ComparisonResult``. Trimming ``content`` for UI clients is a follow-up
(proposal P7).
"""

from __future__ import annotations

import json

from mcp.types import TextContent

from .comparison_view import view_of
from .models import ComparisonResult
from .result_schema import json_schema_for

COMPARISON_OUTPUT_SCHEMA = json_schema_for(ComparisonResult)

REPORT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "report": {"type": "string", "description": "Human-readable comparison report"},
        "similarity_score": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["report", "similarity_score"],
}


DIFF_SCORES_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "diff_id": {"type": "string"},
        "reference_musicxml": {"type": "string", "description": "Reference score with the differences colored"},
        "target_musicxml": {"type": "string", "description": "Target score with the differences colored"},
        "legend": {
            "type": "object",
            "description": "Difference kind to the #RRGGBB color it is drawn in",
            "additionalProperties": {"type": "string"},
        },
    },
    "required": ["diff_id", "reference_musicxml", "target_musicxml", "legend"],
}

EXPORT_DIFF_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "reference_annotated_musicxml_path": {"type": "string"},
        "target_annotated_musicxml_path": {"type": "string"},
        "similarity_score": {"type": "number", "minimum": 0, "maximum": 1},
        "legend": {"type": "object", "additionalProperties": {"type": "string"}},
    },
    "required": ["reference_annotated_musicxml_path", "target_annotated_musicxml_path"],
}


def present_diff_scores(scores: dict) -> tuple[list, dict]:
    """``(content, structured_content)`` for the app-only fetch of the annotated pair."""
    size_kb = max(1, round((len(scores["reference_musicxml"]) + len(scores["target_musicxml"])) / 1024))
    text = f"Both scores ({size_kb} kB) with the differences marked, sent to the Diff Viewer."
    return [TextContent(type="text", text=text)], dict(scores)


def present_comparison(result: ComparisonResult) -> tuple[list, dict]:
    """``(content, structured_content)`` for a full diff; both are the result's dict."""
    return _json_text(result.to_dict()), result.to_dict()


def present_report(payload: dict) -> tuple[list, dict]:
    """``(content, structured_content)`` for the readable report and its similarity score."""
    return _json_text(payload), dict(payload)


def present_view(result: ComparisonResult, detail: str) -> tuple[list, dict]:
    """``(content, structured_content)`` for ``compare_scores``; both are the same view."""
    view = view_of(result, detail)
    return _json_text(view), view


def _json_text(data: dict) -> list:
    return [TextContent(type="text", text=json.dumps(data, indent=2))]
