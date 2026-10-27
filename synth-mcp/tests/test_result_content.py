"""Result content blocks appended after the JSON text (docs/conventions.md, Result Content).

No soundfont is needed: synthesize_midi is replaced by a fake that writes a small WAV file.
"""

import json
import wave
from pathlib import Path

import pytest

import synth_mcp.server as server
from synth_mcp.engine import ProcessingError, parse_parts
from synth_mcp.server import call_tool

from .test_server import VALID_MUSICXML


@pytest.fixture(autouse=True)
def output_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
    return tmp_path


def _write_wav(midi_bytes, output_path):
    with wave.open(output_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0" * 800)
    return 4.004


class TestSynthesizeResultContent:
    async def test_json_block_unchanged(self, monkeypatch, output_root):
        monkeypatch.setattr(server, "synthesize_midi", _write_wav)
        out = str(output_root / "practice.wav")

        result = await call_tool(
            "synthesize", {"musicxml": VALID_MUSICXML, "tempo_factor": 0.75, "output_path": out}
        )

        expected = {
            "audio_path": out,
            "format": "wav",
            "duration_seconds": 4.0,
            "parts_included": [p["id"] for p in parse_parts(VALID_MUSICXML)],
            "tempo_factor": 0.75,
        }
        assert result[0].type == "text"
        assert result[0].text == json.dumps(expected, indent=2)

    async def test_appends_wav_link(self, monkeypatch, output_root):
        monkeypatch.setattr(server, "synthesize_midi", _write_wav)
        out = output_root / "practice.wav"

        result = await call_tool("synthesize", {"musicxml": VALID_MUSICXML, "output_path": str(out)})

        assert [block.type for block in result] == ["text", "resource_link"]
        link = result[1]
        assert link.mime_type == "audio/wav"
        assert link.uri.startswith("file://")
        assert link.uri == out.resolve().as_uri()
        assert link.name == "practice.wav"
        assert link.size == out.stat().st_size

    async def test_auto_generated_path_is_linked(self, monkeypatch, output_root):
        monkeypatch.setattr(server, "synthesize_midi", _write_wav)
        monkeypatch.setattr(server, "generate_output_path", lambda p: str(output_root / "auto.wav"))

        result = await call_tool("synthesize", {"musicxml": VALID_MUSICXML})

        audio_path = json.loads(result[0].text)["audio_path"]
        assert result[1].uri == Path(audio_path).resolve().as_uri()

    async def test_no_image_block(self, monkeypatch, output_root):
        monkeypatch.setattr(server, "synthesize_midi", _write_wav)

        result = await call_tool(
            "synthesize", {"musicxml": VALID_MUSICXML, "output_path": str(output_root / "a.wav")}
        )

        assert all(block.type != "image" for block in result)


class TestSynthesizeErrorsHaveNoExtraBlocks:
    async def test_synthesis_error(self, monkeypatch):
        def fail(midi_bytes, output_path):
            raise ProcessingError("no soundfont", "SOUNDFONT_NOT_FOUND")

        monkeypatch.setattr(server, "synthesize_midi", fail)

        result = await call_tool("synthesize", {"musicxml": VALID_MUSICXML})

        assert len(result) == 1
        assert json.loads(result[0].text)["error_code"] == "SOUNDFONT_NOT_FOUND"

    async def test_validation_error(self):
        result = await call_tool("synthesize", {"musicxml": "not xml"})

        assert len(result) == 1
        assert "error" in json.loads(result[0].text)

    async def test_missing_file(self, monkeypatch, output_root):
        monkeypatch.setattr(server, "synthesize_midi", lambda midi, path: 1.0)

        result = await call_tool(
            "synthesize", {"musicxml": VALID_MUSICXML, "output_path": str(output_root / "x.wav")}
        )

        assert len(result) == 1
