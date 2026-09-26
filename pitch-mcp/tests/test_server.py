"""MCP protocol and tool schema tests for pitch-mcp."""

import json
import os
import tempfile
from importlib.metadata import version as package_version

import numpy as np
import pytest
from scipy.io.wavfile import write as wav_write

from pitch_mcp.server import _active_backend, app, call_tool, list_tools

MINIMAL_MUSICXML = """\
<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <work><work-title>Test</work-title></work>
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
      <direction placement="above">
        <direction-type>
          <metronome><beat-unit>quarter</beat-unit><per-minute>120</per-minute></metronome>
        </direction-type>
      </direction>
      <note>
        <pitch><step>A</step><octave>4</octave></pitch>
        <duration>8</duration><type>half</type>
      </note>
      <note>
        <pitch><step>G</step><octave>4</octave></pitch>
        <duration>8</duration><type>half</type>
      </note>
    </measure>
  </part>
</score-partwise>
"""


def _make_wav(freq_hz: float = 440.0, duration_sec: float = 1.0) -> str:
    sr = 22050
    t = np.linspace(0, duration_sec, int(sr * duration_sec))
    audio = (0.5 * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    wav_write(path, sr, (audio * 32767).astype(np.int16))
    return path


class TestListTools:
    async def test_returns_seven_tools(self):
        tools = await list_tools()
        names = {t.name for t in tools}
        assert names == {
            "analyze_recording",
            "load_score",
            "start_monitoring",
            "get_current_position",
            "stop_monitoring",
            "list_capabilities",
            "health_check",
        }

    async def test_analyze_recording_schema(self):
        tools = await list_tools()
        t = next(x for x in tools if x.name == "analyze_recording")
        req = t.input_schema["required"]
        assert "audio_path" in req
        assert "musicxml" in req
        assert "part_id" in req

    async def test_load_score_schema(self):
        tools = await list_tools()
        t = next(x for x in tools if x.name == "load_score")
        assert "musicxml" in t.input_schema["required"]
        assert "part_id" in t.input_schema["required"]

    async def test_start_monitoring_schema(self):
        tools = await list_tools()
        t = next(x for x in tools if x.name == "start_monitoring")
        assert "session_id" in t.input_schema["required"]
        # tempo_bpm is optional
        assert "tempo_bpm" in t.input_schema["properties"]

    async def test_list_capabilities_no_required(self):
        tools = await list_tools()
        t = next(x for x in tools if x.name == "list_capabilities")
        assert t.input_schema["required"] == []

    async def test_health_check_no_required(self):
        tools = await list_tools()
        t = next(x for x in tools if x.name == "health_check")
        assert t.input_schema["required"] == []


class TestListCapabilities:
    async def test_structure(self):
        result = await call_tool("list_capabilities", {})
        payload = json.loads(result[0].text)
        assert payload["server"] == "pitch-mcp"
        assert payload["version"] == package_version("pitch-mcp")
        assert "musicxml" in payload["input_formats"]
        assert "wav" in payload["input_formats"]
        assert "pitch_backend" in payload
        assert "pitch_backend_version" in payload
        assert "microphone_available" in payload
        assert set(payload["tools"]) == {
            "analyze_recording",
            "load_score",
            "start_monitoring",
            "get_current_position",
            "stop_monitoring",
            "list_capabilities",
            "health_check",
        }


class TestCallToolAnalyzeRecording:
    async def test_missing_audio_file_returns_error(self):
        result = await call_tool(
            "analyze_recording",
            {"audio_path": "/nonexistent.wav", "musicxml": MINIMAL_MUSICXML, "part_id": "Soprano"},
        )
        payload = json.loads(result[0].text)
        assert "error" in payload
        assert payload["error_code"] in ("FILE_NOT_FOUND", "UNSUPPORTED_FORMAT")

    async def test_empty_musicxml_returns_error(self):
        path = _make_wav()
        try:
            result = await call_tool(
                "analyze_recording",
                {"audio_path": path, "musicxml": "", "part_id": "Soprano"},
            )
            payload = json.loads(result[0].text)
            assert "error" in payload
        finally:
            os.unlink(path)

    async def test_invalid_part_id_returns_error(self):
        path = _make_wav()
        try:
            result = await call_tool(
                "analyze_recording",
                {"audio_path": path, "musicxml": MINIMAL_MUSICXML, "part_id": "Tuba"},
            )
            payload = json.loads(result[0].text)
            assert "error" in payload
            assert payload["error_code"] == "INVALID_PARAMETER"
        finally:
            os.unlink(path)

    async def test_valid_call_returns_analysis(self):
        path = _make_wav(440.0, duration_sec=2.0)
        try:
            result = await call_tool(
                "analyze_recording",
                {"audio_path": path, "musicxml": MINIMAL_MUSICXML, "part_id": "Soprano"},
            )
            payload = json.loads(result[0].text)
            assert "error" not in payload or "error_code" not in payload
            assert "measures_covered" in payload
            assert "note_accuracy" in payload
        finally:
            os.unlink(path)

    async def test_unsupported_format_returns_error(self):
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"not a real mp3")
            path = f.name
        try:
            result = await call_tool(
                "analyze_recording",
                {"audio_path": path, "musicxml": MINIMAL_MUSICXML, "part_id": "Soprano"},
            )
            payload = json.loads(result[0].text)
            assert "error" in payload
            assert payload["error_code"] == "UNSUPPORTED_FORMAT"
        finally:
            os.unlink(path)


