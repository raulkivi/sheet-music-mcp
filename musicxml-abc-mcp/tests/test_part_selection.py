"""Part selection by ID, name or voice, with stable MusicXML part IDs (docs/conventions.md, Part
Selection; docs/research/core-library-review.md F1).

music21 replaces part.id with the part name, repeats it for same-named parts and gives unnamed
parts a new integer on every parse, so these tests fail against selection by music21's part.id.
"""

import json

import pytest
from sheet_music_mcp_core.parts import PartSelectionError

from musicxml_abc_mcp.engine import musicxml_to_abc
from musicxml_abc_mcp.server import call_tool, list_tools


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


class TestEngine:
    def test_parts_included_reports_musicxml_ids(self):
        assert musicxml_to_abc(SATB)["parts_included"] == ["P1", "P2", "P3", "P4"]

    @pytest.mark.parametrize("request_", ["P2", "Alto", "alto", "A"])
    def test_id_name_or_voice_selects_one_part(self, request_):
        assert musicxml_to_abc(SATB, part_id=request_)["parts_included"] == ["P2"]

    def test_selects_one_of_two_same_named_parts(self):
        result = musicxml_to_abc(TWO_TENORS, part_id="P4")

        assert result["parts_included"] == ["P4"]
        assert "E" in result["abc"].split("K:", 1)[1]
        assert "C" not in result["abc"].split("K:", 1)[1].split("\n", 1)[1]

    def test_same_named_parts_are_ambiguous_by_name(self):
        with pytest.raises(PartSelectionError) as excinfo:
            musicxml_to_abc(TWO_TENORS, part_id="Tenor")

        assert excinfo.value.choices == ["Tenor (P3)", "Tenor (P4)"]

    def test_unnamed_part_is_selectable_and_labelled_by_its_id(self):
        result = musicxml_to_abc(UNNAMED, part_id="P2")

        assert result["parts_included"] == ["P2"]
        assert "P2" in result["abc"]

    def test_unnamed_parts_never_show_music21_object_numbers(self):
        abc = musicxml_to_abc(UNNAMED)["abc"]

        assert not any(len(token) > 9 and token.isdigit() for token in abc.replace(":", " ").split())


class TestServer:
    async def test_schema_has_part_and_deprecated_part_id(self):
        tool = next(t for t in await list_tools() if t.name == "musicxml_to_abc")
        props = tool.input_schema["properties"]

        assert props["part"]["type"] == "string"
        assert props["part_id"]["description"].startswith("(Deprecated: use `part`)")

    @pytest.mark.parametrize("argument", ["part", "part_id"])
    async def test_new_and_deprecated_names_work(self, argument):
        result = await call_tool("musicxml_to_abc", {"musicxml": SATB, argument: "Bass"})

        assert json.loads(result[0].text)["parts_included"] == ["P4"]

    async def test_unknown_part_returns_choices_and_hint(self):
        result = await call_tool("musicxml_to_abc", {"musicxml": SATB, "part": "Piano"})
        payload = json.loads(result[0].text)

        assert payload["error_code"] == "INVALID_PARAMETER"
        assert payload["choices"] == ["Soprano (P1)", "Alto (P2)", "Tenor (P3)", "Bass (P4)"]
        assert payload["hint"]

    async def test_conflicting_part_and_part_id_are_rejected(self):
        result = await call_tool("musicxml_to_abc", {"musicxml": SATB, "part": "S", "part_id": "P2"})

        assert json.loads(result[0].text)["error_code"] == "INVALID_PARAMETER"
