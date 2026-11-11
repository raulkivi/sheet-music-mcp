"""Read a WAV file and measure what it contains: length, level, clipping and silence.

Pure analysis: standard-library ``wave`` plus numpy. It knows nothing about MCP, the synth engine
or soundfonts, so it can be unit-tested on generated signals.

Placement: this is a test helper for now, so it lives under ``tests/``. When pitch-mcp needs the
same measurements it moves to ``sheet-music-mcp-core`` (MCP-free, so engines may import it).

Conventions:
- Samples are normalised to floats in [-1.0, 1.0) (16-bit PCM divided by 32768).
- A sample is *clipped* when ``abs(x) >= CLIP_THRESHOLD`` (0.999, about 32735 in int16).
- RMS is measured per ``WINDOW_S`` (50 ms) window over all channels pooled; the last window may be
  shorter than the others and is kept. A window is a whole number of samples, so its real length
  (``window_seconds``) can differ from the nominal one; times are counted in real lengths.
- A window is *silent* when its RMS is below ``SILENCE_RMS`` (0.001, about -60 dBFS). A silence span
  is a run of silent windows, as ``(start_s, end_s)``, with the end clipped to the file duration.
- An *onset* is where the RMS envelope (``ONSET_WINDOW_S`` windows) crosses half its rise near an
  expected time (``onsets_near``): a struck note's attack, even while earlier notes still ring.
"""

import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

CLIP_THRESHOLD = 0.999
WINDOW_S = 0.05
SILENCE_RMS = 0.001
MIN_SILENCE_S = 0.1  # analyze_wav ignores gaps shorter than this (note gaps, not dropouts)
ONSET_WINDOW_S = 0.005
ONSET_SEARCH_S = 0.1


@dataclass(frozen=True)
class AudioFeatures:
    duration_s: float
    sample_rate: int
    channels: int
    peak: float
    clipped_samples: int
    window_s: float
    rms: list[float] = field(repr=False)
    silence_spans: list[tuple[float, float]] = field(default_factory=list)


def read_wav(path: str | Path) -> tuple[np.ndarray, int, int]:
    """Return ``(samples, sample_rate, channels)``; samples are float64, shape ``(frames, channels)``."""
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"Only 16-bit PCM WAV is supported, got {8 * w.getsampwidth()}-bit")
        channels, rate = w.getnchannels(), w.getframerate()
        raw = w.readframes(w.getnframes())
    pcm = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    return pcm.reshape(-1, channels), rate, channels


def peak_amplitude(samples: np.ndarray) -> float:
    return float(np.max(np.abs(samples))) if samples.size else 0.0


def clipped_sample_count(samples: np.ndarray) -> int:
    return int(np.count_nonzero(np.abs(samples) >= CLIP_THRESHOLD))


def window_frames(window_s: float, sample_rate: int) -> int:
    """Samples per RMS window: ``window_s`` rounded to whole samples (220 for 5 ms at 44.1 kHz)."""
    return max(1, round(window_s * sample_rate))


def window_seconds(window_s: float, sample_rate: int) -> float:
    """The real length of an RMS window. Count window starts with this, never with ``window_s``:
    at 44.1 kHz a 5 ms window is 220 samples, and nominal 5 ms steps run 1/441 ahead of the audio.
    """
    return window_frames(window_s, sample_rate) / sample_rate


def rms_per_window(samples: np.ndarray, sample_rate: int, window_s: float = WINDOW_S) -> list[float]:
    """RMS of each consecutive window (all channels pooled); a short final window is kept."""
    frames = samples.reshape(len(samples), -1) if samples.ndim > 1 else samples.reshape(-1, 1)
    size = window_frames(window_s, sample_rate)
    return [
        float(np.sqrt(np.mean(frames[i : i + size] ** 2)))
        for i in range(0, len(frames), size)
    ]


def silence_spans(
    rms: list[float],
    window_s: float,
    threshold: float = SILENCE_RMS,
    min_duration_s: float = 0.0,
    duration_s: float | None = None,
) -> list[tuple[float, float]]:
    """Runs of windows with RMS below ``threshold`` as ``(start_s, end_s)``, at least ``min_duration_s`` long."""
    spans: list[tuple[float, float]] = []
    start: int | None = None
    for i, value in enumerate([*rms, float("inf")]):  # sentinel closes a trailing run
        if value < threshold:
            if start is None:
                start = i
        elif start is not None:
            begin, end = start * window_s, i * window_s
            if duration_s is not None:
                end = min(end, duration_s)
            if end - begin >= min_duration_s - 1e-9:
                spans.append((begin, end))
            start = None
    return spans


def onsets_near(
    samples: np.ndarray,
    sample_rate: int,
    expected_s: list[float],
    *,
    search_s: float = ONSET_SEARCH_S,
    window_s: float = ONSET_WINDOW_S,
) -> list[float | None]:
    """For each expected time, where the RMS envelope crosses half its rise (None: no rise).

    The rise runs from the quietest window in the ``search_s`` before the expected time to the
    loudest in the ``search_s`` after it; the onset is the start of the first window, from
    ``search_s`` before, at or above the halfway level. Robust to the envelope's ripple, unlike the
    steepest rise.
    """
    rms = np.asarray(rms_per_window(samples, sample_rate, window_s))
    starts = np.arange(len(rms)) * window_seconds(window_s, sample_rate)
    found: list[float | None] = []
    for expected in expected_s:
        before = rms[(starts >= expected - search_s - 1e-9) & (starts <= expected + 1e-9)]
        after_mask = (starts >= expected - 1e-9) & (starts <= expected + search_s + 1e-9)
        after = rms[after_mask]
        if not after.size:
            found.append(None)
            continue
        base = float(before.min()) if before.size else 0.0
        peak = float(after.max())
        if peak - base <= SILENCE_RMS:
            found.append(None)
            continue
        level = base + (peak - base) / 2
        span = np.nonzero((starts >= expected - search_s - 1e-9) & (starts <= expected + search_s + 1e-9))[0]
        first = next(i for i in span if rms[i] >= level)
        found.append(float(starts[first]))
    return found


def analyze_wav(
    path: str | Path,
    *,
    window_s: float = WINDOW_S,
    silence_rms: float = SILENCE_RMS,
    min_silence_s: float = MIN_SILENCE_S,
) -> AudioFeatures:
    samples, rate, channels = read_wav(path)
    duration = len(samples) / rate
    rms = rms_per_window(samples, rate, window_s)
    window_s = window_seconds(window_s, rate)
    return AudioFeatures(
        duration_s=duration,
        sample_rate=rate,
        channels=channels,
        peak=peak_amplitude(samples),
        clipped_samples=clipped_sample_count(samples),
        window_s=window_s,
        rms=rms,
        silence_spans=silence_spans(rms, window_s, silence_rms, min_silence_s, duration),
    )
