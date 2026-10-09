"""Tests for synth_mcp.engine."""

import os
import wave
from pathlib import Path
from unittest.mock import patch

import pytest

from synth_mcp.engine import (
    ProcessingError,
    _get_wav_duration,
    extract_midi,
    parse_parts,
    synthesize_midi,
)

# ---------------------------------------------------------------------------
# Shared fixture: minimal valid two-part MusicXML
# ---------------------------------------------------------------------------

SIMPLE_MUSICXML = """\
<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Soprano</part-name></score-part>
    <score-part id="P2"><part-name>Alto</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <note>
        <pitch><step>C</step><octave>5</octave></pitch>
        <duration>4</duration><type>whole</type>
      </note>
    </measure>
  </part>
  <part id="P2">
    <measure number="1">
      <note>
        <pitch><step>A</step><octave>4</octave></pitch>
        <duration>4</duration><type>whole</type>
      </note>
    </measure>
  </part>
</score-partwise>"""


# ---------------------------------------------------------------------------
# parse_parts
# ---------------------------------------------------------------------------

class TestParseParts:
    def test_returns_two_parts(self):
        parts = parse_parts(SIMPLE_MUSICXML)
        assert len(parts) == 2

    def test_part_ids(self):
        # music21 9.x uses the part name as the id (e.g. "Soprano", not "P1")
        parts = parse_parts(SIMPLE_MUSICXML)
        ids = [p["id"] for p in parts]
        assert "Soprano" in ids
        assert "Alto" in ids

    def test_part_names(self):
        parts = parse_parts(SIMPLE_MUSICXML)
        names = [p["name"] for p in parts]
        assert "Soprano" in names
        assert "Alto" in names

    def test_measure_count(self):
        parts = parse_parts(SIMPLE_MUSICXML)
        for p in parts:
            assert p["measure_count"] == 1

    def test_invalid_xml_raises_invalid_input(self):
        with pytest.raises(ProcessingError) as exc:
            parse_parts("not xml at all")
        assert exc.value.error_code == "INVALID_INPUT"

    def test_empty_string_raises_error(self):
        with pytest.raises(ProcessingError):
            parse_parts("")

    def test_xml_with_no_parts_raises_error(self):
        xml = '<?xml version="1.0"?><score-partwise><part-list></part-list></score-partwise>'
        with pytest.raises(ProcessingError) as exc:
            parse_parts(xml)
        assert exc.value.error_code == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# extract_midi
# ---------------------------------------------------------------------------

class TestExtractMidi:
    def test_returns_nonempty_bytes(self):
        result = extract_midi(SIMPLE_MUSICXML, None, 1.0)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_midi_header_present(self):
        result = extract_midi(SIMPLE_MUSICXML, None, 1.0)
        assert result[:4] == b"MThd"

    def test_part_filter_returns_bytes(self):
        # Use the music21-assigned id ("Soprano"), not the XML attribute ("P1")
        result = extract_midi(SIMPLE_MUSICXML, ["Soprano"], 1.0)
        assert isinstance(result, bytes)
        assert result[:4] == b"MThd"

    def test_invalid_part_id_raises_invalid_parameter(self):
        with pytest.raises(ProcessingError) as exc:
            extract_midi(SIMPLE_MUSICXML, ["P99"], 1.0)
        assert exc.value.error_code == "INVALID_PARAMETER"
        assert "P99" in str(exc.value)

    def test_invalid_xml_raises_invalid_input(self):
        with pytest.raises(ProcessingError) as exc:
            extract_midi("bad xml", None, 1.0)
        assert exc.value.error_code == "INVALID_INPUT"

    def test_tempo_factor_applied_returns_valid_midi(self):
        result = extract_midi(SIMPLE_MUSICXML, None, 0.5)
        assert result[:4] == b"MThd"

    def test_all_valid_part_ids_accepted(self):
        result = extract_midi(SIMPLE_MUSICXML, ["Soprano", "Alto"], 1.0)
        assert result[:4] == b"MThd"


# Two-part score with the tempo marking only in the top part, as most
# MusicXML exporters write it: 60 BPM at measure 1, 90 BPM at measure 2.
TEMPO_IN_TOP_PART_MUSICXML = """\
<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Soprano</part-name></score-part>
    <score-part id="P2"><part-name>Alto</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <direction placement="above">
        <direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>60</per-minute></metronome></direction-type>
        <sound tempo="60"/>
      </direction>
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
    <measure number="2">
      <direction placement="above">
        <direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>90</per-minute></metronome></direction-type>
        <sound tempo="90"/>
      </direction>
      <note><pitch><step>D</step><octave>5</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
  </part>
  <part id="P2">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <note><pitch><step>A</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
    <measure number="2">
      <note><pitch><step>B</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>"""


