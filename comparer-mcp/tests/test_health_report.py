"""Health report mapping for comparer-mcp (docs/conventions.md, Health Reports)."""

import json

import jsonschema
import pytest
from sheet_music_mcp_core.health import HEALTH_OUTPUT_SCHEMA
from sheet_music_mcp_core.ui import InMemoryAssetSource, UiRegistry

import comparer_mcp.server as server

DOC = "https://github.com/raulkivi/sheet-music-mcp/blob/main/comparer-mcp/TROUBLESHOOTING.md"

RAW_OK = {
    "status": "ok",
    "checks": {"music21": {"ok": True, "version": "9.1.0"}, "self_compare": {"ok": True}},
    "summary": "All systems operational. music21 9.1.0 is working correctly.",
}
RAW_NO_M21 = {
    "status": "degraded",
    "checks": {"music21": {"ok": False, "version": None, "error": "No module named 'music21'"}},
    "summary": "Server is degraded: music21: No module named 'music21'",
}
RAW_SELF_FAIL = {
    "status": "degraded",
    "checks": {
        "music21": {"ok": True, "version": "9.1.0"},
        "self_compare": {"ok": False, "error": "boom"},
    },
    "summary": "Server is degraded: self_compare: boom",
}


async def run(monkeypatch, raw):
    monkeypatch.setattr(server, "health_check", lambda: raw)
    result = await server.call_tool_result("health_check", {})
    assert not result.is_error
    return result


@pytest.mark.parametrize("raw", [RAW_OK, RAW_NO_M21, RAW_SELF_FAIL])
async def test_schema_and_text_unchanged(monkeypatch, raw):
    result = await run(monkeypatch, raw)
    jsonschema.validate(result.structured_content, HEALTH_OUTPUT_SCHEMA)
    assert len(result.content) == 1
    assert result.content[0].text == json.dumps(raw, indent=2)


async def test_ok(monkeypatch):
    report = (await run(monkeypatch, RAW_OK)).structured_content
    assert report == {
        "status": "ready",
        "checks": [
            {"name": "music21", "status": "ok", "version": "9.1.0"},
            {"name": "Self-comparison", "status": "ok"},
        ],
    }


async def test_music21_missing(monkeypatch):
    report = (await run(monkeypatch, RAW_NO_M21)).structured_content
    assert report == {
        "status": "not_ready",
        "checks": [
            {
                "name": "music21",
                "status": "fail",
                "hint": "music21 is not installed: No module named 'music21'",
                "fix_snippet": "uv sync",
                "doc_url": DOC,
            }
        ],
    }


async def test_self_compare_fails(monkeypatch):
    report = (await run(monkeypatch, RAW_SELF_FAIL)).structured_content
    assert report["status"] == "not_ready"
    assert report["checks"] == [
        {"name": "music21", "status": "ok", "version": "9.1.0"},
        {
            "name": "Self-comparison",
            "status": "fail",
            "hint": "Comparing a score with itself failed: boom",
            "doc_url": DOC,
        },
    ]


async def test_real_health_check_is_ready():
    result = await server.call_tool_result("health_check", {})
    assert result.structured_content["status"] == "ready"
    jsonschema.validate(result.structured_content, HEALTH_OUTPUT_SCHEMA)


def _registry(monkeypatch, packaged):
    assets = {server.SETUP_DOCTOR.asset: "<!doctype html>"} if packaged else {}
    monkeypatch.setattr(
        server,
        "ui_registry",
        UiRegistry([server.DIFF_VIEWER, server.SETUP_DOCTOR], InMemoryAssetSource(assets)),
    )


async def test_tool_metadata_packaged(monkeypatch):
    _registry(monkeypatch, True)
    tool = next(t for t in await server.list_tools() if t.name == "health_check")
    assert tool.output_schema == HEALTH_OUTPUT_SCHEMA
    assert tool.meta["ui"]["resourceUri"] == "ui://comparer/setup-doctor"


async def test_tool_metadata_unpackaged(monkeypatch):
    _registry(monkeypatch, False)
    tool = next(t for t in await server.list_tools() if t.name == "health_check")
    assert tool.output_schema == HEALTH_OUTPUT_SCHEMA
    assert not tool.meta
