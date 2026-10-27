"""Score references: scores passed as file paths (docs/conventions.md, Score References;
docs/research/ux-wave2-plan.md §4).

Unit tests mock the heavy synthesis steps (extract_midi, synthesize_midi) so no soundfont is
needed. The integration test at the end synthesizes for real when a soundfont exists.
"""

import asyncio
import json
import os
import wave
import zipfile
from pathlib import Path

import pytest
from mcp import Client
from sheet_music_mcp_core.references import exactly_one

import synth_mcp.server as server
from synth_mcp.server import app, call_tool, list_tools

from .test_server import VALID_MUSICXML

SENTINEL = "SENTINEL-must-never-leak-7f3a"

CONTAINER_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<container><rootfiles><rootfile full-path="score.musicxml"/></rootfiles></container>'
)


@pytest.fixture(autouse=True)
def output_root(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(root))
    monkeypatch.delenv("SHEET_MUSIC_INPUT_ROOTS", raising=False)
    return root


def _write_mxl(path: Path, text: str, *, container: bool = True) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        if container:
            archive.writestr("META-INF/container.xml", CONTAINER_XML)
        archive.writestr("score.musicxml", text)
    return path


def _with_client(call):
    async def _go():
        async with Client(app) as client:
            return await call(client)

    return asyncio.run(_go())


def _json(result):
    return json.loads(result[0].text)


class FakeEngine:
    """Records the MusicXML the engine receives and writes a small WAV instead of synthesizing."""

    def __init__(self):
        self.musicxml = []

    def extract_midi(self, musicxml, part_ids, tempo_factor):
        self.musicxml.append(musicxml)
        return b"MThd-fake"

    @staticmethod
    def synthesize_midi(midi_bytes, output_path):
        with wave.open(output_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\0\0" * 800)
        return 4.004


@pytest.fixture
def engine(monkeypatch):
    fake = FakeEngine()
    monkeypatch.setattr(server, "extract_midi", fake.extract_midi)
    monkeypatch.setattr(server, "synthesize_midi", fake.synthesize_midi)
    return fake


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["get_parts", "synthesize", "describe_score"])
async def test_schema_takes_exactly_one_of_musicxml_and_path(name):
    tool = next(t for t in await list_tools() if t.name == name)
    schema = tool.input_schema

    assert {"musicxml", "musicxml_path"} <= set(schema["properties"])
    assert schema["oneOf"] == exactly_one()["oneOf"]
    assert "musicxml" not in schema.get("required", [])


# ---------------------------------------------------------------------------
# get_parts
# ---------------------------------------------------------------------------


class TestGetPartsByPath:
    async def test_path_gives_same_content_as_inline(self, output_root):
        path = output_root / "s.musicxml"
        path.write_text(VALID_MUSICXML, encoding="utf-8")

        inline = await call_tool("get_parts", {"musicxml": VALID_MUSICXML})
        by_path = await call_tool("get_parts", {"musicxml_path": str(path)})

        assert by_path[0].text == inline[0].text
        assert [p["id"] for p in _json(by_path)["parts"]] == ["P1", "P2"]

    @pytest.mark.parametrize("container", [True, False], ids=["container", "plain-member"])
    async def test_mxl_path(self, output_root, container):
        path = _write_mxl(output_root / "s.mxl", VALID_MUSICXML, container=container)

        inline = await call_tool("get_parts", {"musicxml": VALID_MUSICXML})
        by_path = await call_tool("get_parts", {"musicxml_path": str(path)})

        assert by_path[0].text == inline[0].text

    async def test_relative_path_resolves_against_output_root(self, output_root):
        (output_root / "s.xml").write_text(VALID_MUSICXML, encoding="utf-8")

        result = await call_tool("get_parts", {"musicxml_path": "s.xml"})

        assert [p["id"] for p in _json(result)["parts"]] == ["P1", "P2"]

    async def test_missing_file_is_file_not_found(self, output_root):
        result = await call_tool("get_parts", {"musicxml_path": str(output_root / "none.musicxml")})

        assert _json(result)["error_code"] == "FILE_NOT_FOUND"

    async def test_file_that_is_not_musicxml_is_invalid_input(self, output_root):
        path = output_root / "s.musicxml"
        path.write_text(f"<html>{SENTINEL}</html>", encoding="utf-8")

        result = await call_tool("get_parts", {"musicxml_path": str(path)})

        assert _json(result)["error_code"] == "INVALID_INPUT"
        assert SENTINEL not in result[0].text


# ---------------------------------------------------------------------------
# synthesize (acceptance: path call == inline call, same duration and parts)
# ---------------------------------------------------------------------------


