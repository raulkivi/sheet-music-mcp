"""Score Viewer linking: the ``ui://render/score-viewer`` resource, tool ``_meta`` and
``structuredContent`` (docs/research/mcp-apps-phase0-spike-plan.md, DoD-2 to DoD-4)."""

import asyncio
import json
from pathlib import Path

import pytest
from mcp import Client, MCPError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS
from sheet_music_mcp_core.ui import UI_MIME, is_app_only

import render_mcp.server as server
from render_mcp.engine import ProcessingError
from render_mcp.server import app, call_tool_result, list_tools

from .conftest import VIEWER_HTML
from .test_result_content import TINY_PNG, _fake_render_to_image, _fake_render_to_pdf
from .test_server import VALID_MUSICXML

VIEWER_URI = "ui://render/score-viewer"
LINKED = ("render_to_pdf", "render_to_image")


@pytest.fixture(autouse=True)
def output_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def engines(monkeypatch):
    monkeypatch.setattr(server, "render_to_image", _fake_render_to_image(TINY_PNG))
    monkeypatch.setattr(server, "render_to_pdf", _fake_render_to_pdf)
    monkeypatch.setattr(server, "detect_backend", lambda: "verovio")


def _with_client(call):
    async def _go():
        async with Client(app) as client:
            return await call(client)

    return asyncio.run(_go())


def _read_error(uri):
    async def read(client):
        try:
            await client.read_resource(uri)
        except MCPError as e:
            return e
        raise AssertionError("read_resource did not raise")

    return _with_client(read)


async def _tools():
    return {tool.name: tool for tool in await list_tools()}


class TestToolLinking:
    @pytest.mark.parametrize("name", LINKED)
    async def test_render_tools_link_the_viewer_when_packaged(self, packaged_ui, name):
        assert (await _tools())[name].meta == {"ui": {"resourceUri": VIEWER_URI}}

    @pytest.mark.parametrize("name", LINKED)
    async def test_no_link_without_a_ui_build(self, name):
        assert (await _tools())[name].meta is None

    async def test_other_model_facing_tools_are_not_linked(self, packaged_ui):
        others = [t for name, t in (await _tools()).items() if name not in LINKED and not is_app_only(t)]

        assert others
        assert all(t.meta is None or "resourceUri" not in t.meta.get("ui", {}) for t in others)

    def test_link_reaches_the_client_as_meta(self, packaged_ui):
        result = _with_client(lambda c: c.list_tools())

        tool = next(t for t in result.tools if t.name == "render_to_pdf")
        assert tool.meta["ui"]["resourceUri"] == VIEWER_URI

    @pytest.mark.parametrize("name", LINKED)
    async def test_render_tools_declare_an_output_schema(self, name):
        schema = (await _tools())[name].output_schema

        assert schema["type"] == "object"
        assert schema["required"]


class TestResources:
    def test_lists_the_viewer_when_packaged(self, packaged_ui):
        result = _with_client(lambda c: c.list_resources())

        assert [(r.uri, r.name, r.mime_type) for r in result.resources] == [
            (VIEWER_URI, "Score Viewer", UI_MIME)
        ]

    def test_lists_nothing_without_a_ui_build(self):
        assert _with_client(lambda c: c.list_resources()).resources == []

    def test_reads_the_viewer_html(self, packaged_ui):
        result = _with_client(lambda c: c.read_resource(VIEWER_URI))

        [contents] = result.contents
        assert (contents.uri, contents.mime_type, contents.text) == (VIEWER_URI, UI_MIME, VIEWER_HTML)

    def test_missing_build_is_an_error_naming_the_fix(self):
        error = _read_error(VIEWER_URI)

        assert error.code == INTERNAL_ERROR
        assert error.data["error_code"] == "UI_ASSET_MISSING"
        assert "npm run build" in error.message

    def test_unknown_resource_is_invalid_params(self, packaged_ui):
        error = _read_error("ui://render/nope")

        assert error.code == INVALID_PARAMS
        assert error.data["error_code"] == "RESOURCE_NOT_FOUND"


class TestStructuredContent:
    def test_pdf_result_carries_structured_content(self, engines, output_root):
        out = str(output_root / "score.pdf")

        # The client validates structured_content against the tool's output_schema.
        result = _with_client(
            lambda c: c.call_tool("render_to_pdf", {"musicxml": VALID_MUSICXML, "output_path": out})
        )

        assert not result.is_error
        assert result.structured_content == {"pdf_path": out, "page_count": 2, "backend": "verovio"}
        assert json.loads(result.content[0].text) == result.structured_content

    def test_image_result_carries_structured_content(self, engines, output_root):
        out = str(output_root / "page.png")

        result = _with_client(
            lambda c: c.call_tool("render_to_image", {"musicxml": VALID_MUSICXML, "output_path": out})
        )

        assert not result.is_error
        data = result.structured_content
        assert (data["image_path"], data["format"], data["page"]) == (out, "png", 1)
        assert (data["width_px"], data["height_px"]) == (1, 1)
        assert [b.type for b in result.content] == ["text", "image", "resource_link"]

    @pytest.mark.parametrize(
        "tool, arguments",
        [
            ("render_to_pdf", {"musicxml": "<nope/>"}),
            ("render_to_image", {"musicxml": VALID_MUSICXML, "page": 0}),
            ("render_to_image", {"musicxml_path": "/no/such/file.musicxml"}),
        ],
    )
    def test_errors_keep_the_envelope_and_carry_no_structured_content(self, tool, arguments):
        result = _with_client(lambda c: c.call_tool(tool, arguments))

        # isError results are exempt from output_schema validation, as the spec allows.
        assert result.is_error
        assert result.structured_content is None
        assert {"error", "error_code"} <= set(json.loads(result.content[0].text))

    async def test_engine_errors_are_error_results(self, monkeypatch):
        def fail(*args, **kwargs):
            raise ProcessingError("no backend", "PROCESSING_FAILED")

        monkeypatch.setattr(server, "render_to_pdf", fail)

        result = await call_tool_result("render_to_pdf", {"musicxml": VALID_MUSICXML})

        assert result.is_error
        assert result.structured_content is None

    async def test_other_tools_keep_plain_results(self):
        result = await call_tool_result("list_capabilities", {})

        assert not result.is_error
        assert result.structured_content is None
        assert json.loads(result.content[0].text)["server"] == "render-mcp"

    async def test_output_file_exists_for_the_link(self, engines, output_root):
        out = output_root / "score.pdf"

        result = await call_tool_result("render_to_pdf", {"musicxml": VALID_MUSICXML, "output_path": str(out)})

        assert Path(result.structured_content["pdf_path"]) == out
        assert result.content[-1].uri == out.resolve().as_uri()
