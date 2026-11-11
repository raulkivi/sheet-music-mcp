"""Standard health report wiring: raw engine output → HealthCheck rows → structuredContent,
plus the Setup Doctor linking (docs/conventions.md: Health Reports)."""

import json
from unittest.mock import patch

import pytest
from sheet_music_mcp_core.health import HEALTH_OUTPUT_SCHEMA, HealthCheck, health_report

from musicxml_abc_mcp import server
from musicxml_abc_mcp.health import build_health_report, health_checks

DOC = "https://github.com/raulkivi/sheet-music-mcp/blob/main/musicxml-abc-mcp/TROUBLESHOOTING.md"

RAW_OK = {
    "status": "ok",
    "checks": {"music21": {"ok": True, "version": "9.0.0"}, "round_trip": {"ok": True}},
    "summary": "All systems operational.",
}

RAW_MUSIC21_FAIL = {
    "status": "degraded",
    "checks": {"music21": {"ok": False, "version": None, "error": "No module named 'music21'"}},
    "summary": "Server is degraded: music21: No module named 'music21'",
}

RAW_ROUND_TRIP_FAIL = {
    "status": "degraded",
    "checks": {"music21": {"ok": True, "version": "9.0.0"}, "round_trip": {"ok": False, "error": "boom"}},
    "summary": "Server is degraded: round_trip: boom",
}


def test_all_ok_maps_to_two_ok_checks():
    assert health_checks(RAW_OK) == [
        HealthCheck("music21", "ok", version="9.0.0"),
        HealthCheck("ABC round trip", "ok"),
    ]


def test_music21_fail_carrying_hint_fix_and_doc():
    [check] = health_checks(RAW_MUSIC21_FAIL)

    assert check == HealthCheck(
        "music21",
        "fail",
        hint="music21 is not installed: No module named 'music21'",
        fix_snippet="uv sync",
        doc_url=DOC,
    )
    assert "version" not in check.to_dict()  # unset fields are omitted, not sent as None


def test_round_trip_fail_carrying_hint_and_doc_but_no_fix():
    [_, check] = health_checks(RAW_ROUND_TRIP_FAIL)

    assert check == HealthCheck(
        "ABC round trip",
        "fail",
        hint="MusicXML → ABC → MusicXML smoke test failed: boom",
        doc_url=DOC,
    )
    assert "fix_snippet" not in check.to_dict()


def test_absent_round_trip_is_omitted():
    assert len(health_checks(RAW_MUSIC21_FAIL)) == 1


def test_build_health_report_derives_status_itself():
    assert build_health_report(RAW_OK) == health_report([
        HealthCheck("music21", "ok", version="9.0.0"),
        HealthCheck("ABC round trip", "ok"),
    ])
    assert build_health_report(RAW_OK)["status"] == "ready"
    assert build_health_report(RAW_MUSIC21_FAIL)["status"] == "not_ready"
    assert build_health_report(RAW_ROUND_TRIP_FAIL)["status"] == "not_ready"

    # A fail row must win over an ok row: the engine's own "status" field is never copied.
    report = build_health_report(
        {"checks": {"music21": RAW_MUSIC21_FAIL["checks"]["music21"], "round_trip": {"ok": True}}}
    )
    assert report["status"] == "not_ready"


async def _tools():
    return {tool.name: tool for tool in await server.list_tools()}


class TestServerWiring:
    async def test_text_content_unchanged_and_structured_content_is_the_report(self):
        with patch.object(server, "health_check", return_value=RAW_OK):
            result = await server.call_tool_result("health_check", {})

        assert not result.is_error
        assert result.content[0].text == json.dumps(RAW_OK, indent=2)
        assert result.structured_content == build_health_report(RAW_OK)

    async def test_error_envelope_is_kept_when_the_check_raises(self):
        with patch.object(server, "health_check", side_effect=RuntimeError("kaput")):
            result = await server.call_tool_result("health_check", {})

        assert result.is_error
        payload = json.loads(result.content[0].text)
        assert (payload["error"], payload["error_code"]) == ("Unexpected error: kaput", "PROCESSING_FAILED")
        assert result.structured_content is None

    async def test_output_schema_is_the_standard_health_schema(self, packaged_ui):
        tool = (await _tools())["health_check"]

        assert tool.output_schema == HEALTH_OUTPUT_SCHEMA

    async def test_links_the_setup_doctor_when_packaged(self, packaged_ui):
        tool = (await _tools())["health_check"]

        assert tool.meta == {"ui": {"resourceUri": "ui://abc/setup-doctor"}}

    async def test_no_link_without_a_ui_build(self):
        assert (await _tools())["health_check"].meta is None
