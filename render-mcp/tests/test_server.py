"""Tests for render_mcp MCP server — tool schemas, list_capabilities, error propagation."""

import json
from unittest.mock import patch

import pytest

from render_mcp.server import call_tool, list_tools

VALID_MUSICXML = """\
<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Soprano</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <note>
        <pitch><step>C</step><octave>5</octave></pitch>
        <duration>4</duration><type>whole</type>
      </note>
    </measure>
  </part>
</score-partwise>"""


# ---------------------------------------------------------------------------
# Tool schema tests
# ---------------------------------------------------------------------------

class TestToolSchemas:
    async def test_all_expected_tools_registered(self):
        tools = await list_tools()
        names = [t.name for t in tools]
        assert "render_to_pdf" in names
        assert "render_to_image" in names
        assert "list_capabilities" in names

    async def test_render_to_pdf_schema(self):
        tools = await list_tools()
        tool = next(t for t in tools if t.name == "render_to_pdf")
        schema = tool.input_schema
        assert "musicxml" in schema["properties"]
        assert schema["required"] == ["musicxml"]

    async def test_render_to_image_schema(self):
        tools = await list_tools()
        tool = next(t for t in tools if t.name == "render_to_image")
        schema = tool.input_schema
        assert "musicxml" in schema["properties"]
        assert "page" in schema["properties"]
        assert "format" in schema["properties"]
        assert "dpi" in schema["properties"]
        assert "output_path" in schema["properties"]
        assert schema["required"] == ["musicxml"]

    async def test_list_capabilities_schema(self):
        tools = await list_tools()
        tool = next(t for t in tools if t.name == "list_capabilities")
        assert tool.input_schema["properties"] == {}
        assert tool.input_schema["required"] == []


# ---------------------------------------------------------------------------
# list_capabilities
# ---------------------------------------------------------------------------

class TestListCapabilities:
    async def test_returns_required_fields(self):
        result = await call_tool("list_capabilities", {})
        assert len(result) == 1
        data = json.loads(result[0].text)

        assert data["server"] == "render-mcp"
        assert data["version"] == "0.1.2"
        assert "musicxml" in data["input_formats"]
        assert "pdf" in data["output_formats"]
        assert "png" in data["output_formats"]
        assert "svg" in data["output_formats"]
        assert "render_to_pdf" in data["tools"]
        assert "render_to_image" in data["tools"]
        assert "list_capabilities" in data["tools"]
        assert "musescore_available" in data
        assert "verovio_available" in data

    async def test_verovio_shown_as_available(self):
        result = await call_tool("list_capabilities", {})
        data = json.loads(result[0].text)
        assert data["verovio_available"] is True

    async def test_backend_field_present(self):
        result = await call_tool("list_capabilities", {})
        data = json.loads(result[0].text)
        assert "backend" in data


# ---------------------------------------------------------------------------
# render_to_pdf — parameter validation
# ---------------------------------------------------------------------------

class TestRenderToPdfValidation:
    async def test_invalid_musicxml_returns_invalid_input(self):
        result = await call_tool("render_to_pdf", {"musicxml": "bad xml"})
        data = json.loads(result[0].text)
        assert "error" in data
        assert data["error_code"] == "INVALID_INPUT"

    async def test_empty_musicxml_returns_error(self):
        result = await call_tool("render_to_pdf", {"musicxml": ""})
        data = json.loads(result[0].text)
        assert "error" in data

    async def test_no_backend_returns_processing_failed(self):
        with (
            patch("render_mcp.engine._MUSESCORE_CMD", None),
            patch("render_mcp.engine._VEROVIO_AVAILABLE", False),
        ):
            result = await call_tool("render_to_pdf", {"musicxml": VALID_MUSICXML})
        data = json.loads(result[0].text)
        assert "error" in data
        assert data["error_code"] == "PROCESSING_FAILED"


# ---------------------------------------------------------------------------
# render_to_image — parameter validation
# ---------------------------------------------------------------------------

