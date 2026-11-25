"""compare_scores (C24): one tool with four detail levels, and the five old names as aliases."""

import json

import jsonschema
import pytest
from mcp import Client
from sheet_music_mcp_core.annotations import READ_ONLY

import comparer_mcp.server as server
from comparer_mcp.server import app, call_tool, call_tool_result, list_tools

from .test_part_selection import SATB_REF
from .test_server import REFERENCE_XML, TARGET_XML

PAIR = {"reference_xml": REFERENCE_XML, "target_xml": TARGET_XML}
DETAILS = ("summary", "changes", "report", "full")
CHANGE_KINDS = ["PITCH_CHANGE", "DURATION_CHANGE", "SUBSTITUTION", "INSERTION", "DELETION"]
DEPRECATED = (
    "compare_musicxml",
    "compare_musicxml_files",
    "quick_similarity",
    "list_changes",
    "generate_comparison_report",
)


async def _tool(name):
    return next(t for t in await list_tools() if t.name == name)


async def _structured(arguments):
    result = await call_tool_result("compare_scores", arguments)
    assert not result.is_error, result.content[0].text
    return result.structured_content


async def _error_code(arguments, *, through_protocol=False):
    if through_protocol:
        async with Client(app) as client:
            result = await client.call_tool("compare_scores", arguments)
    else:
        result = await call_tool_result("compare_scores", arguments)
    assert result.is_error
    return json.loads(result.content[0].text)