class TestSynthesizeByPath:
    async def test_mxl_path_gives_same_result_as_inline(self, engine, output_root):
        path = _write_mxl(output_root / "s.mxl", VALID_MUSICXML)
        inline_out = str(output_root / "inline.wav")
        path_out = str(output_root / "path.wav")

        inline = await call_tool(
            "synthesize", {"musicxml": VALID_MUSICXML, "tempo_factor": 0.75, "output_path": inline_out}
        )
        by_path = await call_tool(
            "synthesize", {"musicxml_path": str(path), "tempo_factor": 0.75, "output_path": path_out}
        )

        # The engine receives the identical MusicXML text either way.
        assert engine.musicxml == [VALID_MUSICXML, VALID_MUSICXML]
        inline_data, path_data = _json(inline), _json(by_path)
        assert inline_data.pop("audio_path") == inline_out
        assert path_data.pop("audio_path") == path_out
        assert path_data == inline_data
        assert path_data["duration_seconds"] == 4.0
        assert path_data["parts_included"] == ["P1", "P2"]
        assert [b.type for b in by_path] == [b.type for b in inline] == ["text", "resource_link"]

    async def test_musicxml_path_selects_parts(self, engine, output_root):
        path = output_root / "s.musicxml"
        path.write_text(VALID_MUSICXML, encoding="utf-8")

        result = await call_tool(
            "synthesize",
            {"musicxml_path": str(path), "parts": ["Alto"], "output_path": str(output_root / "a.wav")},
        )

        assert _json(result)["parts_included"] == ["P2"]

    async def test_path_error_stops_before_the_engine(self, engine, output_root):
        result = await call_tool("synthesize", {"musicxml_path": str(output_root / "none.musicxml")})

        assert _json(result)["error_code"] == "FILE_NOT_FOUND"
        assert engine.musicxml == []


# ---------------------------------------------------------------------------
# Read policy: paths outside the roots never leak content
# ---------------------------------------------------------------------------


def _outside_score(tmp_path: Path) -> Path:
    outside = tmp_path / "outside"
    outside.mkdir(exist_ok=True)
    secret = outside / "secret.musicxml"
    secret.write_text(f"<score-partwise><!-- {SENTINEL} --></score-partwise>", encoding="utf-8")
    return secret


class TestReadPolicy:
    @pytest.mark.parametrize("tool", ["get_parts", "synthesize", "describe_score"])
    async def test_etc_passwd_is_rejected(self, tool):
        result = await call_tool(tool, {"musicxml_path": "/etc/passwd"})

        data = _json(result)
        assert data["error_code"] == "INVALID_PARAMETER"
        assert "root:" not in result[0].text

    @pytest.mark.parametrize("tool", ["get_parts", "synthesize", "describe_score"])
    async def test_parent_traversal_is_rejected(self, tool, tmp_path):
        (tmp_path / "x.musicxml").write_text(f"<score-partwise>{SENTINEL}</score-partwise>")

        result = await call_tool(tool, {"musicxml_path": "../x.musicxml"})

        assert _json(result)["error_code"] == "INVALID_PARAMETER"
        assert SENTINEL not in result[0].text

    @pytest.mark.parametrize("tool", ["get_parts", "synthesize", "describe_score"])
    async def test_symlink_pointing_outside_is_rejected(self, tool, tmp_path, output_root):
        link = output_root / "link.musicxml"
        link.symlink_to(_outside_score(tmp_path))

        result = await call_tool(tool, {"musicxml_path": str(link)})

        assert _json(result)["error_code"] == "INVALID_PARAMETER"
        assert SENTINEL not in result[0].text

    async def test_input_roots_extend_the_allowed_folders(self, tmp_path, monkeypatch):
        extra = tmp_path / "library"
        extra.mkdir()
        (extra / "s.musicxml").write_text(VALID_MUSICXML, encoding="utf-8")
        monkeypatch.setenv("SHEET_MUSIC_INPUT_ROOTS", str(extra))

        result = await call_tool("get_parts", {"musicxml_path": str(extra / "s.musicxml")})

        assert [p["id"] for p in _json(result)["parts"]] == ["P1", "P2"]


# ---------------------------------------------------------------------------
# Through the protocol (make_handlers validates the oneOf)
# ---------------------------------------------------------------------------


