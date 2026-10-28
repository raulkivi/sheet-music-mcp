"""Diff Viewer linking: the ``ui://comparer/diff-viewer`` resource, tool ``_meta``,
``structuredContent`` and output schemas (proposal 5.4, AC-C1)."""

import asyncio
import json

import jsonschema
import pytest
from mcp import Client, MCPError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS
from sheet_music_mcp_core.ui import UI_MIME, is_app_only

from comparer_mcp.engine import compare
from comparer_mcp.models import ComparisonResult
from comparer_mcp.presenter import (
    COMPARISON_OUTPUT_SCHEMA,
    REPORT_OUTPUT_SCHEMA,
    present_comparison,
    present_report,
)
from comparer_mcp.result_schema import json_schema_for
from comparer_mcp.server import app, call_tool_result, list_tools

from .conftest import VIEWER_HTML
from .test_server import REFERENCE_XML, TARGET_XML

VIEWER_URI = "ui://comparer/diff-viewer"
LINKED = ("compare_musicxml", "compare_musicxml_files", "generate_comparison_report")
PAIR = {"reference_xml": REFERENCE_XML, "target_xml": TARGET_XML}


def _with_client(call):
    async def _go():
        async with Client(app) as client:
            return await call(client)

    return asyncio.run(_go())


async def _tools():
    return {tool.name: tool for tool in await list_tools()}


class TestToolLinking:
    @pytest.mark.parametrize("name", LINKED)
    async def test_tools_link_the_viewer_when_packaged(self, packaged_ui, name):
        assert (await _tools())[name].meta == {"ui": {"resourceUri": VIEWER_URI}}

    @pytest.mark.parametrize("name", LINKED)
    async def test_no_link_without_a_ui_build(self, name):
        assert (await _tools())[name].meta is None

    async def test_other_tools_are_not_linked(self, packaged_ui):
        others = [t for n, t in (await _tools()).items() if n not in LINKED]

        assert others
        assert all(t.meta is None for t in others)

    async def test_there_are_no_app_only_tools(self, packaged_ui):
        # list_changes and export_annotated_musicxml are model-facing and app-callable (default
        # visibility), so the viewer needs no helper tool.
        assert not any(is_app_only(t) for t in (await _tools()).values())

    async def test_linked_tools_declare_output_schemas(self):
        tools = await _tools()

        assert tools["compare_musicxml"].output_schema == COMPARISON_OUTPUT_SCHEMA
        assert tools["compare_musicxml_files"].output_schema == COMPARISON_OUTPUT_SCHEMA
        assert tools["generate_comparison_report"].output_schema == REPORT_OUTPUT_SCHEMA

    async def test_unstructured_tools_declare_none(self):
        tools = await _tools()

        for name in ("quick_similarity", "list_changes", "export_annotated_musicxml"):
            assert tools[name].output_schema is None


class TestResources:
    def test_lists_the_viewer_when_packaged(self, packaged_ui):
        result = _with_client(lambda c: c.list_resources())

        assert [(r.uri, r.name, r.mime_type) for r in result.resources] == [
            (VIEWER_URI, "Diff Viewer", UI_MIME)
        ]

    def test_lists_nothing_without_a_ui_build(self):
        assert _with_client(lambda c: c.list_resources()).resources == []

    def test_reads_the_viewer_html(self, packaged_ui):
        [contents] = _with_client(lambda c: c.read_resource(VIEWER_URI)).contents

        assert (contents.uri, contents.mime_type, contents.text) == (VIEWER_URI, UI_MIME, VIEWER_HTML)

    def test_missing_build_is_an_error_naming_the_fix(self):
        async def read(client):
            with pytest.raises(MCPError) as caught:
                await client.read_resource(VIEWER_URI)
            return caught.value

        error = _with_client(read)

        assert error.code == INTERNAL_ERROR
        assert error.data["error_code"] == "UI_ASSET_MISSING"

    def test_unknown_resource_is_invalid_params(self, packaged_ui):
        async def read(client):
            with pytest.raises(MCPError) as caught:
                await client.read_resource("ui://comparer/nope")
            return caught.value

        assert _with_client(read).code == INVALID_PARAMS


