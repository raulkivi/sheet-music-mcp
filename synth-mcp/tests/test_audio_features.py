"""Unit tests for the audio feature helper, on generated signals (no soundfont, no server)."""

import wave
from pathlib import Path

import numpy as np
import pytest

from .audio_features import (
    CLIP_THRESHOLD,
    SILENCE_RMS,
    WINDOW_S,
    analyze_wav,
    clipped_sample_count,
    rms_per_window,
    silence_spans,
)

RATE = 8000


def write_wav(path: Path, signal, *, rate: int = RATE, channels: int = 1) -> Path:
    """Write float samples in [-1, 1] as 16-bit PCM (interleaved when ``channels`` > 1)."""
    pcm = np.clip(np.asarray(signal, dtype=np.float64), -1.0, 1.0)
    pcm = np.round(pcm * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return path


def sine(seconds: float, amp: float = 0.5, freq: float = 440.0, rate: int = RATE, phase: float = 0.0):
    t = np.arange(int(seconds * rate)) / rate
    return amp * np.sin(2 * np.pi * freq * t + phase)


def silence(seconds: float, rate: int = RATE):
    return np.zeros(int(seconds * rate))


class TestBasicFeatures:
    def test_duration_rate_channels(self, tmp_path):
        f = analyze_wav(write_wav(tmp_path / "a.wav", sine(1.5)))
        assert f.duration_s == pytest.approx(1.5)
        assert f.sample_rate == RATE
        assert f.channels == 1

    def test_stereo_channels_and_duration(self, tmp_path):
        mono = sine(1.0)
        stereo = np.column_stack([mono, mono]).ravel()
        f = analyze_wav(write_wav(tmp_path / "s.wav", stereo, channels=2))
        assert f.channels == 2
        assert f.duration_s == pytest.approx(1.0)

    def test_peak_of_sine(self, tmp_path):
        f = analyze_wav(write_wav(tmp_path / "a.wav", sine(1.0, amp=0.5)))
        assert f.peak == pytest.approx(0.5, abs=0.01)

    def test_peak_is_absolute(self, tmp_path):
        f = analyze_wav(write_wav(tmp_path / "n.wav", -sine(0.5, amp=0.7)))
        assert f.peak == pytest.approx(0.7, abs=0.01)

    def test_rejects_unsupported_sample_width(self, tmp_path):
        path = tmp_path / "w8.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(1)
            w.setframerate(RATE)
            w.writeframes(b"\x80" * 100)
        with pytest.raises(ValueError, match="16-bit"):
            analyze_wav(path)


class TestClipping:
    def test_clean_sine_has_no_clipped_samples(self, tmp_path):
        assert analyze_wav(write_wav(tmp_path / "a.wav", sine(1.0, amp=0.5))).clipped_samples == 0

    def test_full_scale_square_is_all_clipped(self, tmp_path):
        square = np.where(sine(1.0, amp=1.0, freq=100, phase=0.1) >= 0, 1.0, -1.0)
        f = analyze_wav(write_wav(tmp_path / "sq.wav", square))
        assert f.clipped_samples == RATE  # every sample is +-1.0

    def test_overdriven_sine_clips_only_the_flat_tops(self, tmp_path):
        f = analyze_wav(write_wav(tmp_path / "o.wav", sine(1.0, amp=2.0)))
        assert 0 < f.clipped_samples < RATE

    def test_threshold_boundary(self):
        samples = np.array([0.998, 0.999, -0.999, -0.5, 1.0])
        assert CLIP_THRESHOLD == 0.999
        assert clipped_sample_count(samples) == 3


class TestRmsWindows:
    def test_window_count_covers_the_whole_file(self):
        rms = rms_per_window(sine(1.0), RATE)
        assert len(rms) == 20  # 1 s / 50 ms

    def test_partial_last_window_is_kept(self):
        assert len(rms_per_window(sine(0.12), RATE)) == 3  # 50 + 50 + 20 ms

    def test_sine_rms_is_amp_over_root_two(self):
        rms = rms_per_window(sine(1.0, amp=0.5, freq=400), RATE)  # whole cycles per window
        assert rms == pytest.approx([0.5 / np.sqrt(2)] * 20, abs=0.005)

    def test_silence_rms_is_zero(self):
        assert rms_per_window(silence(0.5), RATE) == [0.0] * 10

    def test_analyze_reports_window_length(self, tmp_path):
        f = analyze_wav(write_wav(tmp_path / "a.wav", sine(1.0)))
        assert f.window_s == WINDOW_S == 0.05
        assert len(f.rms) == 20

    def test_stereo_rms_pools_channels(self, tmp_path):
        left, right = sine(1.0, amp=0.5, freq=400), silence(1.0)
        f = analyze_wav(write_wav(tmp_path / "s.wav", np.column_stack([left, right]).ravel(), channels=2))
        assert f.rms[5] == pytest.approx(0.5 / np.sqrt(2) / np.sqrt(2), abs=0.005)


class TestSilenceSpans:
    def test_no_silence_in_a_tone(self, tmp_path):
        assert analyze_wav(write_wav(tmp_path / "a.wav", sine(1.0))).silence_spans == []

    def test_all_silence_is_one_span(self, tmp_path):
        f = analyze_wav(write_wav(tmp_path / "z.wav", silence(1.0)))
        assert f.silence_spans == [(0.0, pytest.approx(1.0))]

    def test_gap_in_the_middle(self, tmp_path):
        signal = np.concatenate([sine(0.5), silence(0.3), sine(0.5)])
        f = analyze_wav(write_wav(tmp_path / "g.wav", signal))
        assert len(f.silence_spans) == 1
        start, end = f.silence_spans[0]
        assert start == pytest.approx(0.5, abs=0.05)
        assert end == pytest.approx(0.8, abs=0.05)

    def test_leading_and_trailing_silence(self, tmp_path):
        signal = np.concatenate([silence(0.2), sine(0.5), silence(0.25)])
        spans = analyze_wav(write_wav(tmp_path / "e.wav", signal)).silence_spans
        assert len(spans) == 2
        assert spans[0][0] == 0.0
        assert spans[1][1] == pytest.approx(0.95, abs=0.001)  # clipped to the duration

    def test_min_duration_drops_short_gaps(self):
        rms = [0.5, 0.0, 0.5, 0.0, 0.0, 0.0, 0.5]
        spans = silence_spans(rms, WINDOW_S, SILENCE_RMS, min_duration_s=0.1)
        assert spans == [(pytest.approx(0.15), pytest.approx(0.30))]

    def test_threshold_is_exclusive_of_audible_windows(self):
        assert silence_spans([SILENCE_RMS, SILENCE_RMS / 2], WINDOW_S, SILENCE_RMS) == [
            (pytest.approx(0.05), pytest.approx(0.10))
        ]

    def test_quiet_noise_below_threshold_counts_as_silence(self, tmp_path):
        noise = np.random.default_rng(0).normal(0, 0.0002, RATE)
        assert len(analyze_wav(write_wav(tmp_path / "q.wav", noise)).silence_spans) == 1