class TestProtocol:
    @pytest.mark.parametrize("tool", ["get_parts", "synthesize", "describe_score"])
    def test_both_inline_and_path_is_an_error(self, tool, output_root):
        args = {"musicxml": VALID_MUSICXML, "musicxml_path": str(output_root / "s.musicxml")}

        result = _with_client(lambda client: client.call_tool(tool, args))

        assert result.is_error
        data = json.loads(result.content[0].text)
        assert data["error_code"] == "INVALID_PARAMETER"
        assert "<score-partwise" not in result.content[0].text

    @pytest.mark.parametrize("tool", ["get_parts", "synthesize", "describe_score"])
    def test_neither_inline_nor_path_is_an_error(self, tool):
        result = _with_client(lambda client: client.call_tool(tool, {}))

        assert result.is_error
        assert json.loads(result.content[0].text)["error_code"] == "INVALID_PARAMETER"

    def test_path_call_through_the_protocol(self, output_root):
        path = output_root / "s.musicxml"
        path.write_text(VALID_MUSICXML, encoding="utf-8")

        result = _with_client(lambda client: client.call_tool("get_parts", {"musicxml_path": str(path)}))

        assert not result.is_error
        assert [p["id"] for p in json.loads(result.content[0].text)["parts"]] == ["P1", "P2"]


# ---------------------------------------------------------------------------
# describe_score
# ---------------------------------------------------------------------------


class TestDescribeScore:
    async def test_is_listed(self):
        assert "describe_score" in {t.name for t in await list_tools()}

    def test_is_listed_through_the_protocol(self):
        result = _with_client(lambda client: client.list_tools())

        assert "describe_score" in {t.name for t in result.tools}

    async def test_inline(self):
        result = await call_tool("describe_score", {"musicxml": VALID_MUSICXML})

        data = _json(result)
        assert [p["id"] for p in data["parts"]] == ["P1", "P2"]
        assert [p["name"] for p in data["parts"]] == ["Soprano", "Alto"]
        assert data["measures"] == 1

    async def test_path_matches_inline(self, output_root):
        path = _write_mxl(output_root / "s.mxl", VALID_MUSICXML)

        inline = await call_tool("describe_score", {"musicxml": VALID_MUSICXML})
        by_path = await call_tool("describe_score", {"musicxml_path": str(path)})

        assert by_path[0].text == inline[0].text

    async def test_malformed_inline_is_invalid_input(self):
        result = await call_tool("describe_score", {"musicxml": "not xml"})

        assert _json(result)["error_code"] == "INVALID_INPUT"

    async def test_listed_in_capabilities(self):
        data = _json(await call_tool("list_capabilities", {}))

        assert "describe_score" in data["tools"]
        assert "mxl" in data["input_formats"]
        assert data["input_parameters"] == ["musicxml", "musicxml_path"]


# ---------------------------------------------------------------------------
# Integration: real synthesis both ways
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent.parent.parent / "omr-mcp" / "test_samples" / "pdmx_satb_samples" / "mxl"
DEFAULT_SOUNDFONT = "/usr/share/sounds/sf2/TimGM6mb.sf2"


def _soundfont() -> str | None:
    for candidate in (os.environ.get("SYNTH_SOUNDFONT_PATH"), DEFAULT_SOUNDFONT):
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


@pytest.mark.integration
@pytest.mark.skipif(_soundfont() is None, reason="No soundfont: set SYNTH_SOUNDFONT_PATH")
async def test_real_synthesis_by_path_matches_inline(output_root, monkeypatch):
    from sheet_music_mcp_core.paths import max_score_bytes
    from sheet_music_mcp_core.scores import read_score_file

    monkeypatch.setenv("SYNTH_SOUNDFONT_PATH", _soundfont())
    # A real SATB fixture when the omr-mcp samples are present, else the two-part test score.
    path = output_root / "s.mxl"
    fixtures = sorted(FIXTURE_DIR.glob("*.mxl"))
    if fixtures:
        path.write_bytes(fixtures[0].read_bytes())
    else:
        _write_mxl(path, VALID_MUSICXML)
    musicxml = read_score_file(path, max_bytes=max_score_bytes())

    inline = await call_tool("synthesize", {"musicxml": musicxml, "output_path": str(output_root / "i.wav")})
    by_path = await call_tool("synthesize", {"musicxml_path": str(path), "output_path": str(output_root / "p.wav")})

    inline_data, path_data = _json(inline), _json(by_path)
    assert "error" not in inline_data, inline_data
    assert set(path_data) == {"audio_path", "format", "duration_seconds", "parts_included", "tempo_factor"}
    assert path_data["duration_seconds"] > 0
    assert path_data["duration_seconds"] == inline_data["duration_seconds"]
    assert path_data["parts_included"] == inline_data["parts_included"]
    assert len(path_data["parts_included"]) >= 2
    assert Path(path_data["audio_path"]).is_file()