def _midi_tempos(midi_bytes: bytes) -> list[tuple[int, float]]:
    """Return (tick, BPM) for every SET_TEMPO event in the MIDI data, deduplicated."""
    import music21.midi

    mf = music21.midi.MidiFile()
    mf.readstr(midi_bytes)
    tempos = set()
    for track in mf.tracks:
        tick = 0
        for event in track.events:
            if event.isDeltaTime():
                tick += event.time
            elif event.type == music21.midi.MetaEvents.SET_TEMPO:
                usec_per_beat = int.from_bytes(event.data, "big")
                tempos.add((tick, round(60_000_000 / usec_per_beat, 3)))
    return sorted(tempos)


class TestExtractMidiTempo:
    """A part exported alone must keep the score tempo, even when only the top part carries it."""

    def test_lower_part_alone_keeps_score_tempo(self):
        midi = extract_midi(TEMPO_IN_TOP_PART_MUSICXML, ["Alto"], 1.0)
        assert [bpm for _, bpm in _midi_tempos(midi)] == [60.0, 90.0]

    def test_lower_part_alone_keeps_tempo_change_offset(self):
        alone = _midi_tempos(extract_midi(TEMPO_IN_TOP_PART_MUSICXML, ["Alto"], 1.0))
        both = _midi_tempos(extract_midi(TEMPO_IN_TOP_PART_MUSICXML, None, 1.0))
        assert alone == both

    def test_lower_part_alone_scales_score_tempo_by_factor(self):
        midi = extract_midi(TEMPO_IN_TOP_PART_MUSICXML, ["Alto"], 2.0)
        assert [bpm for _, bpm in _midi_tempos(midi)] == [120.0, 180.0]

    def test_all_parts_tempo_scaled_once(self):
        midi = extract_midi(TEMPO_IN_TOP_PART_MUSICXML, None, 0.5)
        assert [bpm for _, bpm in _midi_tempos(midi)] == [30.0, 45.0]


# ---------------------------------------------------------------------------
# synthesize_midi — unit tests (mocked environment)
# ---------------------------------------------------------------------------

class TestSynthesizeMidiUnit:
    MINIMAL_MIDI = b"MThd\x00\x00\x00\x06\x00\x01\x00\x01\x00\x60"

    def test_missing_soundfont_env_raises_error(self, monkeypatch):
        monkeypatch.delenv("SYNTH_SOUNDFONT_PATH", raising=False)
        with pytest.raises(ProcessingError) as exc:
            synthesize_midi(self.MINIMAL_MIDI, "/tmp/test.wav")
        assert exc.value.error_code == "PROCESSING_FAILED"
        assert "SYNTH_SOUNDFONT_PATH" in str(exc.value)

    def test_nonexistent_soundfont_file_raises_error(self, monkeypatch):
        monkeypatch.setenv("SYNTH_SOUNDFONT_PATH", "/nonexistent/soundfont.sf2")
        with pytest.raises(ProcessingError) as exc:
            synthesize_midi(self.MINIMAL_MIDI, "/tmp/test.wav")
        assert exc.value.error_code == "PROCESSING_FAILED"
        assert "not found" in str(exc.value).lower()

    def test_fluidsynth_import_failure_raises_error(self, monkeypatch, tmp_path):
        sf = tmp_path / "dummy.sf2"
        sf.write_bytes(b"RIFF")
        monkeypatch.setenv("SYNTH_SOUNDFONT_PATH", str(sf))

        with patch.dict("sys.modules", {"fluidsynth": None}):
            with pytest.raises((ProcessingError, ImportError, TypeError)):
                synthesize_midi(self.MINIMAL_MIDI, str(tmp_path / "out.wav"))


# ---------------------------------------------------------------------------
# _get_wav_duration
# ---------------------------------------------------------------------------

