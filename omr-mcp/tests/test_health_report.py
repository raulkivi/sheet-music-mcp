"""Health report mapping for omr-mcp (docs/conventions.md, Health Reports)."""

import jsonschema
import pytest
from sheet_music_mcp_core.health import HEALTH_OUTPUT_SCHEMA
from sheet_music_mcp_core.ui import InMemoryAssetSource, UiRegistry

import omr_mcp.server as server

DOC = "https://github.com/raulkivi/sheet-music-mcp/blob/main/omr-mcp/TROUBLESHOOTING.md"
CACHE_NOTE = (
    "Model cache not found. On first use oemer will download ~100 MB of "
    "model checkpoints (this may take 5–10 minutes). Subsequent runs are fast."
)
AUD_NOTE = "Optional alternate engine, not required; downloads automatically on first use."

OEMER_OK = {"status": "ok", "version": "0.1.8"}
OEMER_MISSING = {"status": "missing", "error": "No module named 'oemer'", "hint": "Run 'uv sync'"}
CACHE_OK = {"status": "ok", "path": "/x", "note": "Model cache found — ready."}
CACHE_MISSING = {"status": "missing", "path": None, "note": CACHE_NOTE}
AUD_OK = {"status": "ok", "path": "/a", "version": "5.4.1", "note": "ready to use."}
AUD_NONE = {"status": "not_installed", "path": None, "note": AUD_NOTE}


def raw(oemer, cache, aud):
    checks = {"oemer": oemer, "model_cache": cache, "audiveris": aud}
    ok = oemer["status"] == "ok" and cache["status"] == "ok"
    return {"status": "ok" if ok else "degraded", "checks": checks}


def expected_text(result):
    lines = [f"omr-mcp health status: {result['status'].upper()}", ""]
    for dep, info in result["checks"].items():
        icon = "✓" if info["status"] == "ok" else "○" if info["status"] == "not_installed" else "✗"
        line = f"  {icon} {dep}: {info['status']}"
        if info.get("version"):
            line += f" (v{info['version']})"
        if info.get("path"):
            line += f"\n      path: {info['path']}"
        if info.get("note"):
            line += f"\n      {info['note']}"
        if info.get("error"):
            line += f"\n      error: {info['error']}"
        if info.get("hint"):
            line += f"\n      hint: {info['hint']}"
        lines.append(line)
    return "\n".join(lines)


async def run(monkeypatch, data):
    monkeypatch.setattr(server, "_engine_health_check", lambda: data)
    result = await server.call_tool_result("health_check", {})
    assert not result.is_error
    jsonschema.validate(result.structured_content, HEALTH_OUTPUT_SCHEMA)
    assert len(result.content) == 1
    assert result.content[0].text == expected_text(data)
    return result.structured_content


async def test_all_ok_with_audiveris(monkeypatch):
    report = await run(monkeypatch, raw(OEMER_OK, CACHE_OK, AUD_OK))
    assert report == {
        "status": "ready",
        "checks": [
            {"name": "oemer", "status": "ok", "version": "0.1.8"},
            {"name": "oemer model cache", "status": "ok"},
            {"name": "Audiveris (optional)", "status": "ok", "version": "5.4.1"},
        ],
    }


async def test_audiveris_not_installed_is_ok_with_note(monkeypatch):
    report = await run(monkeypatch, raw(OEMER_OK, CACHE_OK, AUD_NONE))
    assert report["status"] == "ready"
    assert report["checks"][2] == {"name": "Audiveris (optional)", "status": "ok", "hint": AUD_NOTE}


async def test_oemer_missing_fails(monkeypatch):
    report = await run(monkeypatch, raw(OEMER_MISSING, CACHE_OK, AUD_NONE))
    assert report["status"] == "not_ready"
    assert report["checks"][0] == {
        "name": "oemer",
        "status": "fail",
        "hint": "oemer is not installed: No module named 'oemer'",
        "fix_snippet": "uv sync",
        "doc_url": DOC,
    }


async def test_oemer_unknown_version_is_unset(monkeypatch):
    report = await run(monkeypatch, raw({"status": "ok", "version": "unknown"}, CACHE_OK, AUD_NONE))
    assert report["checks"][0] == {"name": "oemer", "status": "ok"}


async def test_model_cache_missing_warns(monkeypatch):
    report = await run(monkeypatch, raw(OEMER_OK, CACHE_MISSING, AUD_NONE))
    assert report["status"] == "degraded"
    assert report["checks"][1] == {
        "name": "oemer model cache",
        "status": "warn",
        "hint": CACHE_NOTE,
        "doc_url": DOC,
    }


async def test_fail_beats_warn(monkeypatch):
    report = await run(monkeypatch, raw(OEMER_MISSING, CACHE_MISSING, AUD_NONE))
    assert report["status"] == "not_ready"
    assert [c["status"] for c in report["checks"]] == ["fail", "warn", "ok"]


async def test_real_environment_validates():
    result = await server.call_tool_result("health_check", {})
    jsonschema.validate(result.structured_content, HEALTH_OUTPUT_SCHEMA)
    assert [c["name"] for c in result.structured_content["checks"]] == [
        "oemer",
        "oemer model cache",
        "Audiveris (optional)",
    ]


def _registry(monkeypatch, packaged):
    assets = {server.SETUP_DOCTOR.asset: "<!doctype html>"} if packaged else {}
    monkeypatch.setattr(
        server,
        "ui_registry",
        UiRegistry([server.RECOGNITION_REVIEW, server.SETUP_DOCTOR], InMemoryAssetSource(assets)),
    )


async def test_tool_metadata_packaged(monkeypatch):
    _registry(monkeypatch, True)
    tool = next(t for t in await server.list_tools() if t.name == "health_check")
    assert tool.output_schema == HEALTH_OUTPUT_SCHEMA
    assert tool.meta["ui"]["resourceUri"] == "ui://omr/setup-doctor"


async def test_tool_metadata_unpackaged(monkeypatch):
    _registry(monkeypatch, False)
    tool = next(t for t in await server.list_tools() if t.name == "health_check")
    assert tool.output_schema == HEALTH_OUTPUT_SCHEMA
    assert not tool.meta
