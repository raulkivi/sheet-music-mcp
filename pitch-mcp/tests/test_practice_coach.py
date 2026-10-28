"""Practice Coach linking: the ``ui://pitch/practice-coach`` resource, tool ``_meta``,
``structuredContent`` and the app-only ``get_score_for_session`` (proposal 5.1, AC-P1 to AC-P3)."""

import asyncio
import json

import jsonschema
import pytest
from mcp import Client, MCPError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS
from sheet_music_mcp_core.ui import UI_MIME, is_app_only

import pitch_mcp.server as server
from pitch_mcp.presenter import (
    ANALYSIS_OUTPUT_SCHEMA,
    POSITION_OUTPUT_SCHEMA,
    SESSION_OUTPUT_SCHEMA,
    present_analysis,
    present_position,
    present_session,
)
from pitch_mcp.server import app, call_tool_result, list_tools

from .conftest import COACH_HTML
from .test_content_golden import ANALYSIS
from .test_engine import MINIMAL_MUSICXML
from .test_practice import SIX_BARS, mic  # noqa: F401  (mic is a fixture)

COACH_URI = "ui://pitch/practice-coach"
OPENERS = ("load_score", "start_practice")
LINKED = (*OPENERS, "analyze_recording")
SESSION_FIELDS = {"session_id", "part_id", "part_name", "measure_count", "duration_seconds", "tempo_bpm"}


def _with_client(call):
    async def _go():
        async with Client(app) as client:
            return await call(client)

    return asyncio.run(_go())


async def _tools():
    return {tool.name: tool for tool in await list_tools()}


class TestToolLinking:
    @pytest.mark.parametrize("name", LINKED)
    async def test_tools_link_the_coach_when_packaged(self, packaged_ui, name):
        assert (await _tools())[name].meta == {"ui": {"resourceUri": COACH_URI}}

    @pytest.mark.parametrize("name", LINKED)
    async def test_no_link_without_a_ui_build(self, name):
        assert (await _tools())[name].meta is None

    async def test_other_model_facing_tools_are_not_linked(self, packaged_ui):
        others = [t for n, t in (await _tools()).items() if n not in LINKED and not is_app_only(t)]

        assert others
        assert all(t.meta is None or "resourceUri" not in t.meta.get("ui", {}) for t in others)

    @pytest.mark.parametrize("name", ("load_score", "start_practice", "get_current_position", "analyze_recording"))
    async def test_structured_tools_declare_an_output_schema(self, name):
        schema = (await _tools())[name].output_schema

        assert schema["type"] == "object"
        assert schema["required"]


class TestResources:
    def test_lists_the_coach_when_packaged(self, packaged_ui):
        result = _with_client(lambda c: c.list_resources())

        assert [(r.uri, r.name, r.mime_type) for r in result.resources] == [
            (COACH_URI, "Practice Coach", UI_MIME)
        ]

    def test_lists_nothing_without_a_ui_build(self):
        assert _with_client(lambda c: c.list_resources()).resources == []

    def test_reads_the_coach_html(self, packaged_ui):
        [contents] = _with_client(lambda c: c.read_resource(COACH_URI)).contents

        assert (contents.uri, contents.mime_type, contents.text) == (COACH_URI, UI_MIME, COACH_HTML)

    def test_missing_build_is_an_error_naming_the_fix(self):
        async def read(client):
            with pytest.raises(MCPError) as caught:
                await client.read_resource(COACH_URI)
            return caught.value

        error = _with_client(read)

        assert error.code == INTERNAL_ERROR
        assert error.data["error_code"] == "UI_ASSET_MISSING"

    def test_unknown_resource_is_invalid_params(self, packaged_ui):
        async def read(client):
            with pytest.raises(MCPError) as caught:
                await client.read_resource("ui://pitch/nope")
            return caught.value

        assert _with_client(read).code == INVALID_PARAMS


class TestPresenter:
    VIEW = {
        "session_id": "s1", "part_id": "P1", "part_name": "Soprano",
        "measure_count": 6, "duration_seconds": 24.0, "tempo_bpm": 90.0,
    }

    def test_session_content_is_the_original_json_and_structured_the_view(self):
        original = {**self.VIEW, "status": "started"}
        original.pop("tempo_bpm")

        content, structured = present_session(original, self.VIEW)

        assert json.loads(content[0].text) == original
        assert content[0].text == json.dumps(original, indent=2)
        assert structured == self.VIEW
        jsonschema.validate(structured, SESSION_OUTPUT_SCHEMA)

    def test_position_and_analysis_structured_equal_content(self):
        position = {"session_id": "s1", "measure": 1, "beat": 1.0, "expected_note": "C4",
                    "sung_pitch_hz": None, "accuracy_cents": None, "status": "no_signal"}

        for present, data, schema in (
            (present_position, position, POSITION_OUTPUT_SCHEMA),
            (present_analysis, ANALYSIS, ANALYSIS_OUTPUT_SCHEMA),
        ):
            content, structured = present(data)
            assert json.loads(content[0].text) == structured == data
            jsonschema.validate(structured, schema)


