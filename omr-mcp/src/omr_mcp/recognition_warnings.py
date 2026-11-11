"""Structured ``warnings[]`` for recognition results (docs/conventions.md, Warnings).

Pure functions, no MCP imports. Messages are built from counts and printed bar numbers only,
never from score metadata.
"""

from __future__ import annotations

from collections.abc import Iterable

from sheet_music_mcp_core.scores import ScoreFormatError, parse_score

WARNINGS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "code": {"type": "string"},
            "severity": {"enum": ["info", "warning", "error"]},
            "message": {"type": "string"},
            "measure": {"type": "integer"},
            "part": {"type": "string"},
        },
        "required": ["code", "severity", "message"],
    },
}


def build_warnings(
    musicxml: str,
    *,
    parts: int,
    staves_on_page: int | None,
    engine_notes: Iterable[str] = (),
) -> list[dict]:
    """Warning items for one recognition.

    ``parts`` is the recognised part count (metadata ``staves_detected``); ``staves_on_page`` the
    image's staff count, None when unknown. ``engine_notes`` are the engine's plain-text
    low-resolution notes, kept as LOW_RESOLUTION items so the array has one shape.
    """
    items = [
        {"code": "LOW_RESOLUTION", "severity": "warning", "message": note} for note in engine_notes
    ]
    if staves_on_page and parts < staves_on_page:
        items.append(
            {
                "code": "PARTS_FEWER_THAN_STAVES",
                # "for awareness" until the check is measured on real scores
                "severity": "info",
                "message": f"{parts} {'part' if parts == 1 else 'parts'} recognised but "
                f"{staves_on_page} staves found on the page; voices may be merged",
            }
        )
    items.extend(_empty_measures(musicxml))
    return items


def _empty_measures(musicxml: str) -> list[dict]:
    try:
        root = parse_score(musicxml)
    except ScoreFormatError:
        return []
    found = []
    for part in root.iter("part"):
        for measure in part.iter("measure"):
            if measure.find("note") is not None:
                continue
            item = {"code": "EMPTY_MEASURE", "severity": "warning", "message": ""}
            number = (measure.get("number") or "").strip()
            if number.isdigit():
                item["measure"] = int(number)
                item["message"] = f"Measure {number} has no notes or rests"
            else:
                item["message"] = "A measure has no notes or rests"
            if part.get("id"):
                item["part"] = part.get("id")
            found.append(item)
    return found
