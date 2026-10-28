"""Part selection by ID, name or voice, with stable MusicXML part IDs (docs/conventions.md, Part
Selection; docs/research/core-library-review.md F1).

music21 replaces part.id with the part name, repeats it for same-named parts and gives unnamed
parts a new integer on every parse, so these tests fail against selection by music21's part.id.
"""

import io
import json

import music21
import pytest
from sheet_music_mcp_core.parts import PartSelectionError

from synth_mcp.engine import extract_midi, parse_parts, resolve_part_ids
from synth_mcp.server import call_tool

from .midi_helpers import fake_render


def _score(parts):
    """MusicXML with one whole note per part: parts = [(xml_id, name, step), ...]."""
    part_list = "".join(
        f'<score-part id="{pid}"><part-name>{name}</part-name></score-part>' for pid, name, _ in parts
    )
    body = "".join(
        f'<part id="{pid}"><measure number="1"><attributes><divisions>1</divisions>'
        f"<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
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


def _midi_pitches(midi_bytes):
    score = music21.midi.translate.midiStringToStream(midi_bytes)
    return sorted({p.nameWithOctave for p in score.pitches})


class TestStablePartIds:
    def test_get_parts_reports_musicxml_ids(self):
        assert [p["id"] for p in parse_parts(SATB)] == ["P1", "P2", "P3", "P4"]

    def test_unnamed_parts_get_the_same_ids_on_every_call(self):
        first = [p["id"] for p in parse_parts(UNNAMED)]
        second = [p["id"] for p in parse_parts(UNNAMED)]

        assert first == second == ["P1", "P2"]

    def test_same_named_parts_have_distinct_ids(self):
        assert [p["id"] for p in parse_parts(TWO_TENORS)] == ["P3", "P4"]


class TestResolvePartIds:
    @pytest.mark.parametrize(
        "requested, expected",
        [
            (["P2"], ["P2"]),
            (["soprano"], ["P1"]),
            (["S", "B"], ["P1", "P4"]),
            (["Alto", "P2"], ["P2"]),
        ],
    )
    def test_id_name_or_voice(self, requested, expected):
        assert resolve_part_ids(SATB, requested) == expected

    def test_unknown_part_lists_choices(self):
        with pytest.raises(PartSelectionError) as excinfo:
            resolve_part_ids(SATB, ["Piano"])

        assert excinfo.value.choices == ["Soprano (P1)", "Alto (P2)", "Tenor (P3)", "Bass (P4)"]


class TestExtractMidiSelectsByPosition:
    def test_selects_one_of_two_same_named_parts(self):
        assert _midi_pitches(extract_midi(TWO_TENORS, ["P4"], 1.0)) == ["E4"]

    def test_selects_an_unnamed_part(self):
        assert _midi_pitches(extract_midi(UNNAMED, ["P2"], 1.0)) == ["E4"]

    def test_accepts_a_voice_name(self):
        assert _midi_pitches(extract_midi(SATB, ["Alto"], 1.0)) == ["E4"]


class TestServerParameters:
    async def test_schema_has_parts_and_deprecated_part_ids(self):
        from synth_mcp.server import list_tools

        tool = next(t for t in await list_tools() if t.name == "synthesize")
        props = tool.input_schema["properties"]

        assert props["parts"]["type"] == "array"
        assert props["part_ids"]["description"].startswith("(Deprecated: use `parts`)")

    async def test_unknown_part_returns_choices_and_hint(self):
        result = await call_tool("synthesize", {"musicxml": SATB, "parts": ["Piano"]})
        payload = json.loads(result[0].text)

        assert payload["error_code"] == "INVALID_PARAMETER"
        assert payload["choices"] == ["Soprano (P1)", "Alto (P2)", "Tenor (P3)", "Bass (P4)"]
        assert payload["hint"]

    async def test_conflicting_parts_and_part_ids_are_rejected(self):
        result = await call_tool("synthesize", {"musicxml": SATB, "parts": ["S"], "part_ids": ["P2"]})

        assert json.loads(result[0].text)["error_code"] == "INVALID_PARAMETER"

    @pytest.mark.parametrize("argument", ["parts", "part_ids"])
    async def test_parts_included_reports_resolved_ids(self, argument, monkeypatch, tmp_path):
        monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
        monkeypatch.setattr("synth_mcp.server.synthesize_midi", fake_render)

        result = await call_tool("synthesize", {"musicxml": SATB, argument: ["Alto", "B"]})

        assert json.loads(result[0].text)["parts_included"] == ["P2", "P4"]
