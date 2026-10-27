"""Part selection by ID, name or voice, with stable MusicXML part IDs (docs/conventions.md, Part
Selection; docs/research/core-library-review.md F1).

music21 replaces part.id with the part name, repeats it for same-named parts and gives unnamed
parts a new integer on every parse, so these tests fail against music21's part.id.
"""

import json

import pytest
from sheet_music_mcp_core.parts import PartSelectionError

from comparer_mcp.engine import compare
from comparer_mcp.report import generate_report
from comparer_mcp.server import call_tool, list_tools


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


SATB_REF = _score([("P1", "Soprano", "G"), ("P2", "Alto", "E"), ("P3", "Tenor", "C"), ("P4", "Bass", "A")])
# Alto and Bass changed
SATB_TGT = _score([("P1", "Soprano", "G"), ("P2", "Alto", "F"), ("P3", "Tenor", "C"), ("P4", "Bass", "B")])
TENORS_REF = _score([("P3", "Tenor", "C"), ("P4", "Tenor", "E")])
TENORS_TGT = _score([("P3", "Tenor", "C"), ("P4", "Tenor", "F")])  # only the second changed
UNNAMED_REF = _score([("P1", "", "C"), ("P2", "", "E")])
UNNAMED_TGT = _score([("P1", "", "C")])  # second part missing


class TestStablePartIds:
    def test_part_diffs_carry_musicxml_ids(self):
        result = compare(SATB_REF, SATB_TGT)

        assert [(pd.reference_part_id, pd.target_part_id) for pd in result.part_diffs] == [
            ("P1", "P1"),
            ("P2", "P2"),
            ("P3", "P3"),
            ("P4", "P4"),
        ]

    def test_unnamed_parts_get_stable_ids_and_a_name(self):
        first = compare(UNNAMED_REF, UNNAMED_REF)
        second = compare(UNNAMED_REF, UNNAMED_REF)

        assert [pd.reference_part_id for pd in first.part_diffs] == ["P1", "P2"]
        assert [pd.reference_part_id for pd in second.part_diffs] == ["P1", "P2"]
        assert [pd.part_name for pd in first.part_diffs] == ["P1", "P2"]

    def test_missing_unnamed_part_is_reported_by_id_and_the_report_renders(self):
        result = compare(UNNAMED_REF, UNNAMED_TGT)

        assert result.summary.parts_missing == ["P2"]
        assert "P2" in generate_report(result)


class TestOptionsParts:
    def test_parts_option_accepts_a_voice(self):
        result = compare(SATB_REF, SATB_TGT, options={"parts": ["A"]})

        assert [pd.reference_part_id for pd in result.part_diffs] == ["P2"]

    def test_parts_option_selects_one_of_two_same_named_parts(self):
        result = compare(TENORS_REF, TENORS_TGT, options={"parts": ["P4"]})

        assert [pd.reference_part_id for pd in result.part_diffs] == ["P4"]
        assert result.similarity_score < 1.0

    def test_deprecated_part_filter_still_works(self):
        result = compare(SATB_REF, SATB_TGT, options={"part_filter": ["Bass"]})

        assert [pd.reference_part_id for pd in result.part_diffs] == ["P4"]

    def test_unknown_part_lists_reference_choices(self):
        with pytest.raises(PartSelectionError) as excinfo:
            compare(SATB_REF, SATB_TGT, options={"parts": ["Piano"]})

        assert excinfo.value.choices == ["Soprano (P1)", "Alto (P2)", "Tenor (P3)", "Bass (P4)"]

    def test_conflicting_parts_and_part_filter_are_rejected(self):
        with pytest.raises(Exception) as excinfo:
            compare(SATB_REF, SATB_TGT, options={"parts": ["S"], "part_filter": ["Alto"]})

        assert excinfo.value.error_code == "INVALID_PARAMETER"


class TestServer:
    async def test_options_schema_has_parts_and_deprecated_part_filter(self):
        tool = next(t for t in await list_tools() if t.name == "compare_musicxml")
        props = tool.input_schema["properties"]["options"]["properties"]

        assert props["parts"]["type"] == "array"
        assert props["part_filter"]["description"].startswith("(Deprecated: use `parts`)")

    @pytest.mark.parametrize("part", ["Alto", "alto", "A", "P2"])
    async def test_list_changes_part_by_id_name_or_voice(self, part):
        result = await call_tool(
            "list_changes", {"reference_xml": SATB_REF, "target_xml": SATB_TGT, "part": part}
        )
        changes = json.loads(result[0].text)["changes"]

        assert changes and {c["part_name"] for c in changes} == {"Alto"}

    async def test_list_changes_tells_same_named_parts_apart(self):
        result = await call_tool(
            "list_changes", {"reference_xml": TENORS_REF, "target_xml": TENORS_TGT, "part": "P3"}
        )

        assert json.loads(result[0].text)["changes"] == []

    async def test_list_changes_unknown_part_returns_choices(self):
        result = await call_tool(
            "list_changes", {"reference_xml": SATB_REF, "target_xml": SATB_TGT, "part": "Piano"}
        )
        payload = json.loads(result[0].text)

        assert payload["error_code"] == "INVALID_PARAMETER"
        assert payload["choices"] == ["Soprano (P1)", "Alto (P2)", "Tenor (P3)", "Bass (P4)"]
