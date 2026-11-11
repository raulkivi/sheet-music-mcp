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
    onsets_near,
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


def struck(at: list[float], seconds: float, freqs: list[float], rate: int = RATE):
    """Decaying tones (like piano keys) starting at ``at``; each rings on under the next."""
    out = np.zeros(int(seconds * rate))
    t = np.arange(len(out)) / rate
    for start, freq in zip(at, freqs):
        on = t >= start
        out[on] += 0.3 * np.exp(-(t[on] - start) * 3) * np.sin(2 * np.pi * freq * (t[on] - start))
    return out


class TestOnsetsNear:
    STARTS = [0.3, 0.9, 1.4]

    def test_finds_each_struck_note_within_5_ms(self):
        signal = struck(self.STARTS, 2.0, [440.0, 494.0, 523.0]).reshape(-1, 1)
        found = onsets_near(signal, RATE, self.STARTS)
        assert np.allclose(found, self.STARTS, atol=0.005), found

    def test_finds_an_onset_off_the_expected_time(self):
        signal = struck([0.33], 1.0, [440.0]).reshape(-1, 1)
        [found] = onsets_near(signal, RATE, [0.3], search_s=0.1)
        assert found == pytest.approx(0.33, abs=0.005)

    def test_an_onset_beyond_the_search_window_is_not_found(self):
        signal = struck([0.6], 1.0, [440.0]).reshape(-1, 1)
        assert onsets_near(signal, RATE, [0.3], search_s=0.1) == [None]

    def test_stereo_pools_channels(self):
        mono = struck(self.STARTS, 2.0, [440.0, 494.0, 523.0])
        found = onsets_near(np.stack([mono, mono], axis=1), RATE, self.STARTS)
        assert np.allclose(found, self.STARTS, atol=0.005)

    def test_window_starts_stay_on_the_samples_when_the_window_is_not_whole(self):
        # At 44.1 kHz a 5 ms window is 220.5 samples and is cut to 220: window starts counted
        # in nominal 5 ms steps run ahead of the audio by 1/441 (75 ms at 33 s).
        rate = 44100
        starts = [1.0, 16.0, 31.5]
        signal = struck(starts, 33.0, [440.0, 494.0, 523.0], rate=rate).reshape(-1, 1)
        found = onsets_near(signal, rate, starts)
        assert np.allclose(found, starts, atol=0.005), found


def test_silence_spans_stay_on_the_samples_when_the_window_is_not_whole(tmp_path):
    # At 22.05 kHz a 50 ms window is 1102.5 samples, cut to 1102: 0.1 s off after two minutes.
    rate = 22050
    signal = np.concatenate([sine(120.0, rate=rate), silence(1.0, rate=rate), sine(1.0, rate=rate)])
    f = analyze_wav(write_wav(tmp_path / "long.wav", signal, rate=rate))
    [(start, end)] = f.silence_spans
    assert start == pytest.approx(120.0, abs=0.05)
    assert end == pytest.approx(121.0, abs=0.05)
