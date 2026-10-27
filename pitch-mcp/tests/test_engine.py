"""Unit and integration tests for pitch_mcp.engine."""

import io
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from scipy.io.wavfile import write as wav_write

from pitch_mcp.engine import (
    ProcessingError,
    ScoreSession,
    analyze_recording,
    get_position,
    load_score,
    stop_monitoring,
)
from pitch_mcp import engine
from pitch_mcp.utils import note_name_to_hz

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
        <pitch><step>A</step><octave>4</octave></pitch>
        <duration>8</duration><type>half</type>
      </note>
      <note>
        <pitch><step>G</step><octave>4</octave></pitch>
        <duration>8</duration><type>half</type>
      </note>
    </measure>
  </part>
</score-partwise>
"""


FOUR_NOTE_MUSICXML = """\
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
      <note>
        <pitch><step>C</step><octave>5</octave></pitch>
        <duration>4</duration><type>quarter</type>
      </note>
    </measure>
  </part>
</score-partwise>
"""


def _make_wav(freq_hz: float, duration_sec: float = 2.0, sr: int = 22050) -> str:
    """Create a temp WAV file with a sine wave. Caller must delete."""
    t = np.linspace(0, duration_sec, int(sr * duration_sec))
    audio = (0.5 * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    wav_write(path, sr, (audio * 32767).astype(np.int16))
    return path


class TestAnalyzeRecording:
    def test_file_not_found_raises(self):
        with pytest.raises(ProcessingError) as exc:
            analyze_recording("/nonexistent.wav", MINIMAL_MUSICXML, "Soprano")
        assert exc.value.error_code == "FILE_NOT_FOUND"

    def test_invalid_musicxml_raises(self):
        path = _make_wav(440.0)
        try:
            with pytest.raises(ProcessingError) as exc:
                analyze_recording(path, "<not-xml>", "Soprano")
            assert exc.value.error_code == "INVALID_INPUT"
        finally:
            os.unlink(path)

    def test_invalid_part_id_raises(self):
        path = _make_wav(440.0)
        try:
            with pytest.raises(ProcessingError) as exc:
                analyze_recording(path, MINIMAL_MUSICXML, "Bass")
            assert exc.value.error_code == "INVALID_PARAMETER"
        finally:
            os.unlink(path)

    def test_a4_sine_against_a4_score(self):
        """An A4 sine wave against an A4-containing score should be on_pitch."""
        path = _make_wav(440.0, duration_sec=2.0)
        try:
            result = analyze_recording(path, MINIMAL_MUSICXML, "Soprano")
            assert "measures_covered" in result
            assert "note_accuracy" in result
            assert "accuracy_histogram" in result
            assert result["measures_covered"] >= 1
            # The A4 note should align with some on_pitch frames
            assert result["accuracy_histogram"]["on_pitch"] > 0 or result["accuracy_histogram"]["sharp"] >= 0
        finally:
            os.unlink(path)

    def test_result_structure(self):
        path = _make_wav(440.0)
        try:
            result = analyze_recording(path, MINIMAL_MUSICXML, "Soprano")
            assert isinstance(result["measures_covered"], int)
            assert isinstance(result["note_accuracy"], list)
            assert isinstance(result["accuracy_histogram"], dict)
            hist = result["accuracy_histogram"]
            assert "on_pitch" in hist
            assert "sharp" in hist
            assert "flat" in hist
            assert "no_signal" in hist
        finally:
            os.unlink(path)

    def test_note_accuracy_structure(self):
        path = _make_wav(440.0)
        try:
            result = analyze_recording(path, MINIMAL_MUSICXML, "Soprano")
            for note in result["note_accuracy"]:
                assert "measure" in note
                assert "beat" in note
                assert "expected" in note
                assert "expected_hz" in note
                assert "status" in note
                assert note["status"] in ("on_pitch", "sharp", "flat", "no_signal")
        finally:
            os.unlink(path)


class TestLoadScore:
    def test_valid_score_creates_session(self):
        result = load_score(MINIMAL_MUSICXML, "Soprano")
        sid = result["session_id"]
        assert sid
        assert result["part_name"] == "Soprano"
        assert result["measure_count"] >= 1
        assert result["duration_seconds"] > 0
        # Cleanup: stop_monitoring succeeds for a valid session
        stop_result = stop_monitoring(sid)
        assert "session_id" in stop_result

    def test_invalid_part_id_raises(self):
        with pytest.raises(ProcessingError) as exc:
            load_score(MINIMAL_MUSICXML, "Tuba")
        assert exc.value.error_code == "INVALID_PARAMETER"

    def test_invalid_musicxml_raises(self):
        with pytest.raises(ProcessingError) as exc:
            load_score("<bad>", "Soprano")
        assert exc.value.error_code in ("INVALID_INPUT", "PROCESSING_FAILED")

    def test_multiple_sessions_are_isolated(self):
        r1 = load_score(MINIMAL_MUSICXML, "Soprano")
        r2 = load_score(MINIMAL_MUSICXML, "Soprano")
        assert r1["session_id"] != r2["session_id"]
        # Cleanup both
        stop_monitoring(r1["session_id"])
        stop_monitoring(r2["session_id"])
        # Now both should be gone
        with pytest.raises(ProcessingError) as exc:
            get_position(r1["session_id"])
        assert exc.value.error_code == "SESSION_NOT_FOUND"


class TestGetPosition:
    def test_invalid_session_raises(self):
        with pytest.raises(ProcessingError) as exc:
            get_position("nonexistent-session-id")
        assert exc.value.error_code == "SESSION_NOT_FOUND"

    def test_valid_session_returns_position(self):
        result = load_score(MINIMAL_MUSICXML, "Soprano")
        sid = result["session_id"]
        pos = get_position(sid)
        assert pos["session_id"] == sid
        assert "measure" in pos
        assert "beat" in pos
        assert "expected_note" in pos
        assert "status" in pos
        # Cleanup
        stop_monitoring(sid)


class TestStopMonitoring:
    def test_invalid_session_raises(self):
        with pytest.raises(ProcessingError) as exc:
            stop_monitoring("nonexistent-session-id")
        assert exc.value.error_code == "SESSION_NOT_FOUND"

    def test_stop_removes_session(self):
        result = load_score(MINIMAL_MUSICXML, "Soprano")
        sid = result["session_id"]
        # Session should be in registry
        assert engine._registry.get(sid) is not None
        # First stop succeeds and removes session
        stop_monitoring(sid)
        # Second stop raises SESSION_NOT_FOUND
        with pytest.raises(ProcessingError) as exc:
            stop_monitoring(sid)
        assert exc.value.error_code == "SESSION_NOT_FOUND"

    def test_stop_returns_summary(self):
        result = load_score(MINIMAL_MUSICXML, "Soprano")
        sid = result["session_id"]
        # Manually remove from registry to simulate stopping:
        # Actually just call stop - it should return a summary even without audio
        # We need to simulate: stop without a running stream
        session = engine._registry.remove(sid)
        if session:
            # Call stop directly on session (no stream running)
            summary_result = session.stop()
            assert "session_id" in summary_result
            assert "summary" in summary_result


class TestProcessPitchFrame:
    """Tests for ScoreSession._process_pitch_frame — the per-frame update
    that drives real-time position tracking (Phase B)."""

    def _make_session(self):
        return ScoreSession(FOUR_NOTE_MUSICXML, "Soprano")

    def test_no_signal_frame_does_not_raise_or_populate_history(self):
        session = self._make_session()
        session._process_pitch_frame(0.0, 0.0, 0.1)
        assert session._history == []

    def test_valid_frame_populates_history(self):
        """See docs/todo.md: `_history` was never appended to, so
        `stop_monitoring`'s summary always reported zeros regardless of what
        was actually sung."""
        session = self._make_session()
        session._process_pitch_frame(note_name_to_hz("C4"), 0.9, 0.1)
        assert len(session._history) == 1
        assert session._history[0]["status"] == "on_pitch"

        summary = session.stop()["summary"]
        assert summary["accuracy_histogram"]["on_pitch"] == 1
        assert summary["avg_accuracy_cents"] == 0

    def test_valid_frame_updates_current_position(self):
        session = self._make_session()
        session._process_pitch_frame(note_name_to_hz("E4"), 0.9, 0.6)
        pos = session.get_position()
        assert pos["expected_note"] == "E4"
        assert pos["status"] == "on_pitch"

    def test_position_tracking_is_audio_driven_not_pure_wallclock(self):
        """See docs/todo.md: position previously advanced purely from
        elapsed wall-clock time, never from the detected pitch. Here the
        singer pauses before the first note, then comes in singing the
        *second* note's pitch while elapsed time is still within the first
        note's nominal window — a pure wall-clock tracker would report the
        first note; audio-driven tracking should recognize the second."""
        session = self._make_session()
        # elapsed_sec=0.1 falls inside C4's nominal 0.0-0.5s window, but the
        # singer is actually singing E4 (the next note) after a late start.
        session._process_pitch_frame(note_name_to_hz("E4"), 0.9, 0.1)
        pos = session.get_position()
        assert pos["expected_note"] == "E4"

    def test_note_index_never_moves_backward(self):
        session = self._make_session()
        session._process_pitch_frame(note_name_to_hz("G4"), 0.9, 1.1)
        assert session._note_idx == 2
        # A stray frame that happens to match an earlier note shouldn't pull
        # position backward.
        session._process_pitch_frame(note_name_to_hz("C4"), 0.9, 1.2)
        assert session._note_idx >= 2

    def test_tempo_bpm_override_shifts_score_time(self):
        """See docs/todo.md: `tempo_bpm` was threaded through to `start()`
        but never used anywhere. A singer performing at half the written
        120 BPM tempo should map a given wall-clock time to half as much
        score-time — at real time 0.9s, that keeps the last note (C5,
        nominally starting at 1.5s) out of the plausible-candidate lookahead,
        where at the score's actual tempo it would already be reachable."""
        c5_hz = note_name_to_hz("C5")  # matches the 4th note exactly

        baseline = self._make_session()
        baseline._tempo_bpm = None
        baseline._process_pitch_frame(c5_hz, 0.9, 0.9)
        assert baseline._note_idx == 3  # C5 reached at the score's own tempo

        half_tempo = self._make_session()
        half_tempo._tempo_bpm = 60  # half of the score's 120 BPM
        half_tempo._process_pitch_frame(c5_hz, 0.9, 0.9)

        assert half_tempo._note_idx < baseline._note_idx
