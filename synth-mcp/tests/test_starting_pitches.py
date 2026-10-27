"""starting_pitches: each part's first note as text and a short piano clip (UX Wave 3 C13, W3-6).

FluidSynth is never used: synthesize_midi is replaced by a fake that writes a stereo 44.1 kHz WAV,
or left alone with no soundfont configured to exercise the text-only result.
"""

import asyncio
import json
import math
import struct
import wave
from pathlib import Path

import pytest
from mcp import Client
from sheet_music_mcp_core.annotations import WRITES_FILE
from sheet_music_mcp_core.scores import first_pitches

import synth_mcp.clip as clip
from synth_mcp.clip import clip_midi, downmix_wav, pitches_text, starting_pitches
from synth_mcp.engine import ProcessingError
from synth_mcp.server import app, call_tool, list_tools

from .midi_helpers import fixture, read_midi

SATB = fixture("satb_4bars.musicxml")

RESTS_IN_ALTO = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Soprano</part-name></score-part>
    <score-part id="P2"><part-name>Alto</part-name></score-part>
  </part-list>
  <part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
    <note><pitch><step>E</step><octave>5</octave></pitch><duration>4</duration><type>whole</type></note>
  </measure></part>
  <part id="P2"><measure number="1"><attributes><divisions>1</divisions></attributes>
    <note><rest/><duration>4</duration><type>whole</type></note>
  </measure></part>
