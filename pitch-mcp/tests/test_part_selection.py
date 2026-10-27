"""Part selection by ID, name or voice, with stable MusicXML part IDs (docs/conventions.md, Part
Selection; docs/research/core-library-review.md F1).

music21 replaces part.id with the part name, repeats it for same-named parts and gives unnamed
parts a new integer on every parse, so these tests fail against selection by music21's part.id.
"""

import json

import pytest
from sheet_music_mcp_core.parts import PartSelectionError

from pitch_mcp.engine import load_score, stop_monitoring
from pitch_mcp.server import call_tool, list_tools
from pitch_mcp.utils import extract_part_notes


def _score(parts):
    """MusicXML at 120 BPM with one whole note per part: parts = [(xml_id, name, step), ...]."""
    part_list = "".join(
        f'<score-part id="{pid}"><part-name>{name}</part-name></score-part>' for pid, name, _ in parts
    )
    body = "".join(
        f'<part id="{pid}"><measure number="1"><attributes><divisions>1</divisions>'
        f"<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
        f'<direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit>'
        f"<per-minute>120</per-minute></metronome></direction-type><sound tempo=\"120\"/></direction>"
        f"<note><pitch><step>{step}</step><octave>4</octave></pitch><duration>4</duration>"
        f"<type>whole</type></note></measure></part>"
        for pid, _, step in parts
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><score-partwise version="3.1">'
        f"<part-list>{part_list}</part-list>{body}</score-partwise>"
    )


SATB = _score([("P1", "Soprano", "G"), ("P2", "Alto", "E"), ("P3", "Tenor", "C"), ("P4", "Bass", "A")])
TWO_TENORS = _score([("P3", "Tenor", "C"), ("P4", "Tenor", "E")])
UNNAMED = _score([("P1", "", "C"), ("P2", "", "E")])


class TestExtractPartNotes:
    @pytest.mark.parametrize("request_", ["P2", "Alto", "alto", "A"])
    def test_id_name_or_voice(self, request_):
        info, notes = extract_part_notes(SATB, request_)

        assert (info.id, info.name) == ("P2", "Alto")
        assert [n["note_name"] for n in notes] == ["E4"]

    def test_selects_one_of_two_same_named_parts(self):
        info, notes = extract_part_notes(TWO_TENORS, "P4")

        assert info.id == "P4"
        assert [n["note_name"] for n in notes] == ["E4"]

    def test_unnamed_part(self):
        info, notes = extract_part_notes(UNNAMED, "P2")

        assert info.id == "P2"
        assert [n["note_name"] for n in notes] == ["E4"]

    def test_ambiguous_name_lists_choices(self):
        with pytest.raises(PartSelectionError) as excinfo:
            extract_part_notes(TWO_TENORS, "Tenor")

        assert excinfo.value.choices == ["Tenor (P3)", "Tenor (P4)"]


class TestLoadScore:
    def test_reports_stable_id_and_real_name(self):
        result = load_score(SATB, "A")
        try:
            assert result["part_id"] == "P2"
            assert result["part_name"] == "Alto"
        finally:
            stop_monitoring(result["session_id"])

    def test_unnamed_part_name_falls_back_to_id(self):
        result = load_score(UNNAMED, "P1")
        try:
            assert result["part_name"] == "P1"
        finally:
            stop_monitoring(result["session_id"])


class TestServer:
    @pytest.mark.parametrize("tool_name", ["analyze_recording", "load_score"])
    async def test_schema_has_part_and_deprecated_part_id(self, tool_name):
        tool = next(t for t in await list_tools() if t.name == tool_name)
        schema = tool.input_schema

        assert schema["properties"]["part"]["type"] == "string"
        assert schema["properties"]["part_id"]["description"].startswith("(Deprecated: use `part`)")
        assert {"required": ["part"]} in schema["anyOf"]
        assert {"required": ["part_id"]} in schema["anyOf"]
        assert "part_id" not in schema["required"]

    @pytest.mark.parametrize("argument", ["part", "part_id"])
    async def test_load_score_accepts_new_and_deprecated_names(self, argument):
        result = await call_tool("load_score", {"musicxml": SATB, argument: "Bass"})
        payload = json.loads(result[0].text)
        try:
            assert payload["part_id"] == "P4"
        finally:
            stop_monitoring(payload["session_id"])

    async def test_unknown_part_returns_choices_and_hint(self):
        result = await call_tool("load_score", {"musicxml": SATB, "part": "Piano"})
        payload = json.loads(result[0].text)

        assert payload["error_code"] == "INVALID_PARAMETER"
        assert payload["choices"] == ["Soprano (P1)", "Alto (P2)", "Tenor (P3)", "Bass (P4)"]
        assert payload["hint"]

    async def test_conflicting_part_and_part_id_are_rejected(self):
        result = await call_tool("load_score", {"musicxml": SATB, "part": "S", "part_id": "P2"})

        assert json.loads(result[0].text)["error_code"] == "INVALID_PARAMETER"

    async def test_missing_part_is_reported(self):
        result = await call_tool("load_score", {"musicxml": SATB})
        payload = json.loads(result[0].text)

        assert payload["error_code"] == "INVALID_INPUT"
        assert "part" in payload["error"]
