"""Engine results to tool results: ``content`` for every client, ``structuredContent`` for apps.

``content`` is exactly the JSON text these tools returned before MCP Apps, so text-only clients
see no change (tests/test_content_golden.py). ``structuredContent`` is what the Practice Coach
reads. Trimming ``content`` for UI clients is a follow-up (proposal P7).
"""

from __future__ import annotations

import json

from mcp.types import TextContent

STATUSES = ["on_pitch", "sharp", "flat", "no_signal"]

SESSION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "session_id": {"type": "string"},
        "part_id": {"type": "string", "description": "Stable MusicXML score-part id"},
        "part_name": {"type": "string"},
        "measure_count": {"type": "integer", "minimum": 0, "description": "Bars from the first practised"},
        "duration_seconds": {"type": "number", "minimum": 0},
        "tempo_bpm": {"type": "number", "description": "Score tempo, or the start_practice override"},
    },
    "required": ["session_id", "part_id", "part_name", "measure_count", "duration_seconds", "tempo_bpm"],
}

POSITION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "session_id": {"type": "string"},
        "measure": {"type": "integer", "description": "Printed measure number"},
        "beat": {"type": "number"},
        "expected_note": {"type": "string"},
        "sung_pitch_hz": {"type": ["number", "null"]},
        "accuracy_cents": {"type": ["integer", "null"], "description": "Positive = sharp"},
        "status": {"type": "string", "enum": STATUSES},
    },
    "required": ["session_id", "measure", "beat", "expected_note", "sung_pitch_hz", "accuracy_cents", "status"],
}

_NOTE_ACCURACY = {
    "type": "object",
    "properties": {
        "measure": {"type": "integer"},
        "beat": {"type": "number"},
        "expected": {"type": "string"},
        "expected_hz": {"type": "number"},
        "sung_hz": {"type": ["number", "null"]},
        "accuracy_cents": {"type": ["integer", "null"]},
        "status": {"type": "string", "enum": STATUSES},
    },
    "required": ["measure", "beat", "expected", "expected_hz", "sung_hz", "accuracy_cents", "status"],
}

ANALYSIS_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "part_id": {"type": "string"},
        "part_name": {"type": "string"},
        "measures_covered": {"type": "integer", "minimum": 0},
        "avg_accuracy_cents": {"type": ["number", "null"]},
        "note_accuracy": {"type": "array", "items": _NOTE_ACCURACY},
        "accuracy_histogram": {
            "type": "object",
            "properties": {status: {"type": "integer", "minimum": 0} for status in STATUSES},
            "required": STATUSES,
        },
        "highlights": {"type": "array", "items": {"type": "object"}},
    },
    "required": ["part_id", "part_name", "measures_covered", "avg_accuracy_cents",
                 "note_accuracy", "accuracy_histogram", "highlights"],
}

SCORE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "session_id": {"type": "string"},
        "musicxml": {"type": "string", "description": "The score the session practises"},
    },
    "required": ["session_id", "musicxml"],
}


def present_session(result: dict, view: dict) -> tuple[list, dict]:
    """``(content, structured_content)`` for a tool that opened a session.

    ``content`` stays the tool's own result (``start_practice`` adds ``status``); the structured
    side is the session ``view`` (``engine.describe_session``), which also knows the tempo.
    """
    return _json_text(result), dict(view)


def present_position(position: dict) -> tuple[list, dict]:
    """``(content, structured_content)`` for the current position snapshot."""
    return _json_text(position), dict(position)


def present_analysis(analysis: dict) -> tuple[list, dict]:
    """``(content, structured_content)`` for an offline analysis, every note included."""
    return _json_text(analysis), dict(analysis)


def present_score(score: dict) -> tuple[list, dict]:
    """``(content, structured_content)`` for the app-only score fetch.

    Only the app reads the MusicXML, so the text block just says what was fetched and keeps the
    document out of any model context.
    """
    size_kb = max(1, round(len(score["musicxml"].encode("utf-8")) / 1024))
    text = f"Score for session {score['session_id']} ({size_kb} kB) fetched for the Practice Coach."
    return [TextContent(type="text", text=text)], dict(score)


def _json_text(data: dict) -> list:
    return [TextContent(type="text", text=json.dumps(data, indent=2))]