</score-partwise>"""


@pytest.fixture(autouse=True)
def output_root(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(root))
    monkeypatch.delenv("SYNTH_SOUNDFONT_PATH", raising=False)
    return root


def _fake_synth(seconds: float):
    """A synthesize_midi stand-in that writes a stereo 44.1 kHz 16-bit WAV of a 440 Hz tone."""
    calls = []

    def fake(midi_bytes, output_path):
        calls.append(midi_bytes)
        _write_tone(output_path, seconds, rate=44100, channels=2)
        return seconds

    fake.calls = calls
    return fake


def _write_tone(path, seconds, *, rate, channels, amplitude=8000):
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        samples = (int(amplitude * math.sin(2 * math.pi * 440 * i / rate)) for i in range(frames))
        w.writeframes(b"".join(struct.pack("<h", s) * channels for s in samples))


def _json(result):
    return json.loads(result[0].text)


# ---------------------------------------------------------------------------
# Engine pieces
# ---------------------------------------------------------------------------


class TestStartingPitches:
    def test_all_parts_in_score_order(self):
        entries = starting_pitches(SATB)
        expected = first_pitches(SATB)
        assert [e["id"] for e in entries] == [p["id"] for p in expected]
        assert [e["pitch"] for e in entries] == [p["pitch"] for p in expected]

    def test_text(self):
        assert pitches_text(starting_pitches(SATB)) == "S: D5, A: A4, T: F#4, B: D3"

    def test_selected_parts_keep_score_order(self):
        entries = starting_pitches(SATB, ["Bass", "S"])
        assert pitches_text(entries) == "S: D5, B: D3"

    def test_unknown_part_has_choices(self):
        with pytest.raises(ProcessingError) as exc:
            starting_pitches(SATB, ["Viola"])
        assert exc.value.error_code == "INVALID_PARAMETER"
        assert "Alto (P2)" in exc.value.choices

    def test_part_without_pitches_is_left_out_of_the_text(self):
        entries = starting_pitches(RESTS_IN_ALTO)
        assert [e["pitch"] for e in entries] == ["E5", None]
        assert pitches_text(entries) == "S: E5"


class TestClipMidi:
    def test_one_note_per_part_then_the_chord(self):
        tpq, tracks = read_midi(clip_midi([74, 69, 66, 50]))
        notes = [(e.tick, e.value, e.velocity) for t in tracks for e in t.of("note_on")]
        notes.sort(key=lambda n: (n[0], -n[1]))
        assert notes[:4] == [(0, 74, 80), (tpq, 69, 80), (2 * tpq, 66, 80), (3 * tpq, 50, 80)]
        assert sorted(n[1] for n in notes[4:]) == [50, 66, 69, 74]
        assert {n[0] for n in notes[4:]} == {4 * tpq}
        assert {n[2] for n in notes[4:]} == {80}

    def test_one_second_per_note_and_two_for_the_chord(self):
        tpq, tracks = read_midi(clip_midi([74, 69]))
        assert [bpm for t in tracks for e in t.of("tempo") for bpm in [e.value]] == [60.0]
        offs = sorted(e.tick for t in tracks for e in t.of("note_off"))
        assert offs[-1] == 4 * tpq  # 1 s + 1 s + 2 s chord

    def test_piano(self):
        _, tracks = read_midi(clip_midi([60, 64]))
        programs = [e.value for t in tracks for e in t.of("program")]
        assert programs and set(programs) == {0}

    def test_unison_chord_plays_each_pitch_once(self):
        _, tracks = read_midi(clip_midi([60, 60]))
        notes = [e.value for t in tracks for e in t.of("note_on")]
        assert notes == [60, 60, 60]


class TestDownmix:
    def test_stereo_44k_to_mono_16k(self, tmp_path):
        src, dst = tmp_path / "in.wav", tmp_path / "out.wav"
        _write_tone(src, 1.0, rate=44100, channels=2)

        duration = downmix_wav(str(src), str(dst))

        with wave.open(str(dst)) as w:
            assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000)
            assert abs(w.getnframes() - 16000) <= 1
            data = w.readframes(w.getnframes())
        assert abs(duration - 1.0) < 0.001
        peak = max(abs(s) for (s,) in struct.iter_unpack("<h", data))
        assert 7000 < peak <= 8001  # the tone survives at its level

    def test_mono_input(self, tmp_path):
        src, dst = tmp_path / "in.wav", tmp_path / "out.wav"
        _write_tone(src, 0.5, rate=22050, channels=1)

        downmix_wav(str(src), str(dst))

        with wave.open(str(dst)) as w:
            assert (w.getnchannels(), w.getframerate()) == (1, 16000)
            assert abs(w.getnframes() - 8000) <= 1


# ---------------------------------------------------------------------------
# The tool
# ---------------------------------------------------------------------------


class TestToolWithoutAudio:
    async def test_no_soundfont_gives_text_and_reason(self):
        result = await call_tool("starting_pitches", {"musicxml": SATB})

        assert len(result) == 1
        data = _json(result)
        assert "error" not in data
        assert data["text"] == "S: D5, A: A4, T: F#4, B: D3"
        assert data["audio_path"] is None
        assert data["duration_seconds"] is None
        assert "SYNTH_SOUNDFONT_PATH" in data["audio_unavailable"]
        assert data["parts"] == [
            {"id": "P1", "name": "Soprano", "label": "S", "pitch": "D5"},
            {"id": "P2", "name": "Alto", "label": "A", "pitch": "A4"},
            {"id": "P3", "name": "Tenor", "label": "T", "pitch": "F#4"},
            {"id": "P4", "name": "Bass", "label": "B", "pitch": "D3"},
        ]

    async def test_no_audio_folder_is_created(self, output_root):
        await call_tool("starting_pitches", {"musicxml": SATB})
        assert not (output_root / "audio").exists()

    def test_not_an_error_over_the_protocol(self):
        async def _go():
            async with Client(app) as client:
                return await client.call_tool("starting_pitches", {"musicxml": SATB})

        result = asyncio.run(_go())
        assert not result.is_error
        assert json.loads(result.content[0].text)["audio_unavailable"]

    async def test_score_without_any_pitch(self):
        rests = RESTS_IN_ALTO.replace(
            "<pitch><step>E</step><octave>5</octave></pitch>", "<rest/>"
        )
        data = _json(await call_tool("starting_pitches", {"musicxml": rests}))
        assert data["text"] == ""
        assert data["audio_path"] is None
        assert data["audio_unavailable"]


class TestToolWithAudio:
    async def test_small_clip_is_inline(self, monkeypatch, output_root):
        fake = _fake_synth(6.0)
        monkeypatch.setattr(clip, "synthesize_midi", fake)

        result = await call_tool("starting_pitches", {"musicxml": SATB})

        assert [b.type for b in result] == ["text", "audio", "resource_link"]
        data = _json(result)
        path = Path(data["audio_path"])
        assert path.parent == output_root / "audio"
        assert path.name.startswith("starting-pitches-") and path.suffix == ".wav"
        assert data["duration_seconds"] == 6.0
        assert "audio_unavailable" not in data
        assert result[1].mime_type == "audio/wav"
        assert result[2].uri == path.resolve().as_uri()
        with wave.open(str(path)) as w:
            assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (1, 16000, 2)
        # The clip played is the starting-pitch MIDI: four notes, then the chord.
        _, tracks = read_midi(fake.calls[0])
        assert len([e for t in tracks for e in t.of("note_on")]) == 8

    async def test_large_clip_is_only_linked(self, monkeypatch):
        monkeypatch.setattr(clip, "synthesize_midi", _fake_synth(8.0))  # 8 s * 32 KB/s > 200 KB

        result = await call_tool("starting_pitches", {"musicxml": SATB})

        assert [b.type for b in result] == ["text", "resource_link"]

    async def test_parts_select_the_clip(self, monkeypatch):
        fake = _fake_synth(1.0)
        monkeypatch.setattr(clip, "synthesize_midi", fake)

        result = await call_tool("starting_pitches", {"musicxml": SATB, "parts": ["A", "T"]})

        assert _json(result)["text"] == "A: A4, T: F#4"
        _, tracks = read_midi(fake.calls[0])
        assert sorted(e.value for t in tracks for e in t.of("note_on")) == [66, 66, 69, 69]

    async def test_output_path_inside_root(self, monkeypatch, output_root):
        monkeypatch.setattr(clip, "synthesize_midi", _fake_synth(1.0))

        result = await call_tool(
            "starting_pitches", {"musicxml": SATB, "output_path": "start.wav"}
        )

        assert _json(result)["audio_path"] == str(output_root / "start.wav")
        assert (output_root / "start.wav").is_file()

    async def test_output_path_outside_root_is_rejected(self, monkeypatch, tmp_path):
        monkeypatch.setattr(clip, "synthesize_midi", _fake_synth(1.0))

        result = await call_tool(
            "starting_pitches", {"musicxml": SATB, "output_path": str(tmp_path / "x.wav")}
        )

        assert _json(result)["error_code"] == "INVALID_PARAMETER"

    async def test_render_failure_degrades_to_text(self, monkeypatch, output_root):
        def fail(midi_bytes, output_path):
            raise ProcessingError("FluidSynth library not available: no lib", "PROCESSING_FAILED")

        monkeypatch.setattr(clip, "synthesize_midi", fail)

        result = await call_tool("starting_pitches", {"musicxml": SATB})

        assert len(result) == 1
        data = _json(result)
        assert data["audio_path"] is None
        assert "FluidSynth" in data["audio_unavailable"]
        assert not list(output_root.rglob("*.wav"))

    async def test_musicxml_path(self, output_root):
        path = output_root / "s.musicxml"
        path.write_text(SATB, encoding="utf-8")

        result = await call_tool("starting_pitches", {"musicxml_path": str(path)})

        assert _json(result)["text"] == "S: D5, A: A4, T: F#4, B: D3"

    async def test_unknown_part(self):
        data = _json(await call_tool("starting_pitches", {"musicxml": SATB, "parts": ["Viola"]}))
        assert data["error_code"] == "INVALID_PARAMETER"
        assert data["choices"]

    async def test_invalid_musicxml(self):
        data = _json(await call_tool("starting_pitches", {"musicxml": "not xml"}))
        assert data["error_code"] == "INVALID_INPUT"


async def test_schema():
    tool = next(t for t in await list_tools() if t.name == "starting_pitches")
    assert tool.title == "Play starting pitches"
    assert tool.annotations.model_dump(exclude_none=True) == dict(WRITES_FILE)
    props = tool.input_schema["properties"]
    assert {"musicxml", "musicxml_path", "parts", "output_path"} <= set(props)
    assert "oneOf" in tool.input_schema


# ---------------------------------------------------------------------------
# Integration: real FluidSynth rendering
# ---------------------------------------------------------------------------

DEFAULT_SOUNDFONT = "/usr/share/sounds/sf2/TimGM6mb.sf2"


def _soundfont() -> str | None:
    import os

    for candidate in (os.environ.get("SYNTH_SOUNDFONT_PATH"), DEFAULT_SOUNDFONT):
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


@pytest.mark.integration
@pytest.mark.skipif(_soundfont() is None, reason="No soundfont: set SYNTH_SOUNDFONT_PATH")
async def test_real_clip_is_inline_mono_16k(monkeypatch):
    monkeypatch.setenv("SYNTH_SOUNDFONT_PATH", _soundfont())

    result = await call_tool("starting_pitches", {"musicxml": SATB})

    data = _json(result)
    assert "audio_unavailable" not in data, data
    assert [b.type for b in result] == ["text", "audio", "resource_link"]  # 4 parts fit in 200 KB
    assert 5.5 < data["duration_seconds"] < 7.0
    with wave.open(data["audio_path"]) as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (1, 16000, 2)


@pytest.mark.integration
@pytest.mark.skipif(_soundfont() is None, reason="No soundfont: set SYNTH_SOUNDFONT_PATH")
async def test_real_practice_track(monkeypatch, output_root):
    monkeypatch.setenv("SYNTH_SOUNDFONT_PATH", _soundfont())

    result = await call_tool(
        "synthesize",
        {"musicxml": SATB, "preset": "learning", "focus_part": "Alto", "count_in_bars": 1,
         "metronome": True, "timbre": "piano", "measures": [3, 4], "repeat": 2,
         "output_path": str(output_root / "practice.wav")},
    )

    data = _json(result)
    assert "error" not in data, data
    # 1 count-in bar + 2 × 2 bars of 4/4 at 120 BPM = 10 s, plus the release tail.
    assert 10.0 <= data["duration_seconds"] < 13.0
