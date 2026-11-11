"""Health report mapping for render-mcp (docs/conventions.md, Health Reports)."""

import importlib.metadata

import jsonschema
import pytest
from sheet_music_mcp_core.health import HEALTH_OUTPUT_SCHEMA
from sheet_music_mcp_core.ui import InMemoryAssetSource, UiRegistry

import render_mcp.server as server

DOC = "https://github.com/raulkivi/sheet-music-mcp/blob/main/render-mcp/TROUBLESHOOTING.md"
NO_BACKEND_HINT = "No rendering backend found; render_to_pdf and render_to_image fail."
CAIRO_HINT = "PNG and PDF output via Verovio will fail; SVG still works."


def raw(backend, musescore=False, verovio=False, cairosvg=False, notes=()):
    return {
        "server": "render-mcp",
        "status": "ok" if backend else "degraded",
        "backend": backend,
        "musescore_available": musescore,
        "verovio_available": verovio,
        "cairosvg_available": cairosvg,
        "notes": list(notes),
    }


def expected_text(status):
    lines = [
        f"render-mcp status: {status['status'].upper()}",
        f"  Backend:   {status['backend'] or 'none'}",
        f"  MuseScore: {'✓' if status['musescore_available'] else '✗'}",
        f"  Verovio:   {'✓' if status['verovio_available'] else '✗'}",
        f"  cairosvg:  {'✓' if status['cairosvg_available'] else '✗'}",
    ]
    if status["notes"]:
        lines += ["", "Warnings:"] + [f"  - {n}" for n in status["notes"]]
    return "\n".join(lines)


async def run(monkeypatch, status):
    monkeypatch.setattr(server, "get_health_status", lambda: status)
    result = await server.call_tool_result("health_check", {})
    assert not result.is_error
    jsonschema.validate(result.structured_content, HEALTH_OUTPUT_SCHEMA)
    assert len(result.content) == 1
    assert result.content[0].text == expected_text(status)
    return result.structured_content


async def test_verovio_with_cairosvg_is_ready(monkeypatch):
    report = await run(monkeypatch, raw("verovio", verovio=True, cairosvg=True))
    assert report == {
        "status": "ready",
        "checks": [
            {"name": "Rendering backend", "status": "ok", "version": importlib.metadata.version("verovio")},
            {"name": "cairosvg", "status": "ok"},
        ],
    }


async def test_musescore_backend_has_no_version(monkeypatch):
    report = await run(monkeypatch, raw("musescore", musescore=True))
    assert report == {"status": "ready", "checks": [{"name": "Rendering backend", "status": "ok"}]}


async def test_musescore_with_verovio_still_checks_cairosvg(monkeypatch):
    report = await run(monkeypatch, raw("musescore", musescore=True, verovio=True, cairosvg=False))
    assert report["status"] == "degraded"
    assert [c["name"] for c in report["checks"]] == ["Rendering backend", "cairosvg"]
    assert report["checks"][0] == {"name": "Rendering backend", "status": "ok"}


async def test_no_backend_fails(monkeypatch):
    report = await run(monkeypatch, raw(None, notes=["No rendering backend found."]))
    assert report == {
        "status": "not_ready",
        "checks": [
            {
                "name": "Rendering backend",
                "status": "fail",
                "hint": NO_BACKEND_HINT,
                "fix_snippet": "uv add verovio cairosvg",
                "doc_url": DOC,
            }
        ],
    }


async def test_cairosvg_missing_warns(monkeypatch):
    report = await run(
        monkeypatch, raw("verovio", verovio=True, cairosvg=False, notes=["cairosvg or libcairo2 not accessible"])
    )
    assert report["status"] == "degraded"
    assert report["checks"][1] == {
        "name": "cairosvg",
        "status": "warn",
        "hint": CAIRO_HINT,
        "fix_snippet": "sudo apt install libcairo2",
        "doc_url": DOC,
    }
    assert report["checks"][0]["status"] == "ok"


async def test_real_environment_validates():
    result = await server.call_tool_result("health_check", {})
    jsonschema.validate(result.structured_content, HEALTH_OUTPUT_SCHEMA)
    assert result.structured_content["checks"][0]["name"] == "Rendering backend"


def _registry(monkeypatch, packaged):
    assets = {server.SETUP_DOCTOR.asset: "<!doctype html>"} if packaged else {}
    monkeypatch.setattr(
        server, "ui_registry", UiRegistry([server.SCORE_VIEWER, server.SETUP_DOCTOR], InMemoryAssetSource(assets))
    )


async def test_tool_metadata_packaged(monkeypatch):
    _registry(monkeypatch, True)
    tool = next(t for t in await server.list_tools() if t.name == "health_check")
    assert tool.output_schema == HEALTH_OUTPUT_SCHEMA
    assert tool.meta["ui"]["resourceUri"] == "ui://render/setup-doctor"


async def test_tool_metadata_unpackaged(monkeypatch):
    _registry(monkeypatch, False)
    tool = next(t for t in await server.list_tools() if t.name == "health_check")
    assert tool.output_schema == HEALTH_OUTPUT_SCHEMA
    assert not tool.meta