class TestResultSchema:
    def test_is_generated_from_the_dataclasses(self):
        schema = json_schema_for(ComparisonResult)

        assert schema == COMPARISON_OUTPUT_SCHEMA
        assert schema["type"] == "object"
        assert set(schema["required"]) == {"similarity_score", "summary", "part_diffs"}

    def test_optional_fields_accept_null(self):
        note = json_schema_for(ComparisonResult)["properties"]["part_diffs"]["items"]["properties"][
            "measure_diffs"
        ]["items"]["properties"]["note_diffs"]["items"]["properties"]

        assert note["reference"]["anyOf"][1] == {"type": "null"}
        assert note["interval_error"]["anyOf"] == [{"type": "integer"}, {"type": "null"}]
        assert note["operation"] == {"type": "string"}

    def test_validates_a_real_result(self):
        result = compare(REFERENCE_XML, TARGET_XML)

        jsonschema.validate(result.to_dict(), COMPARISON_OUTPUT_SCHEMA)

    def test_rejects_a_result_missing_a_field(self):
        data = compare(REFERENCE_XML, TARGET_XML).to_dict()
        del data["summary"]

        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(data, COMPARISON_OUTPUT_SCHEMA)


class TestPresenter:
    def test_comparison_content_is_the_original_json_and_structured_the_result(self):
        result = compare(REFERENCE_XML, TARGET_XML)

        content, structured = present_comparison(result)

        assert content[0].text == json.dumps(result.to_dict(), indent=2)
        assert structured == result.to_dict()

    def test_report_structured_equals_content(self):
        payload = {"report": "Overall similarity: 96%", "similarity_score": 0.95625}

        content, structured = present_report(payload)

        assert content[0].text == json.dumps(payload, indent=2)
        assert structured == payload
        jsonschema.validate(structured, REPORT_OUTPUT_SCHEMA)


class TestStructuredContent:
    @pytest.mark.parametrize("tool", ("compare_musicxml", "compare_musicxml_files"))
    def test_comparison_validates_against_the_output_schema(self, tool, tmp_path, monkeypatch):
        monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
        (tmp_path / "a.musicxml").write_text(REFERENCE_XML, encoding="utf-8")
        (tmp_path / "b.musicxml").write_text(TARGET_XML, encoding="utf-8")
        arguments = {"reference_path": str(tmp_path / "a.musicxml"), "target_path": str(tmp_path / "b.musicxml")}

        result = _with_client(lambda c: c.call_tool(tool, arguments))

        assert not result.is_error
        jsonschema.validate(result.structured_content, COMPARISON_OUTPUT_SCHEMA)
        assert result.structured_content == json.loads(result.content[0].text)
        assert result.structured_content["summary"]["notes_pitch_changed"] == 1

    def test_report_carries_text_and_similarity(self):
        result = _with_client(lambda c: c.call_tool("generate_comparison_report", PAIR))

        assert not result.is_error
        assert result.structured_content == json.loads(result.content[0].text)
        assert result.structured_content["report"].startswith("Overall similarity")

    @pytest.mark.parametrize("tool", ("quick_similarity", "list_changes", "export_annotated_musicxml"))
    def test_other_tools_return_no_structured_content(self, tool):
        result = _with_client(lambda c: c.call_tool(tool, PAIR))

        assert not result.is_error
        assert result.structured_content is None


class TestErrors:
    @pytest.mark.parametrize(
        "tool, arguments, code",
        [
            ("compare_musicxml", {"reference_xml": "<nope/>", "target_xml": TARGET_XML}, "INVALID_INPUT"),
            ("compare_musicxml", {"reference_xml": REFERENCE_XML}, "INVALID_PARAMETER"),
            ("compare_musicxml_files", {"target_path": "/x"}, "INVALID_PARAMETER"),
            ("generate_comparison_report", {"reference_xml": "<nope/>", "target_xml": TARGET_XML}, "INVALID_INPUT"),
            ("list_changes", {**PAIR, "part": "Tuba"}, "INVALID_PARAMETER"),
            ("export_annotated_musicxml", {"reference_xml": "<nope/>", "target_xml": TARGET_XML}, "INVALID_INPUT"),
        ],
    )
    def test_keep_the_envelope_and_carry_no_structured_content(self, tool, arguments, code):
        result = _with_client(lambda c: c.call_tool(tool, arguments))

        assert result.is_error
        assert result.structured_content is None
        assert json.loads(result.content[0].text)["error_code"] == code

    async def test_call_tool_result_marks_errors(self):
        result = await call_tool_result("compare_musicxml", {"reference_xml": "<nope/>", "target_xml": TARGET_XML})

        assert result.is_error
