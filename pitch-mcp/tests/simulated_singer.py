"""A deterministic simulated singer for grading tests (S4). Test support, not product code.

Three small steps that tests compose:

1. ``reference_notes`` / ``sung_notes``: score -> note list (what the singer intends).
2. Fault injectors on that list (``sharpen``, ``delay``, ``octave_slip``, ``vibrato``), each
   returning a new list, plus fault injectors on the waveform (``add_noise``, ``breath_gap``).
3. ``render``: note list -> waveform (a harmonic tone, so it is a little like a voice).
"""

from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from pitch_mcp.utils import extract_part_notes

SAMPLE_RATE = 22050
HARMONICS = (1.0, 0.5, 0.25, 0.125)  # amplitudes of partials 1..4
FADE_SECONDS = 0.01  # removes clicks at note edges
TAIL_SECONDS = 0.2  # silence after the last note


@dataclass(frozen=True)
class SungNote:
    freq_hz: float
    start_sec: float
    end_sec: float
    vibrato_hz: float = 0.0
    vibrato_cents: float = 0.0


def reference_notes(musicxml: str, part: str = "Soprano") -> list[dict]:
    """The part's notes as the product reads them (pitch_mcp.utils.extract_part_notes)."""
    return extract_part_notes(musicxml, part)[1]


def sung_notes(reference: list[dict]) -> list[SungNote]:
    """A perfect singer: every note at its reference pitch and time."""
    return [SungNote(n["freq_hz"], n["start_sec"], n["end_sec"]) for n in reference]


def _replace(notes: list[SungNote], index: int, **changes) -> list[SungNote]:
    return [replace(n, **changes) if i == index else n for i, n in enumerate(notes)]


def sharpen(notes: list[SungNote], index: int, cents: float) -> list[SungNote]:
    """Note ``index`` sung ``cents`` sharp (negative: flat)."""
    return _replace(notes, index, freq_hz=notes[index].freq_hz * 2 ** (cents / 1200))


def octave_slip(notes: list[SungNote], index: int, octaves: int = 1) -> list[SungNote]:
    """Note ``index`` sung ``octaves`` higher (negative: lower)."""
    return _replace(notes, index, freq_hz=notes[index].freq_hz * 2.0**octaves)


def delay(notes: list[SungNote], index: int, seconds: float) -> list[SungNote]:
    """Note ``index`` enters ``seconds`` late and still ends on time."""
    return _replace(notes, index, start_sec=notes[index].start_sec + seconds)


def vibrato(notes: list[SungNote], index: int, rate_hz: float, depth_cents: float) -> list[SungNote]:
    """Note ``index`` sung with vibrato of +-``depth_cents`` at ``rate_hz``."""
    return _replace(notes, index, vibrato_hz=rate_hz, vibrato_cents=depth_cents)


def _tone(note: SungNote, sample_rate: int) -> np.ndarray:
    t = np.arange(int(round((note.end_sec - note.start_sec) * sample_rate))) / sample_rate
    cents = note.vibrato_cents * np.sin(2 * np.pi * note.vibrato_hz * t)
    freq = note.freq_hz * 2 ** (cents / 1200)
    phase = 2 * np.pi * np.cumsum(freq) / sample_rate  # integrate frequency: no phase jumps
    wave = sum(a * np.sin((k + 1) * phase) for k, a in enumerate(HARMONICS)) / sum(HARMONICS)
    fade = min(int(FADE_SECONDS * sample_rate), len(t) // 2)
    envelope = np.ones(len(t))
    envelope[:fade] = np.linspace(0, 1, fade)
    envelope[len(t) - fade :] = np.linspace(1, 0, fade)
    return 0.5 * wave * envelope


def render(notes: list[SungNote], sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """The waveform (float, mono, -1..1) of the notes, each placed at its start time."""
    total = int((max(n.end_sec for n in notes) + TAIL_SECONDS) * sample_rate)
    audio = np.zeros(total)
    for note in notes:
        begin = int(round(note.start_sec * sample_rate))
        tone = _tone(note, sample_rate)
        audio[begin : begin + len(tone)] += tone[: total - begin]
    return audio


def add_noise(audio: np.ndarray, snr_db: float, seed: int = 0) -> np.ndarray:
    """White Gaussian noise added at ``snr_db`` relative to the signal's RMS power."""
    noise_power = np.mean(audio**2) / 10 ** (snr_db / 10)
    noise = np.random.default_rng(seed).normal(0.0, np.sqrt(noise_power), len(audio))
    return audio + noise


def breath_gap(
    audio: np.ndarray, start_sec: float, end_sec: float, sample_rate: int = SAMPLE_RATE
) -> np.ndarray:
    """The audio with silence between ``start_sec`` and ``end_sec``."""
    out = audio.copy()
    out[int(start_sec * sample_rate) : int(end_sec * sample_rate)] = 0.0
    return out


def write_wav(path: Path, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    """Write 16-bit PCM mono."""
    pcm = np.clip(audio, -1.0, 1.0)
    wavfile.write(str(path), sample_rate, (pcm * 32767).astype(np.int16))