class TestCallToolLoadScore:
    async def test_valid_load_score(self):
        result = await call_tool("load_score", {"musicxml": MINIMAL_MUSICXML, "part_id": "Soprano"})
        payload = json.loads(result[0].text)
        assert "session_id" in payload
        assert "part_name" in payload
        assert "measure_count" in payload
        assert payload["measure_count"] >= 1

    async def test_invalid_part_id_returns_error(self):
        result = await call_tool("load_score", {"musicxml": MINIMAL_MUSICXML, "part_id": "Tuba"})
        payload = json.loads(result[0].text)
        assert "error" in payload
        assert payload["error_code"] == "INVALID_PARAMETER"


class TestCallToolSessionLifecycle:
    async def test_load_get_position_stop(self):
        # Load score
        load_result = await call_tool(
            "load_score", {"musicxml": MINIMAL_MUSICXML, "part_id": "Soprano"}
        )
        sid = json.loads(load_result[0].text)["session_id"]

        # Get position (before monitoring starts — returns default)
        pos_result = await call_tool("get_current_position", {"session_id": sid})
        pos = json.loads(pos_result[0].text)
        assert pos["session_id"] == sid
        assert "measure" in pos
        assert "status" in pos

        # Stop monitoring (no stream running — still returns summary)
        stop_result = await call_tool("stop_monitoring", {"session_id": sid})
        stop_payload = json.loads(stop_result[0].text)
        assert "session_id" in stop_payload
        assert "summary" in stop_payload

    async def test_get_position_invalid_session(self):
        result = await call_tool("get_current_position", {"session_id": "bad-id"})
        payload = json.loads(result[0].text)
        assert "error" in payload
        assert payload["error_code"] == "SESSION_NOT_FOUND"

    async def test_stop_monitoring_invalid_session(self):
        result = await call_tool("stop_monitoring", {"session_id": "bad-id"})
        payload = json.loads(result[0].text)
        assert "error" in payload
        assert payload["error_code"] == "SESSION_NOT_FOUND"

    async def test_second_stop_fails(self):
        load_result = await call_tool(
            "load_score", {"musicxml": MINIMAL_MUSICXML, "part_id": "Soprano"}
        )
        sid = json.loads(load_result[0].text)["session_id"]
        await call_tool("stop_monitoring", {"session_id": sid})
        # Second stop should fail
        result = await call_tool("stop_monitoring", {"session_id": sid})
        payload = json.loads(result[0].text)
        assert "error" in payload
        assert payload["error_code"] == "SESSION_NOT_FOUND"


class TestHealthCheck:
    async def test_returns_status_field(self):
        result = await call_tool("health_check", {})
        payload = json.loads(result[0].text)
        assert "status" in payload
        assert payload["status"] in ("ok", "degraded", "error")

    async def test_returns_summary(self):
        result = await call_tool("health_check", {})
        payload = json.loads(result[0].text)
        assert "summary" in payload
        assert isinstance(payload["summary"], str)
        assert len(payload["summary"]) > 0

    async def test_offline_analysis_section(self):
        result = await call_tool("health_check", {})
        payload = json.loads(result[0].text)
        assert "offline_analysis" in payload
        oa = payload["offline_analysis"]
        assert "available" in oa
        assert "librosa_version" in oa
        assert isinstance(oa["available"], bool)

    async def test_realtime_monitoring_section(self):
        result = await call_tool("health_check", {})
        payload = json.loads(result[0].text)
        assert "realtime_monitoring" in payload
        rt = payload["realtime_monitoring"]
        assert "available" in rt
        assert "sounddevice_available" in rt
        assert "portaudio_available" in rt
        assert "microphone_detected" in rt

    async def test_librosa_available_in_ci(self):
        # librosa is a required dependency — it must be importable in CI
        result = await call_tool("health_check", {})
        payload = json.loads(result[0].text)
        assert payload["offline_analysis"]["available"] is True
        assert payload["status"] in ("ok", "degraded")

    async def test_no_arguments_required(self):
        # health_check should work with empty arguments dict
        result = await call_tool("health_check", {})
        assert len(result) == 1
        assert result[0].type == "text"


class TestActiveBackend:
    def test_default_is_librosa(self):
        """See docs/todo.md: this defaulted to 'aubio', which isn't even a
        project dependency, so list_capabilities reported the wrong backend
        name and an 'unavailable' version by default."""
        old = os.environ.pop("PITCH_BACKEND", None)
        try:
            assert _active_backend() == "librosa"
        finally:
            if old is not None:
                os.environ["PITCH_BACKEND"] = old

    async def test_list_capabilities_reports_librosa_version(self):
        old = os.environ.pop("PITCH_BACKEND", None)
        try:
            result = await call_tool("list_capabilities", {})
            payload = json.loads(result[0].text)
            assert payload["pitch_backend"] == "librosa"
            assert payload["pitch_backend_version"] != "unavailable"
        finally:
            if old is not None:
                os.environ["PITCH_BACKEND"] = old


class TestUnknownTool:
    async def test_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown tool"):
            await call_tool("nonexistent_tool", {})
