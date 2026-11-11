"""Health report mapping for synth-mcp (docs/conventions.md, Health Reports)."""

import builtins
import importlib.metadata
import sys
import types

import jsonschema
import pytest
from sheet_music_mcp_core.health import HEALTH_OUTPUT_SCHEMA
from sheet_music_mcp_core.ui import InMemoryAssetSource, UiRegistry

import synth_mcp.server as server

DOC = "https://github.com/raulkivi/sheet-music-mcp/blob/main/synth-mcp/TROUBLESHOOTING.md"
SF_FIX = '"env": {"SYNTH_SOUNDFONT_PATH": "/path/to/TimGM6mb.sf2"}'
UNSET_HINT = (
    "SYNTH_SOUNDFONT_PATH is not set; download an SF2 soundfont such as TimGM6mb.sf2 "
    "(https://sourceforge.net/projects/timidity/files/)."
)
FS_ERR = "libfluidsynth.so.3: cannot open shared object file"


def fs_version():
    try:
        return importlib.metadata.version("pyfluidsynth")
    except importlib.metadata.PackageNotFoundError:
        return None


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Soundfont present, fluidsynth and music21 importable (fakes), unless a test overrides."""
    sf2 = tmp_path / "t.sf2"
    sf2.write_bytes(b"x")
    monkeypatch.setenv("SYNTH_SOUNDFONT_PATH", str(sf2))
    fs = types.ModuleType("fluidsynth")
    m21 = types.ModuleType("music21")
    m21.__version__ = "9.9.9"
    monkeypatch.setitem(sys.modules, "fluidsynth", fs)
    monkeypatch.setitem(sys.modules, "music21", m21)
    return sf2


def fluidsynth_oserror(monkeypatch):
    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "fluidsynth":
            raise OSError(FS_ERR)
        return real(name, *a, **k)

    monkeypatch.delitem(sys.modules, "fluidsynth", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake)


async def report(monkeypatch=None):
    result = await server.call_tool_result("health_check", {})
    assert not result.is_error
    jsonschema.validate(result.structured_content, HEALTH_OUTPUT_SCHEMA)
    return result


def fs_ok():
    check = {"name": "FluidSynth", "status": "ok"}
    if fs_version():
        check["version"] = fs_version()
    return check


async def test_all_ok(env):
    result = await report()
    assert result.structured_content == {
        "status": "ready",
        "checks": [
            {"name": "Soundfont", "status": "ok"},
            fs_ok(),
            {"name": "music21", "status": "ok", "version": "9.9.9"},
        ],
    }
    text = result.content[0].text
    assert text == (
        "synth-mcp health check\n" + "=" * 22 + "\n"
        f"Soundfont:    OK — {env}\n"
        "FluidSynth:   OK\n"
        "music21:      OK\n"
        "\nOverall:      READY"
    )


async def test_soundfont_unset(env, monkeypatch):
    monkeypatch.delenv("SYNTH_SOUNDFONT_PATH")
    result = await report()
    assert result.structured_content["status"] == "not_ready"
    assert result.structured_content["checks"][0] == {
        "name": "Soundfont",
        "status": "fail",
        "hint": UNSET_HINT,
        "fix_snippet": SF_FIX,
        "doc_url": DOC,
    }
    text = result.content[0].text
    assert "Soundfont:    MISSING — SYNTH_SOUNDFONT_PATH is not set" in text
    assert text.endswith(
        "\nOverall:      NOT READY\n"
        "Fix the issues above, then restart the server and run health_check again."
    )
    assert "  https://sourceforge.net/projects/timidity/files/" in text


async def test_soundfont_file_missing(env, monkeypatch, tmp_path):
    path = str(tmp_path / "nope.sf2")
    monkeypatch.setenv("SYNTH_SOUNDFONT_PATH", path)
    result = await report()
    assert result.structured_content["checks"][0] == {
        "name": "Soundfont",
        "status": "fail",
        "hint": f"No soundfont file at {path!r}.",
        "fix_snippet": SF_FIX,
        "doc_url": DOC,
    }
    assert f"Soundfont:    MISSING — file not found at {path!r}" in result.content[0].text


async def test_fluidsynth_oserror(env, monkeypatch):
    fluidsynth_oserror(monkeypatch)
    result = await report()
    assert result.structured_content["status"] == "not_ready"
    assert result.structured_content["checks"][1] == {
        "name": "FluidSynth",
        "status": "fail",
        "hint": f"FluidSynth could not be loaded: {FS_ERR}",
        "fix_snippet": "sudo apt install libfluidsynth-dev",
        "doc_url": DOC,
    }
    assert f"FluidSynth:   MISSING — {FS_ERR}" in result.content[0].text


async def test_fluidsynth_importerror(env, monkeypatch):
    monkeypatch.setitem(sys.modules, "fluidsynth", None)
    result = await report()
    check = result.structured_content["checks"][1]
    assert check["status"] == "fail"
    assert check["hint"].startswith("FluidSynth could not be loaded: ")
    assert check["fix_snippet"] == "sudo apt install libfluidsynth-dev"
    assert "version" not in check


async def test_music21_missing(env, monkeypatch):
    monkeypatch.setitem(sys.modules, "music21", None)
    result = await report()
    assert result.structured_content["status"] == "not_ready"
    check = result.structured_content["checks"][2]
    assert check["name"] == "music21" and check["status"] == "fail"
    assert check["hint"].startswith("music21 is not installed: ")
    assert check["fix_snippet"] == "uv sync"
    assert check["doc_url"] == DOC
    assert "music21:      MISSING — " in result.content[0].text


async def test_everything_missing_keeps_order(env, monkeypatch):
    monkeypatch.delenv("SYNTH_SOUNDFONT_PATH")
    monkeypatch.setitem(sys.modules, "music21", None)
    monkeypatch.setitem(sys.modules, "fluidsynth", None)
    result = await report()
    assert [c["name"] for c in result.structured_content["checks"]] == ["Soundfont", "FluidSynth", "music21"]
    assert [c["status"] for c in result.structured_content["checks"]] == ["fail"] * 3


def _registry(monkeypatch, packaged):
    assets = {server.SETUP_DOCTOR.asset: "<!doctype html>"} if packaged else {}
    monkeypatch.setattr(
        server, "ui_registry", UiRegistry([server.PRACTICE_PLAYER, server.SETUP_DOCTOR], InMemoryAssetSource(assets))
    )


async def test_tool_metadata_packaged(monkeypatch):
    _registry(monkeypatch, True)
    tool = next(t for t in await server.list_tools() if t.name == "health_check")
    assert tool.output_schema == HEALTH_OUTPUT_SCHEMA
    assert tool.meta["ui"]["resourceUri"] == "ui://synth/setup-doctor"


async def test_tool_metadata_unpackaged(monkeypatch):
    _registry(monkeypatch, False)
    tool = next(t for t in await server.list_tools() if t.name == "health_check")
    assert tool.output_schema == HEALTH_OUTPUT_SCHEMA
    assert not tool.meta
