"""Unit tests for pitch_mcp.pitch_detector."""

import math
import os
import tempfile

import numpy as np
import pytest
from scipy.io.wavfile import write as wav_write

from pitch_mcp.pitch_detector import detect_pitches, get_backend

from .simulated_singer import SungNote, render, write_wav


def _make_sine_wav(freq_hz: float, duration_sec: float = 2.0, sr: int = 22050) -> str:
    """Create a temporary WAV file with a sine wave at the given frequency.

    Returns the path to the temp file (caller must delete it).
    """
    t = np.linspace(0, duration_sec, int(sr * duration_sec))
    audio = (0.5 * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    wav_write(path, sr, (audio * 32767).astype(np.int16))
    return path


class TestGetBackend:
    def test_default_is_librosa(self):
        old = os.environ.pop("PITCH_BACKEND", None)
        try:
            assert get_backend() == "librosa"
        finally:
            if old is not None:
                os.environ["PITCH_BACKEND"] = old

    def test_env_override(self):
        old = os.environ.get("PITCH_BACKEND")
        os.environ["PITCH_BACKEND"] = "crepe"
        try:
            assert get_backend() == "crepe"
        finally:
            if old is None:
                del os.environ["PITCH_BACKEND"]
            else:
                os.environ["PITCH_BACKEND"] = old


class TestDetectPitches:
    def test_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError):
            detect_pitches("/nonexistent/audio.wav")

    def test_a4_sine_detected(self):
        path = _make_sine_wav(440.0)
        try:
            pitches = detect_pitches(path)
            assert len(pitches) > 0, "Should detect voiced frames in a sine wave"
            freqs = [f for t, f, c in pitches]
            avg = sum(freqs) / len(freqs)
            # pYIN should be very accurate on a clean sine wave
            assert abs(avg - 440.0) < 5.0, f"Expected ~440 Hz, got {avg:.1f} Hz"
        finally:
            os.unlink(path)

    def test_result_format(self):
        path = _make_sine_wav(440.0)
        try:
            pitches = detect_pitches(path)
            for item in pitches:
                assert len(item) == 3
                t, f, c = item
                assert t >= 0
                assert f > 0
                assert 0 <= c <= 1
        finally:
            os.unlink(path)

    def test_g4_sine_detected(self):
        # G4 = 392 Hz
        g4_hz = 440.0 * (2 ** (-5 / 12))
        path = _make_sine_wav(g4_hz)
        try:
            pitches = detect_pitches(path)
            assert len(pitches) > 0
            freqs = [f for t, f, c in pitches]
            avg = sum(freqs) / len(freqs)
            assert abs(avg - g4_hz) < 10.0, f"Expected ~{g4_hz:.1f} Hz, got {avg:.1f} Hz"
        finally:
            os.unlink(path)

    def test_times_are_increasing(self):
        path = _make_sine_wav(440.0)
        try:
            pitches = detect_pitches(path)
            times = [t for t, f, c in pitches]
            assert times == sorted(times)
        finally:
            os.unlink(path)

    @pytest.mark.parametrize("sr", [22050, 44100])
    @pytest.mark.parametrize("slipped_hz", [698.46, 174.61], ids=["F5", "F3"])
    def test_an_octave_slip_between_neighbours_is_read_at_its_own_octave(self, sr, slipped_hz):
        # G4, F4 sung an octave off, E4, with no glide between them. pYIN's HMM limits the pitch
        # step per frame, so at 22.05 kHz it read F5 (between two leaps of 10+ semitones) as its
        # subharmonic F4 for the whole note, although the audio has no energy at F4.
        notes = [SungNote(392.0, 0.0, 0.667), SungNote(slipped_hz, 0.667, 1.333), SungNote(329.63, 1.333, 2.0)]
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        write_wav(path, render(notes, sample_rate=sr), sample_rate=sr)
        try:
            held = [f for t, f, c in detect_pitches(path) if 0.767 <= t <= 1.233]
            got = float(np.median(held))
            assert abs(1200 * math.log2(got / slipped_hz)) < 30, f"expected {slipped_hz} Hz, got {got:.1f} Hz"
        finally:
            os.unlink(path)

    def test_a_tone_with_a_strong_fundamental_is_not_doubled(self):
        # The subharmonic check must not move a real note up: F4 with its usual partials stays F4.
        notes = [SungNote(349.23, 0.0, 1.0)]
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        write_wav(path, render(notes), sample_rate=22050)
        try:
            freqs = [f for t, f, c in detect_pitches(path) if 0.1 <= t <= 0.9]
            assert all(abs(1200 * math.log2(f / 349.23)) < 30 for f in freqs)
        finally:
            os.unlink(path)

    def test_stereo_wav_accepted(self):
        sr = 22050
        t = np.linspace(0, 1.0, sr)
        mono = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        stereo = np.stack([mono, mono], axis=1)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        wav_write(path, sr, (stereo * 32767).astype(np.int16))
        try:
            pitches = detect_pitches(path)
            assert len(pitches) > 0
        finally:
            os.unlink(path)