class TestRenderToImageValidation:
    async def test_invalid_musicxml_returns_invalid_input(self):
        result = await call_tool("render_to_image", {"musicxml": "bad xml"})
        data = json.loads(result[0].text)
        assert "error" in data
        assert data["error_code"] == "INVALID_INPUT"

    async def test_page_zero_returns_invalid_parameter(self):
        result = await call_tool(
            "render_to_image", {"musicxml": VALID_MUSICXML, "page": 0}
        )
        data = json.loads(result[0].text)
        assert "error" in data
        assert data["error_code"] == "INVALID_PARAMETER"

    async def test_negative_page_returns_invalid_parameter(self):
        result = await call_tool(
            "render_to_image", {"musicxml": VALID_MUSICXML, "page": -5}
        )
        data = json.loads(result[0].text)
        assert "error" in data
        assert data["error_code"] == "INVALID_PARAMETER"

    async def test_invalid_format_returns_invalid_parameter(self):
        result = await call_tool(
            "render_to_image", {"musicxml": VALID_MUSICXML, "format": "jpg"}
        )
        data = json.loads(result[0].text)
        assert "error" in data
        assert data["error_code"] == "INVALID_PARAMETER"

    async def test_dpi_too_low_returns_invalid_parameter(self):
        result = await call_tool(
            "render_to_image", {"musicxml": VALID_MUSICXML, "dpi": 10}
        )
        data = json.loads(result[0].text)
        assert "error" in data
        assert data["error_code"] == "INVALID_PARAMETER"

    async def test_dpi_too_high_returns_invalid_parameter(self):
        result = await call_tool(
            "render_to_image", {"musicxml": VALID_MUSICXML, "dpi": 1200}
        )
        data = json.loads(result[0].text)
        assert "error" in data
        assert data["error_code"] == "INVALID_PARAMETER"

    async def test_empty_musicxml_returns_error(self):
        result = await call_tool("render_to_image", {"musicxml": ""})
        data = json.loads(result[0].text)
        assert "error" in data

    async def test_no_backend_returns_processing_failed(self):
        with (
            patch("render_mcp.engine._MUSESCORE_CMD", None),
            patch("render_mcp.engine._VEROVIO_AVAILABLE", False),
        ):
            result = await call_tool("render_to_image", {"musicxml": VALID_MUSICXML})
        data = json.loads(result[0].text)
        assert "error" in data
        assert data["error_code"] == "PROCESSING_FAILED"


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

class TestHealthCheck:
    async def test_health_check_registered(self):
        tools = await list_tools()
        names = [t.name for t in tools]
        assert "health_check" in names

    async def test_health_check_returns_text(self):
        result = await call_tool("health_check", {})
        assert len(result) == 1
        assert result[0].type == "text"
        text = result[0].text
        assert "render-mcp status:" in text

    async def test_health_check_ok_when_verovio_available(self):
        with patch("render_mcp.engine._VEROVIO_AVAILABLE", True):
            result = await call_tool("health_check", {})
        text = result[0].text
        assert "OK" in text or "ok" in text.lower()

    async def test_health_check_degraded_when_no_backend(self):
        with (
            patch("render_mcp.engine._MUSESCORE_CMD", None),
            patch("render_mcp.engine._VEROVIO_AVAILABLE", False),
        ):
            result = await call_tool("health_check", {})
        text = result[0].text
        assert "DEGRADED" in text

    async def test_health_check_warns_cairosvg_missing(self):
        with (
            patch("render_mcp.engine._VEROVIO_AVAILABLE", True),
            patch("render_mcp.engine._CAIROSVG_AVAILABLE", False),
        ):
            result = await call_tool("health_check", {})
        text = result[0].text
        assert "cairosvg" in text
        assert "Warnings:" in text


class TestMisc:
    async def test_unknown_tool_raises(self):
        with pytest.raises(ValueError, match="Unknown tool"):
            await call_tool("nonexistent_tool", {})
