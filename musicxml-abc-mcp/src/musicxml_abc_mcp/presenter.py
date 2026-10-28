"""Engine results to tool results: ``content`` for every client, ``structuredContent`` for apps.

``content`` is exactly what these tools returned before MCP Apps, so text-only clients see no
change (tests/test_content_golden.py). ``structuredContent`` is what the ABC Workbench reads. It
never holds a whole MusicXML score (proposal 6.3 rule 4): ABC is compact and may travel, a score
may not, so ``abc_to_musicxml`` reports only the warnings and how the score was delivered.
Trimming ``content`` for UI clients is a follow-up (proposal P7).
"""

from __future__ import annotations

import json

from mcp.types import TextContent

_STRINGS = {"type": "array", "items": {"type": "string"}}

ABC_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "abc_id": {"type": "string", "description": "Opaque handle to this export; new on every call"},
        "abc": {"type": "string"},
        "parts_included": _STRINGS,
        "warnings": _STRINGS,
    },
    "required": ["abc_id", "abc", "parts_included", "warnings"],
}

CONVERSION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "warnings": _STRINGS,
        "delivery": {
            "type": "string",
            "enum": ["inline", "path"],
            "description": "Whether the model's result holds the MusicXML text or a file path",
        },
        "musicxml_bytes": {"type": "integer", "minimum": 0, "description": "UTF-8 size of the score"},
    },
    "required": ["warnings", "delivery", "musicxml_bytes"],
}

VALIDATION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "valid": {"type": "boolean"},
        "errors": _STRINGS,
        "warnings": _STRINGS,
    },
    "required": ["valid", "errors", "warnings"],
}


def present_abc(result: dict, abc_id: str) -> tuple[list, dict]:
    """``(content, structured_content)`` for ``musicxml_to_abc``.

    ``content`` is the engine result alone: the id is for the app, and adding it would change
    what the model reads.
    """
    return _json_text(result), {"abc_id": abc_id, **result}


def present_conversion(content: list, result: dict) -> tuple[list, dict]:
    """``(content, structured_content)`` for ``abc_to_musicxml``.

    ``content`` is what ``deliver_score`` built (inline text, or a file path and link).
    """
    delivered_by_path = "musicxml_path" in json.loads(content[0].text)
    return content, {
        "warnings": list(result["warnings"]),
        "delivery": "path" if delivered_by_path else "inline",
        "musicxml_bytes": len(result["musicxml"].encode("utf-8")),
    }


def present_validation(result: dict) -> tuple[list, dict]:
    """``(content, structured_content)`` for ``validate_abc``, the same data twice."""
    return _json_text(result), dict(result)


def present_stored_abc(stored: dict, abc_id: str) -> tuple[list, dict]:
    """``(content, structured_content)`` for the app-only ABC fetch.

    Only the app reads the ABC, so the text block just says what was fetched and keeps the ABC
    (derived from user MusicXML, titles included) out of any model context.
    """
    text = "ABC export fetched for the ABC Workbench."
    return [TextContent(type="text", text=text)], {"abc_id": abc_id, **stored}


def _json_text(data: dict) -> list:
    return [TextContent(type="text", text=json.dumps(data, indent=2))]
