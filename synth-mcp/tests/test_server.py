"""Tests for synth_mcp MCP server — tool schemas, list_capabilities, error propagation."""

import json
from importlib.metadata import version as package_version

import pytest

from synth_mcp.server import call_tool, list_tools

VALID_MUSICXML = """\
<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Soprano</part-name></score-part>
    <score-part id="P2"><part-name>Alto</part-name></score-part>
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
  <part id="P2">
    <measure number="1">
      <note>
        <pitch><step>A</step><octave>4</octave></pitch>
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
        assert "get_parts" in names
        assert "synthesize" in names
        assert "list_capabilities" in names

    async def test_get_parts_schema(self):
        tools = await list_tools()
        tool = next(t for t in tools if t.name == "get_parts")
        schema = tool.input_schema
        assert "musicxml" in schema["properties"]
        assert schema["required"] == ["musicxml"]

    async def test_synthesize_schema(self):
        tools = await list_tools()
        tool = next(t for t in tools if t.name == "synthesize")
        schema = tool.input_schema
        assert "musicxml" in schema["properties"]
        assert "part_ids" in schema["properties"]
        assert "tempo_factor" in schema["properties"]
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

        assert data["server"] == "synth-mcp"
        assert data["version"] == package_version("synth-mcp")
        assert "musicxml" in data["input_formats"]
        assert "wav" in data["output_formats"]
        assert "get_parts" in data["tools"]
        assert "synthesize" in data["tools"]
        assert "list_capabilities" in data["tools"]
        assert "health_check" in data["tools"]
        assert data["backend"] == "fluidsynth"
        assert "soundfont_loaded" in data
        assert "fluidsynth_available" in data

    async def test_soundfont_not_loaded_when_env_missing(self, monkeypatch):
        monkeypatch.delenv("SYNTH_SOUNDFONT_PATH", raising=False)
        result = await call_tool("list_capabilities", {})
        data = json.loads(result[0].text)
        assert data["soundfont_loaded"] is False


# ---------------------------------------------------------------------------
# get_parts
# ---------------------------------------------------------------------------

class TestGetParts:
    async def test_valid_musicxml_returns_parts(self):
        result = await call_tool("get_parts", {"musicxml": VALID_MUSICXML})
        data = json.loads(result[0].text)
        assert "parts" in data
        assert len(data["parts"]) == 2
        # music21 9.x uses the part name as the id
        ids = [p["id"] for p in data["parts"]]
        assert "Soprano" in ids
        assert "Alto" in ids

    async def test_part_dicts_have_required_keys(self):
        result = await call_tool("get_parts", {"musicxml": VALID_MUSICXML})
        data = json.loads(result[0].text)
        for part in data["parts"]:
            assert "id" in part
            assert "name" in part
            assert "measure_count" in part

    async def test_invalid_xml_returns_error(self):
        result = await call_tool("get_parts", {"musicxml": "not xml"})
        data = json.loads(result[0].text)
        assert "error" in data
        assert "error_code" in data
        assert data["error_code"] == "INVALID_INPUT"

    async def test_empty_musicxml_returns_error(self):
        result = await call_tool("get_parts", {"musicxml": ""})
        data = json.loads(result[0].text)
        assert "error" in data


# ---------------------------------------------------------------------------
# synthesize — parameter validation (no FluidSynth required)
# ---------------------------------------------------------------------------

class TestSynthesizeValidation:
    async def test_invalid_musicxml_returns_invalid_input(self):
        result = await call_tool("synthesize", {"musicxml": "bad xml"})
        data = json.loads(result[0].text)
        assert "error" in data
        assert data["error_code"] == "INVALID_INPUT"

    async def test_tempo_factor_too_high_returns_invalid_parameter(self):
        result = await call_tool(
            "synthesize", {"musicxml": VALID_MUSICXML, "tempo_factor": 10.0}
        )
        data = json.loads(result[0].text)
        assert "error" in data
        assert data["error_code"] == "INVALID_PARAMETER"

    async def test_tempo_factor_too_low_returns_invalid_parameter(self):
        result = await call_tool(
            "synthesize", {"musicxml": VALID_MUSICXML, "tempo_factor": 0.1}
        )
        data = json.loads(result[0].text)
        assert "error" in data
        assert data["error_code"] == "INVALID_PARAMETER"

    async def test_part_ids_not_a_list_returns_error(self):
        result = await call_tool(
            "synthesize", {"musicxml": VALID_MUSICXML, "part_ids": "P1"}
        )
        data = json.loads(result[0].text)
        assert "error" in data

    async def test_invalid_part_id_returns_error(self):
        # Valid MusicXML but non-existent part ID — reaches engine validation
        result = await call_tool(
            "synthesize", {"musicxml": VALID_MUSICXML, "part_ids": ["P99"]}
        )
        data = json.loads(result[0].text)
        assert "error" in data
        assert data["error_code"] == "INVALID_PARAMETER"

    async def test_missing_soundfont_returns_processing_failed(self, monkeypatch):
        monkeypatch.delenv("SYNTH_SOUNDFONT_PATH", raising=False)
        result = await call_tool("synthesize", {"musicxml": VALID_MUSICXML})
        data = json.loads(result[0].text)
        assert "error" in data
        assert data["error_code"] == "PROCESSING_FAILED"
        assert "SYNTH_SOUNDFONT_PATH" in data["error"]

    async def test_empty_musicxml_returns_error(self):
        result = await call_tool("synthesize", {"musicxml": ""})
        data = json.loads(result[0].text)
        assert "error" in data

    async def test_unknown_tool_raises(self):
        with pytest.raises(ValueError, match="Unknown tool"):
            await call_tool("nonexistent_tool", {})


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    async def test_returns_text_content(self):
        result = await call_tool("health_check", {})
        assert len(result) == 1
        assert result[0].type == "text"

    async def test_output_contains_overall_status(self):
        result = await call_tool("health_check", {})
        text = result[0].text
        assert "Overall:" in text
        assert "READY" in text or "NOT READY" in text

    async def test_output_contains_soundfont_line(self):
        result = await call_tool("health_check", {})
        assert "Soundfont:" in result[0].text

    async def test_soundfont_missing_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("SYNTH_SOUNDFONT_PATH", raising=False)
        result = await call_tool("health_check", {})
        text = result[0].text
        assert "MISSING" in text
        assert "NOT READY" in text

    async def test_soundfont_missing_when_path_nonexistent(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SYNTH_SOUNDFONT_PATH", str(tmp_path / "no_such.sf2"))
        result = await call_tool("health_check", {})
        text = result[0].text
        assert "MISSING" in text
        assert "NOT READY" in text

    async def test_soundfont_ok_when_file_exists(self, monkeypatch, tmp_path):
        sf2 = tmp_path / "test.sf2"
        sf2.write_bytes(b"dummy")
        monkeypatch.setenv("SYNTH_SOUNDFONT_PATH", str(sf2))
        result = await call_tool("health_check", {})
        text = result[0].text
        assert "Soundfont:    OK" in text

    async def test_missing_soundfont_includes_download_hint(self, monkeypatch):
        monkeypatch.delenv("SYNTH_SOUNDFONT_PATH", raising=False)
        result = await call_tool("health_check", {})
        text = result[0].text
        assert "SYNTH_SOUNDFONT_PATH" in text

    async def test_health_check_registered_in_list_tools(self):
        tools = await list_tools()
        names = [t.name for t in tools]
        assert "health_check" in names

    async def test_health_check_schema_has_no_required_params(self):
        tools = await list_tools()
        tool = next(t for t in tools if t.name == "health_check")
        assert tool.input_schema["required"] == []
