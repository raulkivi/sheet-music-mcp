"""MCP protocol and tool schema tests for musicxml-abc-mcp."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from musicxml_abc_mcp.server import app, call_tool, list_tools

MINIMAL_MUSICXML = """\
<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <work><work-title>Test Score</work-title></work>
  <part-list>
    <score-part id="P1"><part-name>Soprano</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>4</divisions>
        <key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <note>
        <pitch><step>C</step><octave>4</octave></pitch>
        <duration>4</duration><type>quarter</type>
      </note>
    </measure>
  </part>
</score-partwise>
"""

MINIMAL_ABC = "X:1\nT:Test\nM:4/4\nL:1/8\nK:C\nCDEF GABC|]"


class TestListTools:
    async def test_returns_five_tools(self):
        tools = await list_tools()
        names = {t.name for t in tools}
        assert names == {
            "musicxml_to_abc",
            "abc_to_musicxml",
            "validate_abc",
            "list_capabilities",
            "health_check",
        }

    async def test_musicxml_to_abc_schema(self):
        tools = await list_tools()
        tool = next(t for t in tools if t.name == "musicxml_to_abc")
        schema = tool.input_schema
        assert "musicxml" in schema["properties"]
        assert "musicxml" in schema["required"]
        # part_id is optional
        assert "part_id" in schema["properties"]
        assert "part_id" not in schema.get("required", [])

    async def test_abc_to_musicxml_schema(self):
        tools = await list_tools()
        tool = next(t for t in tools if t.name == "abc_to_musicxml")
        schema = tool.input_schema
        assert "abc" in schema["properties"]
        assert "abc" in schema["required"]

    async def test_validate_abc_schema(self):
        tools = await list_tools()
        tool = next(t for t in tools if t.name == "validate_abc")
        schema = tool.input_schema
        assert "abc" in schema["properties"]

    async def test_list_capabilities_schema(self):
        tools = await list_tools()
        tool = next(t for t in tools if t.name == "list_capabilities")
        schema = tool.input_schema
        assert schema["required"] == []


class TestCallToolListCapabilities:
    async def test_list_capabilities_structure(self):
        result = await call_tool("list_capabilities", {})
        payload = json.loads(result[0].text)
        assert payload["server"] == "musicxml-abc-mcp"
        assert payload["version"] == "0.1.2"
        assert "musicxml" in payload["input_formats"]
        assert "abc" in payload["input_formats"]
        assert "abc" in payload["output_formats"]
        assert "musicxml" in payload["output_formats"]
        assert set(payload["tools"]) == {
            "musicxml_to_abc",
            "abc_to_musicxml",
            "validate_abc",
            "list_capabilities",
            "health_check",
        }
        assert payload["backend"] == "music21"
        assert "backend_version" in payload


class TestCallToolMusicxmlToAbc:
    async def test_valid_musicxml_returns_abc(self):
        result = await call_tool("musicxml_to_abc", {"musicxml": MINIMAL_MUSICXML})
        payload = json.loads(result[0].text)
        assert "abc" in payload
        assert "parts_included" in payload
        assert "warnings" in payload
        assert "X:1" in payload["abc"]

    async def test_empty_musicxml_returns_error(self):
        result = await call_tool("musicxml_to_abc", {"musicxml": ""})
        payload = json.loads(result[0].text)
        assert "error" in payload
        assert "error_code" in payload

    async def test_invalid_musicxml_returns_error(self):
        result = await call_tool("musicxml_to_abc", {"musicxml": "<foo/>"})
        payload = json.loads(result[0].text)
        assert "error" in payload
        assert payload["error_code"] == "INVALID_INPUT"

    async def test_invalid_part_id_returns_error(self):
        result = await call_tool(
            "musicxml_to_abc", {"musicxml": MINIMAL_MUSICXML, "part_id": "INVALID"}
        )
        payload = json.loads(result[0].text)
        assert "error" in payload
        assert payload["error_code"] == "INVALID_PARAMETER"

    async def test_valid_part_id_works(self):
        result = await call_tool(
            "musicxml_to_abc", {"musicxml": MINIMAL_MUSICXML, "part_id": "Soprano"}
        )
        payload = json.loads(result[0].text)
        assert "abc" in payload
        assert payload["parts_included"] == ["Soprano"]


class TestCallToolAbcToMusicxml:
    async def test_valid_abc_returns_musicxml(self):
        result = await call_tool("abc_to_musicxml", {"abc": MINIMAL_ABC})
        payload = json.loads(result[0].text)
        assert "musicxml" in payload
        assert "<score-partwise" in payload["musicxml"]

    async def test_empty_abc_returns_error(self):
        result = await call_tool("abc_to_musicxml", {"abc": ""})
        payload = json.loads(result[0].text)
        assert "error" in payload


class TestCallToolValidateAbc:
    async def test_valid_abc_passes(self):
        result = await call_tool("validate_abc", {"abc": MINIMAL_ABC})
        payload = json.loads(result[0].text)
        assert payload["valid"] is True
        assert payload["errors"] == []

    async def test_empty_abc_fails(self):
        result = await call_tool("validate_abc", {"abc": ""})
        payload = json.loads(result[0].text)
        assert payload["valid"] is False

    async def test_missing_headers_warns(self):
        result = await call_tool("validate_abc", {"abc": "CDEG|]"})
        payload = json.loads(result[0].text)
        assert payload["warnings"]


class TestCallToolHealthCheck:
    async def test_health_check_returns_ok_status(self):
        result = await call_tool("health_check", {})
        payload = json.loads(result[0].text)
        assert payload["status"] == "ok"
        assert "checks" in payload
        assert "summary" in payload
        assert payload["checks"]["music21"]["ok"] is True
        assert payload["checks"]["round_trip"]["ok"] is True

    async def test_health_check_summary_mentions_music21(self):
        result = await call_tool("health_check", {})
        payload = json.loads(result[0].text)
        assert "music21" in payload["summary"]

    async def test_health_check_schema(self):
        tools = await list_tools()
        tool = next(t for t in tools if t.name == "health_check")
        assert tool.input_schema["required"] == []


class TestUnknownTool:
    async def test_unknown_tool_raises(self):
        with pytest.raises(ValueError, match="Unknown tool"):
            await call_tool("nonexistent_tool", {})
