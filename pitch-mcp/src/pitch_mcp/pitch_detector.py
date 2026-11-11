"""
Pitch detector for pitch-mcp.

Primary backend: librosa (pYIN algorithm) — pure Python, no system dependencies,
excellent accuracy for monophonic singing voice.

Optional backend: crepe (CNN-based, higher accuracy for noisy environments, requires
TensorFlow — install manually and set PITCH_BACKEND=crepe).

Backend is selected by the PITCH_BACKEND environment variable (default: librosa).
"""

import logging
import os
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Confidence threshold for crepe (pYIN uses voiced/unvoiced flags instead)
_CREPE_CONFIDENCE_THRESHOLD = 0.5


def get_backend() -> str:
    """Return the active pitch detection backend name."""
    return os.environ.get("PITCH_BACKEND", "librosa").lower()


def detect_pitches(audio_path: str) -> list[tuple[float, float, float]]:
    """Detect pitches from a WAV file.

    Args:
        audio_path: Path to a WAV file (any sample rate; stereo is mixed to mono).

    Returns:
        List of (time_sec, freq_hz, confidence) tuples for voiced frames only.
        Only frames with a detected pitch > 0 Hz are returned.

    Raises:
        RuntimeError: if the backend is unavailable or the file cannot be read.
        FileNotFoundError: if audio_path does not exist.
    """
    if not Path(audio_path).exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path!r}")

    backend = get_backend()

    if backend == "crepe":
        return _detect_crepe(audio_path)
    else:
        return _detect_librosa(audio_path)


def _detect_librosa(audio_path: str) -> list[tuple[float, float, float]]:
    """Detect pitches using librosa's pYIN algorithm.

    pYIN is a probabilistic extension of YIN, well-suited for monophonic singing voice.
    It returns voiced/unvoiced flags per frame, avoiding false pitch detections.
    """
    try:
        import librosa
    except ImportError as e:
        raise RuntimeError(
            f"librosa is not available: {e}. Install it with: pip install librosa"
        )

    try:
        y, sr = librosa.load(audio_path, sr=None, mono=True)
    except Exception as e:
        raise RuntimeError(f"Failed to load audio file {audio_path!r}: {e}")

    if len(y) == 0:
        return []

    hop_length = 512
    frame_length = 2048
    fmin = librosa.note_to_hz("C2")   # ~65 Hz — Bass lowest
    fmax = librosa.note_to_hz("C7")   # ~2093 Hz — Soprano highest

    try:
        f0, voiced_flag, voiced_prob = librosa.pyin(
            y,
            fmin=fmin,
            fmax=fmax,
            sr=sr,
            frame_length=frame_length,
            hop_length=hop_length,
        )
    except Exception as e:
        raise RuntimeError(f"pYIN pitch detection failed: {e}")

    f0 = undo_subharmonics(y, sr, f0, hop_length, frame_length, fmax)
    times = librosa.times_like(f0, sr=sr, hop_length=hop_length)

    results: list[tuple[float, float, float]] = []
    for t, freq, voiced, prob in zip(times, f0, voiced_flag, voiced_prob):
        if voiced and not np.isnan(freq) and freq > 0:
            results.append((round(float(t), 4), round(float(freq), 2), round(float(prob), 4)))

    return results


# A frame whose half-period difference is below this is periodic at twice the reported pitch:
# its odd partials (the fundamental among them) carry under about 5% of the energy. Same order as
# YIN's own first-dip threshold (0.1).
SUBHARMONIC_THRESHOLD = 0.1


def undo_subharmonics(
    y: np.ndarray, sr: int, f0: np.ndarray, hop_length: int, frame_length: int, fmax: float
) -> np.ndarray:
    """``f0`` with every frame pYIN read an octave low moved up to its real pitch.

    pYIN's HMM limits the pitch step between frames. A note an octave or more away from both
    neighbours (an octave slip sung without a glide) can then be tracked at its subharmonic,
    where the audio has no energy. YIN's first-dip rule would take the half period; this applies
    it after the fact. Frames are centred like librosa's (``center=True``, zero padding).
    """
    padded = np.pad(y, frame_length // 2)
    out = f0.copy()
    for i, freq in enumerate(f0):
        if np.isnan(freq) or freq <= 0 or 2 * freq > fmax:
            continue
        frame = padded[i * hop_length : i * hop_length + frame_length]
        if _periodicity_gap(frame, sr / (2 * freq)) < SUBHARMONIC_THRESHOLD:
            out[i] = 2 * freq
    return out


def _periodicity_gap(frame: np.ndarray, lag: float) -> float:
    """Normalised difference between ``frame`` and itself ``lag`` samples later: 0 when periodic
    at that lag, about 1 for unrelated signal. A fractional lag interpolates its two neighbours."""
    low = int(np.floor(lag))
    weight = lag - low
    return (1 - weight) * _difference(frame, low) + weight * _difference(frame, low + 1)


def _difference(frame: np.ndarray, lag: int) -> float:
    if lag <= 0 or lag >= len(frame):
        return float("inf")
    a, b = frame[:-lag], frame[lag:]
    energy = float(np.sum(a * a + b * b))
    return float(np.sum((a - b) ** 2)) / energy if energy > 0 else float("inf")


def _detect_crepe(audio_path: str) -> list[tuple[float, float, float]]:
    """Detect pitches using the CREPE CNN model (requires TensorFlow)."""
    try:
        import crepe
        from scipy.io import wavfile
    except ImportError as e:
        raise RuntimeError(
            f"crepe or scipy not available: {e}. "
            "Install with: pip install crepe tensorflow"
        )

    sr, audio = wavfile.read(audio_path)

    if audio.dtype == np.int16:
        audio = audio.astype(np.float32) / 32768.0
    elif audio.dtype == np.int32:
        audio = audio.astype(np.float32) / 2147483648.0
    elif audio.dtype != np.float32:
        audio = audio.astype(np.float32)

    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    time, frequency, confidence, _ = crepe.predict(audio, sr, viterbi=True, verbose=0)

    results: list[tuple[float, float, float]] = []
    for t, f, c in zip(time, frequency, confidence):
        if f > 0 and c >= _CREPE_CONFIDENCE_THRESHOLD:
            results.append((round(float(t), 4), round(float(f), 2), round(float(c), 4)))

    return results
