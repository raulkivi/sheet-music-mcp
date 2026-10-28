"""``render_page_svg``: the app-only tool behind the Score Viewer's server-side fallback.

The viewer calls it when the host refuses to compile Verovio's WebAssembly (the MCP Apps default
CSP has no 'wasm-unsafe-eval'). It takes inline MusicXML only, never a path (proposal §7).
"""

import asyncio
import json

import pytest
from mcp import Client
from mcp.client import advertise
from sheet_music_mcp_core.annotations import READ_ONLY
from sheet_music_mcp_core.ui import UI_EXTENSION, UI_MIME

import render_mcp.server as server
from render_mcp.engine import SvgPageRenderer
from render_mcp.server import app, call_tool_result, list_tools

from .test_page_svg import long_score
from .test_server import VALID_MUSICXML

UI_CLIENT = {"extensions": [advertise(UI_EXTENSION, {"mimeTypes": [UI_MIME]})]}
ARGS = {"musicxml": VALID_MUSICXML, "page": 1, "width_px": 1000, "zoom": 1}


@pytest.fixture(autouse=True)
def fresh_renderer(monkeypatch):
    monkeypatch.setattr(server, "page_renderer", SvgPageRenderer())


def _with_client(call, **client_kwargs):
    async def _go():
        async with Client(app, **client_kwargs) as client:
            return await call(client)

    return asyncio.run(_go())


async def _tool():
    return next(t for t in await list_tools() if t.name == "render_page_svg")


class TestDefinition:
    async def test_is_app_only_and_linked_to_the_viewer_when_packaged(self, packaged_ui):
        assert (await _tool()).meta == {
            "ui": {"resourceUri": "ui://render/score-viewer", "visibility": ["app"]}
        }

    async def test_stays_app_only_without_a_ui_build(self):
        assert (await _tool()).meta == {"ui": {"visibility": ["app"]}}

    async def test_title_and_read_only_preset(self):
        tool = await _tool()

        assert tool.title == "Render score page as SVG"
        assert tool.annotations.model_dump(exclude_none=True) == dict(READ_ONLY)

    async def test_takes_inline_musicxml_and_no_path(self):
        schema = (await _tool()).input_schema

        assert set(schema["properties"]) == {"musicxml", "page", "width_px", "zoom"}
        assert set(schema["required"]) == {"musicxml", "page", "width_px", "zoom"}
        assert schema["additionalProperties"] is False
        assert schema["properties"]["page"]["minimum"] == 1

    async def test_declares_its_output(self):
        schema = (await _tool()).output_schema

        assert set(schema["required"]) == {"svg", "page", "page_count"}


class TestVisibility:
    def test_hidden_from_clients_without_ui(self):
        names = {t.name for t in _with_client(lambda c: c.list_tools()).tools}

        assert "render_page_svg" not in names
        assert "render_to_pdf" in names

    def test_listed_for_ui_clients(self):
        names = {t.name for t in _with_client(lambda c: c.list_tools(), **UI_CLIENT).tools}

        assert "render_page_svg" in names


class TestCall:
    def test_returns_the_page_svg_as_structured_content(self):
        result = _with_client(lambda c: c.call_tool("render_page_svg", ARGS), **UI_CLIENT)

        assert not result.is_error
        data = result.structured_content
        assert data["svg"].lstrip().startswith("<svg")
        assert (data["page"], data["page_count"]) == (1, 1)

    def test_text_content_is_short_and_leaves_the_svg_out(self):
        result = _with_client(lambda c: c.call_tool("render_page_svg", ARGS), **UI_CLIENT)

        [block] = result.content
        assert block.text.startswith("Page 1 of 1 rendered as SVG")
        assert "<svg" not in block.text
        assert len(block.text) < 200

    async def test_pages_through_a_long_score(self):
        score = long_score()
        first = await call_tool_result("render_page_svg", {**ARGS, "musicxml": score})
        count = first.structured_content["page_count"]

        last = await call_tool_result("render_page_svg", {**ARGS, "musicxml": score, "page": count})

        assert count > 1
        assert last.structured_content["page"] == count

    async def test_page_past_the_end_is_invalid_parameter_with_the_range(self):
        result = await call_tool_result("render_page_svg", {**ARGS, "page": 4})

        assert result.is_error
        assert result.structured_content is None
        assert json.loads(result.content[0].text) == {
            "error": "Page 4 is out of range.",
            "error_code": "INVALID_PARAMETER",
            "hint": "This score has pages 1–1 at this width and zoom.",
        }

    async def test_not_a_score_is_invalid_input(self):
        result = await call_tool_result("render_page_svg", {**ARGS, "musicxml": "<nope/>"})

        assert result.is_error
        assert json.loads(result.content[0].text)["error_code"] == "INVALID_INPUT"

    @pytest.mark.parametrize(
        "change",
        [
            {"page": 0},
            {"width_px": 0},
            {"zoom": 0},
            {"musicxml_path": "/etc/passwd"},
        ],
    )
    def test_schema_rejects_bad_arguments_and_paths(self, change):
        result = _with_client(lambda c: c.call_tool("render_page_svg", {**ARGS, **change}), **UI_CLIENT)

        assert result.is_error
        assert json.loads(result.content[0].text)["error_code"] == "INVALID_PARAMETER"
