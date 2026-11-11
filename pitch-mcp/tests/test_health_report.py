"""Health report mapping for pitch-mcp (docs/conventions.md, Health Reports)."""

import json

import jsonschema
import pytest
from sheet_music_mcp_core.health import HEALTH_OUTPUT_SCHEMA
from sheet_music_mcp_core.ui import InMemoryAssetSource, UiRegistry

import pitch_mcp.server as server

DOC = "https://github.com/raulkivi/sheet-music-mcp/blob/main/pitch-mcp/TROUBLESHOOTING.md"
BROWSER = "The Practice Coach can still use the browser microphone."


def raw(*, librosa="0.10.2", sd="0.5.1", portaudio=True, mic=True):
    sd_ok = sd is not None
    return {
        "status": "ok" if librosa and sd_ok and portaudio else "degraded",
        "summary": "s",
        "offline_analysis": {
            "available": bool(librosa),
            "backend": "librosa/pYIN",
            "librosa_version": librosa or "unavailable",
        },
        "realtime_monitoring": {
            "available": sd_ok and portaudio,
            "sounddevice_available": sd_ok,
            "sounddevice_version": sd or "unavailable",
            "portaudio_available": sd_ok and portaudio,
            "microphone_detected": sd_ok and portaudio and mic,
        },
    }


async def run(monkeypatch, data):
    monkeypatch.setattr(server, "health_check", lambda: data)
    result = await server.call_tool_result("health_check", {})
    assert not result.is_error
    jsonschema.validate(result.structured_content, HEALTH_OUTPUT_SCHEMA)
    assert len(result.content) == 1
    assert result.content[0].text == json.dumps(data, indent=2)
    return result.structured_content


async def test_all_ok(monkeypatch):
    report = await run(monkeypatch, raw())
    assert report == {
        "status": "ready",
        "checks": [
            {"name": "librosa (offline analysis)", "status": "ok", "version": "0.10.2"},
            {"name": "Server microphone (PortAudio)", "status": "ok", "version": "0.5.1"},
            {"name": "Microphone", "status": "ok"},
        ],
    }


async def test_librosa_missing_fails(monkeypatch):
    report = await run(monkeypatch, raw(librosa=None))
    assert report["status"] == "not_ready"
    assert report["checks"][0] == {
        "name": "librosa (offline analysis)",
        "status": "fail",
        "hint": "librosa is not installed; analyze_recording fails.",
        "fix_snippet": "uv sync",
        "doc_url": DOC,
    }


async def test_sounddevice_missing_warns(monkeypatch):
    report = await run(monkeypatch, raw(sd=None))
    assert report["status"] == "degraded"
    assert [c["name"] for c in report["checks"]] == ["librosa (offline analysis)", "Server microphone (PortAudio)"]
    assert report["checks"][1] == {
        "name": "Server microphone (PortAudio)",
        "status": "warn",
        "hint": f"sounddevice is not installed; start_monitoring with the server microphone fails. {BROWSER}",
        "fix_snippet": "uv sync",
        "doc_url": DOC,
    }


async def test_portaudio_missing_warns(monkeypatch):
    report = await run(monkeypatch, raw(portaudio=False))
    assert report["status"] == "degraded"
    assert len(report["checks"]) == 2
    assert report["checks"][1] == {
        "name": "Server microphone (PortAudio)",
        "status": "warn",
        "hint": f"libportaudio2 is missing; start_monitoring with the server microphone fails. {BROWSER}",
        "fix_snippet": "sudo apt install libportaudio2",
        "doc_url": DOC,
    }


async def test_no_input_device_warns(monkeypatch):
    report = await run(monkeypatch, raw(mic=False))
    assert report["status"] == "degraded"
    assert report["checks"][1] == {"name": "Server microphone (PortAudio)", "status": "ok", "version": "0.5.1"}
    assert report["checks"][2] == {
        "name": "Microphone",
        "status": "warn",
        "hint": "No input device found on the server; use the browser microphone instead.",
        "doc_url": DOC,
    }


async def test_unknown_version_is_unset(monkeypatch):
    report = await run(monkeypatch, raw(librosa="unknown", sd="unknown"))
    assert report["checks"][0] == {"name": "librosa (offline analysis)", "status": "ok"}
    assert report["checks"][1] == {"name": "Server microphone (PortAudio)", "status": "ok"}


async def test_fail_beats_warn(monkeypatch):
    report = await run(monkeypatch, raw(librosa=None, sd=None))
    assert report["status"] == "not_ready"
    assert [c["status"] for c in report["checks"]] == ["fail", "warn"]


async def test_real_environment_validates():
    result = await server.call_tool_result("health_check", {})
    jsonschema.validate(result.structured_content, HEALTH_OUTPUT_SCHEMA)
    assert result.structured_content["checks"][0]["name"] == "librosa (offline analysis)"


def _registry(monkeypatch, packaged):
    assets = {server.SETUP_DOCTOR.asset: "<!doctype html>"} if packaged else {}
    monkeypatch.setattr(
        server, "ui_registry", UiRegistry([server.PRACTICE_COACH, server.SETUP_DOCTOR], InMemoryAssetSource(assets))
    )


async def test_tool_metadata_packaged(monkeypatch):
    _registry(monkeypatch, True)
    tool = next(t for t in await server.list_tools() if t.name == "health_check")
    assert tool.output_schema == HEALTH_OUTPUT_SCHEMA
    assert tool.meta["ui"]["resourceUri"] == "ui://pitch/setup-doctor"


async def test_tool_metadata_unpackaged(monkeypatch):
    _registry(monkeypatch, False)
    tool = next(t for t in await server.list_tools() if t.name == "health_check")
    assert tool.output_schema == HEALTH_OUTPUT_SCHEMA
    assert not tool.meta