class TestSessionOpeners:
    @pytest.mark.parametrize("tool", OPENERS)
    def test_structured_content_describes_the_session(self, mic, tool):  # noqa: F811
        arguments = {"musicxml": SIX_BARS, "part": "Alto", "measures": [2, 4]}

        result = _with_client(lambda c: c.call_tool(tool, arguments))

        assert not result.is_error
        data = result.structured_content
        assert set(data) == SESSION_FIELDS
        assert (data["part_id"], data["part_name"], data["measure_count"]) == ("P2", "Alto", 3)
        assert data["tempo_bpm"] == 90
        assert data["session_id"] == json.loads(result.content[0].text)["session_id"]

    def test_start_practice_reports_the_tempo_override(self, mic):  # noqa: F811
        result = _with_client(
            lambda c: c.call_tool("start_practice", {"musicxml": SIX_BARS, "part": "P1", "tempo_bpm": 60})
        )

        assert result.structured_content["tempo_bpm"] == 60

    def test_load_score_without_a_tempo_mark_reports_the_default(self, mic):  # noqa: F811
        result = _with_client(lambda c: c.call_tool("load_score", {"musicxml": MINIMAL_MUSICXML, "part": "P1"}))

        assert isinstance(result.structured_content["tempo_bpm"], (int, float))


class TestPositionAndAnalysis:
    def test_position_is_the_snapshot(self, mic):  # noqa: F811
        opened = _with_client(lambda c: c.call_tool("load_score", {"musicxml": SIX_BARS, "part": "P1"}))
        sid = opened.structured_content["session_id"]

        result = _with_client(lambda c: c.call_tool("get_current_position", {"session_id": sid}))

        assert not result.is_error
        assert result.structured_content == json.loads(result.content[0].text)
        assert result.structured_content["session_id"] == sid
        assert result.structured_content["status"] == "no_signal"

    def test_analysis_carries_every_note(self, monkeypatch, tmp_path):
        audio = tmp_path / "take.wav"
        audio.write_bytes(b"RIFF")
        monkeypatch.setattr(server, "analyze_recording", lambda *a, **k: ANALYSIS)

        result = _with_client(
            lambda c: c.call_tool(
                "analyze_recording", {"audio_path": str(audio), "musicxml": MINIMAL_MUSICXML, "part": "P1"}
            )
        )

        assert not result.is_error
        assert result.structured_content == ANALYSIS
        assert len(result.structured_content["note_accuracy"]) == 2


class TestScoreForSession:
    async def test_is_app_only_and_never_linked_to_a_page_without_a_build(self):
        tool = (await _tools())["get_score_for_session"]

        assert is_app_only(tool)
        assert tool.meta == {"ui": {"visibility": ["app"]}}
        assert set(tool.input_schema["properties"]) == {"session_id"}
        assert tool.input_schema.get("additionalProperties") is False

    async def test_links_the_coach_when_packaged(self, packaged_ui):
        tool = (await _tools())["get_score_for_session"]

        assert tool.meta == {"ui": {"resourceUri": COACH_URI, "visibility": ["app"]}}

    def test_hidden_from_clients_without_ui(self):
        names = {t.name for t in _with_client(lambda c: c.list_tools()).tools}

        assert "get_score_for_session" not in names

    def test_returns_the_session_score(self, mic):  # noqa: F811
        async def go(client):
            opened = await client.call_tool("load_score", {"musicxml": SIX_BARS, "part": "P1", "measures": [2, 3]})
            sid = opened.structured_content["session_id"]
            return sid, await client.call_tool("get_score_for_session", {"session_id": sid})

        sid, result = _with_client(go)

        assert not result.is_error
        assert set(result.structured_content) == {"session_id", "musicxml"}
        assert result.structured_content["session_id"] == sid
        # The session's own (cut) score, so the app shows what is being practised.
        assert result.structured_content["musicxml"].lstrip().startswith(("<?xml", "<score-partwise"))
        assert "<measure" in result.structured_content["musicxml"]

    async def test_unknown_session_is_not_found(self):
        result = await call_tool_result("get_score_for_session", {"session_id": "nope"})

        assert result.is_error
        assert result.structured_content is None
        assert json.loads(result.content[0].text)["error_code"] == "SESSION_NOT_FOUND"

    def test_paths_are_not_accepted(self):
        result = _with_client(
            lambda c: c.call_tool("get_score_for_session", {"session_id": "x", "musicxml_path": "/etc/passwd"})
        )

        assert result.is_error
        assert json.loads(result.content[0].text)["error_code"] == "INVALID_PARAMETER"


class TestErrors:
    @pytest.mark.parametrize(
        "tool, arguments, code",
        [
            ("load_score", {"musicxml": "<nope/>", "part": "P1"}, "INVALID_INPUT"),
            ("load_score", {"musicxml": MINIMAL_MUSICXML}, "INVALID_PARAMETER"),
            ("start_practice", {"musicxml": SIX_BARS, "part": "P1", "measures": [9, 12]}, "INVALID_PARAMETER"),
            ("get_current_position", {"session_id": "no-such-session"}, "SESSION_NOT_FOUND"),
            ("analyze_recording", {"audio_path": "/no/such.wav", "musicxml": SIX_BARS, "part": "P1"}, "FILE_NOT_FOUND"),
        ],
    )
    def test_keep_the_envelope_and_carry_no_structured_content(self, tool, arguments, code):
        result = _with_client(lambda c: c.call_tool(tool, arguments))

        assert result.is_error
        assert result.structured_content is None
        assert json.loads(result.content[0].text)["error_code"] == code