class TestGetWavDuration:
    def test_one_second_wav(self, tmp_path):
        wav_path = tmp_path / "test.wav"
        sample_rate = 44100
        with wave.open(str(wav_path), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(b"\x00\x00" * sample_rate)  # 1 second of silence

        duration = _get_wav_duration(str(wav_path))
        assert abs(duration - 1.0) < 0.01

    def test_two_second_wav(self, tmp_path):
        wav_path = tmp_path / "test2.wav"
        sample_rate = 44100
        with wave.open(str(wav_path), "w") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(b"\x00\x00\x00\x00" * sample_rate * 2)

        duration = _get_wav_duration(str(wav_path))
        assert abs(duration - 2.0) < 0.01


# ---------------------------------------------------------------------------
# Integration tests — require real MXL fixture files
# ---------------------------------------------------------------------------

FIXTURE_DIR = (
    Path(__file__).parent.parent.parent
    / "omr-mcp"
    / "test_samples"
    / "pdmx_satb_samples"
    / "mxl"
)


def _read_mxl(path: Path) -> str:
    """Extract MusicXML content from an MXL (ZIP) file."""
    import zipfile

    with zipfile.ZipFile(path) as zf:
        xml_names = [
            n
            for n in zf.namelist()
            if n.endswith(".xml") and "META-INF" not in n
        ]
        if not xml_names:
            raise ValueError(f"No XML content found in {path}")
        return zf.read(xml_names[0]).decode("utf-8")


@pytest.mark.integration
class TestIntegration:
    def test_fixture_dir_exists(self):
        assert FIXTURE_DIR.exists(), f"Fixture dir not found: {FIXTURE_DIR}"

    def test_parse_parts_from_real_fixture(self):
        fixtures = sorted(FIXTURE_DIR.glob("*.mxl"))
        assert fixtures, f"No MXL fixtures in {FIXTURE_DIR}"

        musicxml_str = _read_mxl(fixtures[0])
        parts = parse_parts(musicxml_str)

        assert len(parts) >= 2, "Expected at least 2 parts in SATB fixture"
        for p in parts:
            assert "id" in p
            assert "name" in p
            assert p["measure_count"] > 0

    def test_extract_midi_from_real_fixture(self):
        fixtures = sorted(FIXTURE_DIR.glob("*.mxl"))
        assert fixtures

        musicxml_str = _read_mxl(fixtures[0])
        midi_bytes = extract_midi(musicxml_str, None, 1.0)

        assert isinstance(midi_bytes, bytes)
        assert midi_bytes[:4] == b"MThd", "Expected MIDI file header"
        assert len(midi_bytes) > 100

    def test_extract_midi_single_part(self):
        fixtures = sorted(FIXTURE_DIR.glob("*.mxl"))
        assert fixtures

        musicxml_str = _read_mxl(fixtures[0])
        parts = parse_parts(musicxml_str)
        first_id = parts[0]["id"]

        midi_bytes = extract_midi(musicxml_str, [first_id], 1.0)
        assert midi_bytes[:4] == b"MThd"

    def test_extract_midi_tempo_factor(self):
        fixtures = sorted(FIXTURE_DIR.glob("*.mxl"))
        assert fixtures

        musicxml_str = _read_mxl(fixtures[0])
        midi_normal = extract_midi(musicxml_str, None, 1.0)
        midi_slow = extract_midi(musicxml_str, None, 0.5)

        # Both should be valid MIDI files
        assert midi_normal[:4] == b"MThd"
        assert midi_slow[:4] == b"MThd"

    @pytest.mark.skipif(
        not os.environ.get("SYNTH_SOUNDFONT_PATH"),
        reason="SYNTH_SOUNDFONT_PATH not set — skipping WAV synthesis tests",
    )
    def test_synthesize_midi_produces_wav(self, tmp_path):
        """Produce a real WAV from a real MXL fixture."""
        fixtures = sorted(FIXTURE_DIR.glob("*.mxl"))
        assert fixtures

        musicxml_str = _read_mxl(fixtures[0])
        midi_bytes = extract_midi(musicxml_str, None, 1.0)

        out_wav = str(tmp_path / "output.wav")
        duration = synthesize_midi(midi_bytes, out_wav)

        assert Path(out_wav).exists(), "WAV file was not created"
        assert Path(out_wav).stat().st_size > 44, "WAV file is too small (header-only)"
        assert duration > 0.0, "Duration should be positive"

    @pytest.mark.skipif(
        not os.environ.get("SYNTH_SOUNDFONT_PATH"),
        reason="SYNTH_SOUNDFONT_PATH not set — skipping WAV synthesis tests",
    )
    def test_single_part_shorter_than_double_tempo_all_parts(self, tmp_path):
        """Single part WAV should be shorter than all parts at 2× tempo."""
        fixtures = sorted(FIXTURE_DIR.glob("*.mxl"))
        assert fixtures

        musicxml_str = _read_mxl(fixtures[0])
        parts = parse_parts(musicxml_str)
        first_id = parts[0]["id"]

        midi_one = extract_midi(musicxml_str, [first_id], 1.0)
        midi_all_fast = extract_midi(musicxml_str, None, 2.0)

        wav_one = str(tmp_path / "one_part.wav")
        wav_all_fast = str(tmp_path / "all_fast.wav")

        dur_one = synthesize_midi(midi_one, wav_one)
        dur_all_fast = synthesize_midi(midi_all_fast, wav_all_fast)

        assert dur_one > 0
        assert dur_all_fast > 0
        assert dur_one > dur_all_fast, (
            f"Single part ({dur_one:.1f}s) should be longer than all-parts-2x-tempo "
            f"({dur_all_fast:.1f}s)"
        )
