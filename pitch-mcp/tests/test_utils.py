"""Unit tests for pitch_mcp.utils."""

import math

import pytest

from pitch_mcp.utils import (
    classify_accuracy,
    extract_nominal_tempo_bpm,
    extract_note_sequence,
    hz_to_note,
    note_name_to_hz,
    validate_audio_path,
    validate_musicxml,
    validate_session_id,
)


class TestHzToNote:
    def test_a4_exactly(self):
        note, cents = hz_to_note(440.0)
        assert note == "A4"
        assert cents == 0

    def test_a4_sharp(self):
        # 440 * 2^(12/1200) ≈ 442.55 Hz = 12 cents sharp of A4
        hz = 440.0 * (2 ** (12 / 1200))
        note, cents = hz_to_note(hz)
        assert note == "A4"
        assert cents == 12

    def test_a4_flat(self):
        hz = 440.0 * (2 ** (-12 / 1200))
        note, cents = hz_to_note(hz)
        assert note == "A4"
        assert cents == -12

    def test_middle_c(self):
        # C4 = 261.63 Hz
        note, cents = hz_to_note(261.63)
        assert note == "C4"
        assert abs(cents) <= 2  # rounding tolerance

    def test_g4(self):
        # G4 = MIDI 67, A4 = MIDI 69 → G4 is 2 semitones below A4
        hz = 440.0 * (2 ** (-2 / 12))
        note, cents = hz_to_note(hz)
        assert note == "G4"
        assert abs(cents) <= 1

    def test_invalid_hz_raises(self):
        with pytest.raises(ValueError):
            hz_to_note(0.0)
        with pytest.raises(ValueError):
            hz_to_note(-100.0)

    def test_high_soprano(self):
        # A5 = 880 Hz
        note, cents = hz_to_note(880.0)
        assert note == "A5"
        assert cents == 0

    def test_low_bass(self):
        # E2 = MIDI 40, A4 = MIDI 69 → E2 is 29 semitones below A4
        hz = 440.0 * (2 ** (-29 / 12))
        note, cents = hz_to_note(hz)
        assert note == "E2"
        assert abs(cents) <= 1


class TestNoteNameToHz:
    def test_a4(self):
        assert abs(note_name_to_hz("A4") - 440.0) < 0.1

    def test_c4(self):
        assert abs(note_name_to_hz("C4") - 261.63) < 0.5

    def test_round_trip(self):
        for note_str in ["C4", "G4", "A5", "E3", "F#4"]:
            hz = note_name_to_hz(note_str)
            name, cents = hz_to_note(hz)
            assert abs(cents) <= 1, f"{note_str}: {cents} cents off"


class TestClassifyAccuracy:
    def test_on_pitch_zero(self):
        assert classify_accuracy(0) == "on_pitch"

    def test_on_pitch_at_threshold(self):
        assert classify_accuracy(25) == "on_pitch"
        assert classify_accuracy(-25) == "on_pitch"

    def test_sharp(self):
        assert classify_accuracy(26) == "sharp"
        assert classify_accuracy(50) == "sharp"

    def test_flat(self):
        assert classify_accuracy(-26) == "flat"
        assert classify_accuracy(-100) == "flat"

    def test_custom_threshold(self):
        assert classify_accuracy(10, threshold=5) == "sharp"
        assert classify_accuracy(5, threshold=5) == "on_pitch"


class TestValidateAudioPath:
    def test_nonexistent_file(self):
        ok, err = validate_audio_path("/nonexistent/path/audio.wav")
        assert ok is False
        assert "not found" in err.lower()

    def test_empty_path(self):
        ok, err = validate_audio_path("")
        assert ok is False

    def test_unsupported_format(self, tmp_path):
        f = tmp_path / "audio.mp3"
        f.touch()
        ok, err = validate_audio_path(str(f))
        assert ok is False
        assert "unsupported" in err.lower()

    def test_valid_wav(self, tmp_path):
        f = tmp_path / "audio.wav"
        f.touch()
        ok, err = validate_audio_path(str(f))
        assert ok is True


class TestValidateMusicxml:
    def test_valid_score_partwise(self):
        ok, err = validate_musicxml("<score-partwise></score-partwise>")
        assert ok is True

    def test_empty_string(self):
        ok, err = validate_musicxml("")
        assert ok is False

    def test_not_musicxml(self):
        ok, err = validate_musicxml("<html></html>")
        assert ok is False


class TestValidateSessionId:
    def test_valid_id(self):
        ok, err = validate_session_id("abc-123")
        assert ok is True

    def test_empty(self):
        ok, err = validate_session_id("")
        assert ok is False

    def test_whitespace(self):
        ok, err = validate_session_id("   ")
        assert ok is False


MINIMAL_MUSICXML = """\
<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <work><work-title>Test</work-title></work>
  <part-list>
    <score-part id="P1"><part-name>Soprano</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>4</divisions>
        <key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <direction placement="above">
        <direction-type>
          <metronome><beat-unit>quarter</beat-unit><per-minute>120</per-minute></metronome>
        </direction-type>
      </direction>
      <note>
        <pitch><step>C</step><octave>4</octave></pitch>
        <duration>4</duration><type>quarter</type>
      </note>
      <note>
        <pitch><step>E</step><octave>4</octave></pitch>
        <duration>4</duration><type>quarter</type>
      </note>
      <note>
        <pitch><step>G</step><octave>4</octave></pitch>
        <duration>4</duration><type>quarter</type>
      </note>
      <note><rest/><duration>4</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>
"""


class TestExtractNoteSequence:
    def test_extracts_notes(self):
        notes = extract_note_sequence(MINIMAL_MUSICXML, "Soprano")
        assert len(notes) == 3  # 3 pitched notes, 1 rest skipped

    def test_note_structure(self):
        notes = extract_note_sequence(MINIMAL_MUSICXML, "Soprano")
        note = notes[0]
        assert "note_name" in note
        assert "freq_hz" in note
        assert "start_sec" in note
        assert "end_sec" in note
        assert "measure" in note
        assert "beat" in note
        assert "midi" in note

    def test_first_note_is_c4(self):
        notes = extract_note_sequence(MINIMAL_MUSICXML, "Soprano")
        assert notes[0]["note_name"] == "C4"
        assert abs(notes[0]["freq_hz"] - 261.63) < 1.0

    def test_timing_is_positive(self):
        notes = extract_note_sequence(MINIMAL_MUSICXML, "Soprano")
        for note in notes:
            assert note["start_sec"] >= 0
            assert note["end_sec"] > note["start_sec"]

    def test_invalid_part_id_raises(self):
        from sheet_music_mcp_core.parts import PartSelectionError

        with pytest.raises(PartSelectionError, match="not found") as excinfo:
            extract_note_sequence(MINIMAL_MUSICXML, "Bass")
        assert excinfo.value.error_code == "INVALID_PARAMETER"
        assert excinfo.value.choices


class TestExtractNominalTempoBpm:
    def test_reads_metronome_mark(self):
        assert extract_nominal_tempo_bpm(MINIMAL_MUSICXML) == pytest.approx(120.0)

    def test_defaults_to_120_when_no_mark(self):
        no_tempo_xml = MINIMAL_MUSICXML.replace(
            "<direction placement=\"above\">\n"
            "        <direction-type>\n"
            "          <metronome><beat-unit>quarter</beat-unit><per-minute>120</per-minute></metronome>\n"
            "        </direction-type>\n"
            "      </direction>\n",
            "",
        )
        assert extract_nominal_tempo_bpm(no_tempo_xml) == pytest.approx(120.0)
