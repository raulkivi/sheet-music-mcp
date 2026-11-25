"""Scores reach the Diff Viewer by an opaque diff_id: compare_scores returns it, two app-only tools use it."""

import json

import jsonschema
import pytest
from sheet_music_mcp_core.annotations import READ_ONLY, WRITES_FILE
from sheet_music_mcp_core.ui import is_app_only

import comparer_mcp.server as server
from comparer_mcp.server import call_tool_result, list_tools

from .test_server import REFERENCE_XML, TARGET_XML

PAIR = {"reference_xml": REFERENCE_XML, "target_xml": TARGET_XML}


async def _tool(name):
    return next(t for t in await list_tools() if t.name == name)


async def _diff_id(**extra):
    result = await call_tool_result("compare_scores", {**PAIR, "detail": "changes", **extra})
    assert not result.is_error
    return result.structured_content["diff_id"]


class TestDiffIdOnCompareScores:
    async def test_is_returned_when_the_viewer_is_packaged(self, packaged_ui):
        result = await call_tool_result("compare_scores", {**PAIR, "detail": "changes"})

        diff_id = result.structured_content["diff_id"]
        assert isinstance(diff_id, str) and diff_id
        assert json.loads(result.content[0].text)["diff_id"] == diff_id
        jsonschema.validate(result.structured_content, (await _tool("compare_scores")).output_schema)

    async def test_is_absent_without_a_ui_build(self):
        result = await call_tool_result("compare_scores", {**PAIR, "detail": "changes"})

        assert "diff_id" not in result.structured_content

    async def test_each_call_gets_its_own_id(self, packaged_ui):
        assert await _diff_id() != await _diff_id()


class TestGetDiffScores:
    async def test_definition(self, packaged_ui):
        tool = await _tool("get_diff_scores")

        assert is_app_only(tool)
        assert tool.meta["ui"]["resourceUri"] == "ui://comparer/diff-viewer"
        assert tool.title
        assert tool.annotations.model_dump(exclude_none=True) == dict(READ_ONLY)
        assert tool.output_schema
        assert tool.input_schema["required"] == ["diff_id"]
        assert tool.input_schema["additionalProperties"] is False

    async def test_app_only_even_without_a_ui_build(self):
        assert is_app_only(await _tool("get_diff_scores"))

    async def test_returns_both_scores_with_the_diff_colors(self, packaged_ui):
        result = await call_tool_result("get_diff_scores", {"diff_id": await _diff_id()})

        assert not result.is_error, result.content[0].text
        data = result.structured_content
        jsonschema.validate(data, (await _tool("get_diff_scores")).output_schema)
        assert "<score-partwise" in data["reference_musicxml"]
        assert "<score-partwise" in data["target_musicxml"]
        assert data["legend"]["PITCH_CHANGE"].startswith("#")
        assert data["legend"]["PITCH_CHANGE"].lower() in data["target_musicxml"].lower()

    async def test_honours_the_comparison_options(self, packaged_ui):
        diff_id = await _diff_id(measures=[99, 100])

        data = (await call_tool_result("get_diff_scores", {"diff_id": diff_id})).structured_content

        assert data["legend"]["PITCH_CHANGE"].lower() not in data["target_musicxml"].lower()

    @pytest.mark.parametrize("bad", ["nope", "../../etc/passwd"])
    async def test_unknown_id_is_an_invalid_parameter_error(self, bad):
        result = await call_tool_result("get_diff_scores", {"diff_id": bad})

        assert result.is_error
        assert result.structured_content is None
        envelope = json.loads(result.content[0].text)
        assert envelope["error_code"] == "INVALID_PARAMETER"
        assert "passwd" not in envelope["error"]


class TestExportDiffScores:
    @pytest.fixture(autouse=True)
    def output_root(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
        return tmp_path

    async def test_definition(self, packaged_ui):
        tool = await _tool("export_diff_scores")

        assert is_app_only(tool)
        assert tool.title
        assert tool.annotations.model_dump(exclude_none=True) == dict(WRITES_FILE)
        assert tool.output_schema
        assert tool.input_schema["required"] == ["diff_id"]

    async def test_writes_both_annotated_scores_and_returns_their_paths(self, packaged_ui, output_root):
        result = await call_tool_result("export_diff_scores", {"diff_id": await _diff_id()})

        assert not result.is_error, result.content[0].text
        data = result.structured_content
        jsonschema.validate(data, (await _tool("export_diff_scores")).output_schema)
        for key in ("reference_annotated_musicxml_path", "target_annotated_musicxml_path"):
            assert (output_root / "scores").exists()
            assert data[key].endswith(".musicxml")
            assert data[key].startswith(str(output_root))
        assert any(block.type == "resource_link" for block in result.content)

    async def test_unknown_id_is_an_invalid_parameter_error(self):
        result = await call_tool_result("export_diff_scores", {"diff_id": "nope"})

        assert result.is_error
        assert json.loads(result.content[0].text)["error_code"] == "INVALID_PARAMETER"


def test_the_diff_book_is_the_servers():
    assert server.diff_book is not None
