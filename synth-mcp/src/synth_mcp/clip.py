"""
Starting pitches for starting_pitches (UX Wave 3 C13, decision W3-6).

No MCP SDK imports here. Pipeline:

    starting_pitches()  → each selected part's first note (core scores.first_pitches)
    pitches_text()      → "S: D5, A: A4, T: F#4, B: D3"
    clip_midi()         → piano: each note for 1 s in score order, then the chord for 2 s
    render_clip()       → synthesize_midi() (FluidSynth), then downmix_wav() to mono 16 kHz
"""

import tempfile
import wave
from pathlib import Path
from typing import Optional, Sequence

from sheet_music_mcp_core.errors import ProcessingError
from sheet_music_mcp_core.parts import PartInfo, resolve_parts
from sheet_music_mcp_core.paths import new_output_path
from sheet_music_mcp_core.scores import first_pitches

from .engine import synthesize_midi

CLIP_RATE = 16000  # Hz, mono 16-bit: about 32 KB per second
NOTE_SECONDS = 1.0
CHORD_SECONDS = 2.0
VELOCITY = 80
PIANO = 0  # GM program
_LOWPASS_TAPS = 63


def starting_pitches(musicxml_str: str, parts: Optional[Sequence[str]] = None) -> list[dict]:
    """The first note of each part (``first_pitches`` entries), or of the requested parts.

    ``parts`` are IDs, names or voices; the result keeps score order. Raises ProcessingError
    (INVALID_PARAMETER with choices for an unknown part, INVALID_INPUT for an unreadable score).
    """
    entries = first_pitches(musicxml_str)
    if parts is None:
        return entries
    infos = [PartInfo(e["id"], e["name"] or "", e["abbreviation"] or "") for e in entries]
    wanted = set(resolve_parts(parts, infos))
    return [e for e in entries if e["id"] in wanted]


def pitches_text(entries: Sequence[dict]) -> str:
    """``"S: D5, A: A4"``: label and pitch per part, leaving out parts without pitches."""
    return ", ".join(f"{e['label']}: {e['pitch']}" for e in entries if e["pitch"] is not None)


def clip_midi(midi_numbers: Sequence[int]) -> bytes:
    """Piano MIDI: each note for 1 s in the given order, then all of them together for 2 s."""
    import music21.chord
    import music21.instrument
    import music21.midi.translate
    import music21.note
    import music21.stream
    import music21.tempo

    part = music21.stream.Part()
    piano = music21.instrument.Piano()
    piano.midiProgram = PIANO
    part.insert(0, piano)
    part.insert(0, music21.tempo.MetronomeMark(number=60))  # a quarter note lasts 1 s
    offset = 0.0
    for number in midi_numbers:
        note = music21.note.Note(number, quarterLength=NOTE_SECONDS)
        note.volume.velocity = VELOCITY
        part.insert(offset, note)
        offset += NOTE_SECONDS
    chord = music21.chord.Chord(sorted(set(midi_numbers)), quarterLength=CHORD_SECONDS)
    for member in chord.notes:
        member.volume.velocity = VELOCITY
    part.insert(offset, chord)

    score = music21.stream.Score()
    score.insert(0, part)
    # No trailing rest: the clip ends with the chord, keeping a 4-part clip under 200 KB.
    return music21.midi.translate.streamToMidiFile(score, addEndDelay=False).writestr()


def render_clip(midi_bytes: bytes, output_path: Optional[str] = None) -> tuple[str, float]:
    """Render the clip with FluidSynth and write it as mono 16 kHz 16-bit WAV.

    Written to ``output_path`` (already confined by the caller) or to a new
    ``<output root>/audio/starting-pitches-<timestamp>.wav``, which is only created once the
    rendering worked. Returns (path, duration in seconds). Raises ProcessingError when there is
    no soundfont or FluidSynth, or rendering fails.
    """
    with tempfile.TemporaryDirectory() as tmp:
        rendered = str(Path(tmp) / "clip.wav")
        synthesize_midi(midi_bytes, rendered)
        target = output_path or str(new_output_path("starting-pitches", ".wav", subdir="audio"))
        return target, downmix_wav(rendered, target)


def downmix_wav(source: str, target: str, *, rate: int = CLIP_RATE) -> float:
    """Write ``source`` (PCM WAV, any channels and rate) as mono ``rate`` Hz 16-bit to ``target``.

    Channels are averaged, the signal is low-passed below the new Nyquist frequency when the rate
    goes down, then resampled by linear interpolation. Returns the duration in seconds.
    """
    import numpy as np

    with wave.open(source, "rb") as w:
        channels, width, source_rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        data = w.readframes(w.getnframes())

    samples = _pcm_to_float(np, data, width)
    mono = samples.reshape(-1, channels).mean(axis=1)
    if rate < source_rate:
        mono = _lowpass(np, mono, 0.5 * rate / source_rate)

    count = round(len(mono) * rate / source_rate)
    positions = np.arange(count) * (source_rate / rate)
    resampled = np.interp(positions, np.arange(len(mono)), mono)
    pcm = np.clip(np.round(resampled), -32768, 32767).astype("<i2")

    Path(target).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(target, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return count / rate


def _pcm_to_float(np, data: bytes, width: int):
    """PCM bytes as float samples on the 16-bit scale."""
    if width == 1:
        return (np.frombuffer(data, dtype=np.uint8).astype(np.float64) - 128.0) * 256.0
    if width == 2:
        return np.frombuffer(data, dtype="<i2").astype(np.float64)
    if width == 4:
        return np.frombuffer(data, dtype="<i4").astype(np.float64) / 65536.0
    raise ProcessingError(f"Unsupported WAV sample width: {width} bytes", "PROCESSING_FAILED")


def _lowpass(np, signal, cutoff: float):
    """Windowed-sinc FIR low-pass; ``cutoff`` is a fraction of the sample rate (< 0.5)."""
    n = np.arange(_LOWPASS_TAPS) - (_LOWPASS_TAPS - 1) / 2
    taps = 2 * cutoff * np.sinc(2 * cutoff * n) * np.hamming(_LOWPASS_TAPS)
    taps /= taps.sum()
    return np.convolve(signal, taps, mode="same")
