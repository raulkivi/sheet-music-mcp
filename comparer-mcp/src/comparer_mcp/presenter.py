"""Engine results to tool results: ``content`` for every client, ``structuredContent`` for apps.

``content`` is exactly the JSON text these tools returned before MCP Apps, so text-only clients
see no change (tests/test_content_golden.py). ``structuredContent`` is what the Diff Viewer
reads: the full ``ComparisonResult``. Trimming ``content`` for UI clients is a follow-up
(proposal P7).
"""

from __future__ import annotations

import json

from mcp.types import TextContent

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


def present_comparison(result: ComparisonResult) -> tuple[list, dict]:
    """``(content, structured_content)`` for a full diff; both are the result's dict."""
    return _json_text(result.to_dict()), result.to_dict()


def present_report(payload: dict) -> tuple[list, dict]:
    """``(content, structured_content)`` for the readable report and its similarity score."""
    return _json_text(payload), dict(payload)


def _json_text(data: dict) -> list:
    return [TextContent(type="text", text=json.dumps(data, indent=2))]