@pytest.fixture
def files(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
    monkeypatch.delenv("SHEET_MUSIC_INPUT_ROOTS", raising=False)
    reference, target = tmp_path / "ref.musicxml", tmp_path / "tgt.musicxml"
    reference.write_text(REFERENCE_XML, encoding="utf-8")
    target.write_text(TARGET_XML, encoding="utf-8")
    return reference, target


class TestToolDefinition:
    async def test_title_and_read_only_annotations(self):
        tool = await _tool("compare_scores")

        assert tool.title == "Compare scores (summary, changes, report or full diff)"
        assert tool.annotations.model_dump(exclude_none=True) == dict(READ_ONLY)

    async def test_input_schema(self):
        schema = (await _tool("compare_scores")).input_schema
        properties = schema["properties"]

        assert {"reference_xml", "reference_path", "target_xml", "target_path"} <= set(properties)
        assert properties["detail"]["enum"] == list(DETAILS)
        assert properties["detail"]["default"] == "summary"
        assert {"parts", "measures", "options"} <= set(properties)
        assert "detail" not in schema.get("required", [])
        assert len(schema["allOf"]) == 2

    async def test_output_schema_is_declared(self):
        assert (await _tool("compare_scores")).output_schema["required"] == [
            "detail",
            "similarity_score",
            "summary",
        ]

    async def test_viewer_is_linked_when_packaged(self, packaged_ui):
        assert (await _tool("compare_scores")).meta == {"ui": {"resourceUri": "ui://comparer/diff-viewer"}}

    async def test_listed_in_capabilities(self):
        data = json.loads((await call_tool("list_capabilities", {}))[0].text)

        assert "compare_scores" in data["tools"]

    async def test_instructions_point_at_compare_scores(self):
        async with Client(app) as client:
            assert "compare_scores" in client.instructions


class TestDetailLevels:
    async def test_summary_is_the_default(self):
        data = await _structured(PAIR)

        assert data["detail"] == "summary"
        assert set(data) == {"detail", "similarity_score", "summary"}
        assert 0 <= data["similarity_score"] < 1
        assert data["summary"]["notes_pitch_changed"] == 1

    async def test_changes(self):
        data = await _structured({**PAIR, "detail": "changes"})

        assert set(data) == {"detail", "similarity_score", "summary", "changes", "count"}
        assert data["count"] == len(data["changes"]) == 1
        change = data["changes"][0]
        assert change["operation"] == "PITCH_CHANGE"
        assert change["part_name"] == "Soprano"
        assert change["measure_number"] == 1

    async def test_report(self):
        data = await _structured({**PAIR, "detail": "report"})

        assert set(data) == {"detail", "similarity_score", "summary", "report"}
        assert isinstance(data["report"], str) and data["report"]

    async def test_full_has_everything(self):
        data = await _structured({**PAIR, "detail": "full"})

        assert set(data) == {"detail", "similarity_score", "summary", "changes", "count", "report", "part_diffs"}
        assert [pd["part_name"] for pd in data["part_diffs"]] == ["Soprano", "Alto"]

    async def test_identical_scores_have_no_changes(self):
        data = await _structured({"reference_xml": REFERENCE_XML, "target_xml": REFERENCE_XML, "detail": "changes"})

        assert data["similarity_score"] == 1.0
        assert data["changes"] == [] and data["count"] == 0

    @pytest.mark.parametrize("detail", DETAILS)
    async def test_output_validates_against_the_schema(self, detail):
        schema = (await _tool("compare_scores")).output_schema
        data = await _structured({**PAIR, "detail": detail})

        jsonschema.validate(data, schema)

    async def test_change_kinds_come_from_the_diff_model(self):
        schema = (await _tool("compare_scores")).output_schema
        change = schema["properties"]["changes"]["items"]

        assert change["properties"]["operation"]["enum"] == CHANGE_KINDS
        assert "part_name" in change["properties"]

    async def test_content_text_is_the_structured_result(self):
        result = await call_tool_result("compare_scores", {**PAIR, "detail": "changes"})

        assert json.loads(result.content[0].text) == result.structured_content

    async def test_unknown_detail_is_rejected_over_the_protocol(self):
        data = await _error_code({**PAIR, "detail": "everything"}, through_protocol=True)

        assert data["error_code"] == "INVALID_PARAMETER"


class TestInputs:
    @pytest.mark.parametrize("detail", DETAILS)
    async def test_path_equals_inline(self, detail, files):
        reference, target = files
        inline = await _structured({**PAIR, "detail": detail})
        by_path = await _structured({"reference_path": str(reference), "target_path": str(target), "detail": detail})

        assert by_path == inline

    async def test_mixed_inline_and_path(self, files):
        reference, _ = files

        assert await _structured({"reference_path": str(reference), "target_xml": TARGET_XML}) == await _structured(PAIR)

    async def test_both_of_a_side_is_invalid_parameter(self, files):
        reference, _ = files
        data = await _error_code({**PAIR, "reference_path": str(reference)}, through_protocol=True)

        assert data["error_code"] == "INVALID_PARAMETER"
        assert "reference_path" in data["error"]

    async def test_neither_of_a_side_is_invalid_parameter(self):
        data = await _error_code({"reference_xml": REFERENCE_XML}, through_protocol=True)

        assert data["error_code"] == "INVALID_PARAMETER"

    async def test_invalid_inline_xml(self):
        data = await _error_code({"reference_xml": "nope", "target_xml": TARGET_XML})

        assert data["error_code"] == "INVALID_INPUT"


class TestFilters:
    async def test_parts_limits_the_comparison(self):
        data = await _structured({**PAIR, "detail": "full", "parts": ["Alto"]})

        assert [pd["part_name"] for pd in data["part_diffs"]] == ["Alto"]
        assert data["changes"] == []
        assert data["similarity_score"] == 1.0

    async def test_parts_accept_voices(self):
        data = await _structured({"reference_xml": SATB_REF, "target_xml": SATB_REF, "detail": "full", "parts": ["S"]})

        assert len(data["part_diffs"]) == 1

    async def test_unknown_part_is_an_error(self):
        data = await _error_code({**PAIR, "parts": ["Kazoo"]})

        assert data["error_code"] == "INVALID_PARAMETER"

    async def test_measures_filter_the_changes(self):
        outside = await _structured({**PAIR, "detail": "changes", "measures": [2, 3]})
        inside = await _structured({**PAIR, "detail": "changes", "measures": [1, 1]})

        assert outside["changes"] == []
        assert inside["count"] == 1

    async def test_bad_measures_is_invalid_parameter(self):
        data = await _error_code({**PAIR, "measures": [5, 2]})

        assert data["error_code"] == "INVALID_PARAMETER"
        assert data["error"].startswith("measures ")

    async def test_options_are_passed_on(self):
        data = await _structured({**PAIR, "detail": "full", "options": {"parts": ["Alto"]}})

        assert [pd["part_name"] for pd in data["part_diffs"]] == ["Alto"]

    async def test_conflicting_top_level_and_option_filters(self):
        data = await _error_code({**PAIR, "parts": ["Alto"], "options": {"parts": ["Soprano"]}})

        assert data["error_code"] == "INVALID_PARAMETER"

    async def test_same_filter_in_both_places_is_fine(self):
        data = await _structured({**PAIR, "measures": [1, 1], "options": {"measures": [1, 1]}})

        assert data["detail"] == "summary"


class TestDeprecatedAliases:
    @pytest.mark.parametrize(
        ("name", "detail"),
        [
            ("compare_musicxml", "full"),
            ("compare_musicxml_files", "full"),
            ("quick_similarity", "summary"),
            ("list_changes", "changes"),
            ("generate_comparison_report", "report"),
        ],
    )
    async def test_description_says_deprecated(self, name, detail):
        description = (await _tool(name)).description

        assert description.startswith(f'Deprecated: use compare_scores(detail="{detail}")')

    async def test_alias_still_works_and_logs_once(self, caplog):
        server._warned_tools.clear()
        with caplog.at_level("WARNING"):
            await call_tool("quick_similarity", PAIR)
            await call_tool("quick_similarity", PAIR)

        warnings = [r for r in caplog.records if "compare_scores" in r.getMessage()]
        assert len(warnings) == 1
        assert "quick_similarity" in warnings[0].getMessage()

    async def test_alias_output_shapes_are_unchanged(self):
        similarity = json.loads((await call_tool("quick_similarity", PAIR))[0].text)
        changes = json.loads((await call_tool("list_changes", PAIR))[0].text)

        assert set(similarity) == {"similarity_score", "summary"}
        assert set(changes) == {"changes", "count"}

    async def test_new_tool_agrees_with_the_aliases(self):
        similarity = json.loads((await call_tool("quick_similarity", PAIR))[0].text)
        changes = json.loads((await call_tool("list_changes", PAIR))[0].text)
        full = await _structured({**PAIR, "detail": "full"})

        assert full["similarity_score"] == similarity["similarity_score"]
        assert full["summary"] == similarity["summary"]
        assert full["changes"] == changes["changes"]
