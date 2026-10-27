"""
Input validation and music theory helpers for pitch-mcp.

No MCP SDK imports and no business logic here.
"""

import math
import os
from pathlib import Path
from typing import Optional

from sheet_music_mcp_core.parts import PartInfo, music21_part_infos, resolve_part


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def validate_audio_path(path: str) -> tuple[bool, str]:
    """Return (True, '') if path is a readable WAV file, else (False, reason)."""
    if not path or not path.strip():
        return False, "audio_path is empty."
    p = Path(path)
    if not p.exists():
        return False, f"Audio file not found: {path!r}"
    if p.suffix.lower() not in (".wav",):
        return False, (
            f"Unsupported audio format: {p.suffix!r}. "
            "Only WAV (16-bit PCM) is supported."
        )
    return True, ""


def validate_musicxml(musicxml: str) -> tuple[bool, str]:
    """Return (True, '') if the string looks like MusicXML, else (False, reason)."""
    if not musicxml or not musicxml.strip():
        return False, "MusicXML string is empty."
    if "<score-partwise" not in musicxml and "<score-timewise" not in musicxml:
        return False, (
            "Input does not appear to be MusicXML: "
            "no <score-partwise> or <score-timewise> root element found."
        )
    return True, ""


def validate_session_id(session_id: str) -> tuple[bool, str]:
    """Return (True, '') if session_id is a non-empty string."""
    if not session_id or not session_id.strip():
        return False, "session_id is empty."
    return True, ""


# ---------------------------------------------------------------------------
# Music theory helpers
# ---------------------------------------------------------------------------

def hz_to_note(hz: float) -> tuple[str, int]:
    """Convert a frequency in Hz to (note_name, cents_deviation).

    Returns:
        ('A4', 0)  — A4 at exactly 440 Hz
        ('A4', 12) — 12 cents sharp of A4 (between A4 and A#4)
        ('A4', -12) — 12 cents flat of A4

    Raises:
        ValueError: if hz <= 0.
    """
    if hz <= 0:
        raise ValueError(f"Frequency must be positive, got {hz}")

    # MIDI note number (continuous, fractional)
    midi_float = 69.0 + 12.0 * math.log2(hz / 440.0)
    nearest_midi = round(midi_float)
    cents_dev = round((midi_float - nearest_midi) * 100)

    # Convert MIDI integer to note name
    note_name = _midi_to_note_name(nearest_midi)
    return note_name, cents_dev


def note_name_to_hz(note_name: str) -> float:
    """Convert a note name like 'A4' or 'C#5' to its frequency in Hz."""
    midi = _note_name_to_midi(note_name)
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def classify_accuracy(cents: int, threshold: int = 25) -> str:
    """Return 'on_pitch', 'sharp', or 'flat' based on cents deviation."""
    if abs(cents) <= threshold:
        return "on_pitch"
    elif cents > threshold:
        return "sharp"
    else:
        return "flat"


# ---------------------------------------------------------------------------
# Note sequence extraction from MusicXML
# ---------------------------------------------------------------------------

def extract_note_sequence(musicxml_str: str, part_id: str) -> list[dict]:
    """Extract notes from one part as a time-stamped sequence; see extract_part_notes."""
    return extract_part_notes(musicxml_str, part_id)[1]


def extract_part_notes(musicxml_str: str, part_id: str) -> tuple[PartInfo, list[dict]]:
    """Resolve one part and extract its notes as a time-stamped sequence.

    Args:
        musicxml_str: MusicXML document as a string.
        part_id: The part to extract: ID, name or voice (e.g. 'P1', 'Soprano', 'S'). Parts are
            selected by position against stable MusicXML part IDs, never music21's part.id.

    Returns:
        (PartInfo of the resolved part, list of dicts):
            {
                "note_name": "G4",
                "freq_hz": 392.0,
                "start_sec": 0.0,
                "end_sec": 0.5,
                "measure": 1,
                "beat": 1.0,
                "midi": 67,
            }

    Raises:
        ValueError: if the score cannot be parsed or has no parts.
        PartSelectionError: if part_id matches no part, or several (INVALID_PARAMETER, choices).
    """
    try:
        import music21
        import music21.converter
        import music21.note
        import music21.tempo
    except ImportError as e:
        raise RuntimeError(f"music21 is not available: {e}")

    try:
        score = music21.converter.parseData(musicxml_str, format="musicxml")
    except Exception as e:
        raise ValueError(f"Failed to parse MusicXML: {e}")

    all_parts = list(score.parts)
    if not all_parts:
        raise ValueError("No parts found in score.")

    infos = music21_part_infos(all_parts)
    chosen = resolve_part(part_id, infos)
    part, info = next((p, i) for p, i in zip(all_parts, infos) if i.id == chosen)

    # Build a MetronomeMap so we can convert offsets to seconds
    metronome_map = _build_metronome_map(score)

    result: list[dict] = []
    for elem in part.flatten().notesAndRests:
        if isinstance(elem, music21.note.Rest):
            continue

        # Handle chords: take the highest pitch (melody note)
        if hasattr(elem, "pitches"):
            pitch = elem.pitches[-1]  # highest pitch in chord
        elif hasattr(elem, "pitch"):
            pitch = elem.pitch
        else:
            continue

        offset_ql = float(elem.offset)  # offset in quarter lengths from score start
        dur_ql = float(elem.quarterLength)

        start_sec = _offset_to_seconds(offset_ql, metronome_map)
        end_sec = _offset_to_seconds(offset_ql + dur_ql, metronome_map)

        midi = round(pitch.midi)
        note_name = f"{pitch.name}{pitch.octave}"
        freq_hz = 440.0 * (2.0 ** ((midi - 69) / 12.0))

        # Find measure and beat
        measure_num, beat = _offset_to_measure_beat(elem, part)

        result.append(
            {
                "note_name": note_name,
                "freq_hz": round(freq_hz, 2),
                "start_sec": round(start_sec, 4),
                "end_sec": round(end_sec, 4),
                "measure": measure_num,
                "beat": beat,
                "midi": midi,
            }
        )

    return info, result


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _midi_to_note_name(midi: int) -> str:
    """Convert MIDI integer (e.g. 69) to note name (e.g. 'A4')."""
    octave = (midi // 12) - 1
    name = _NOTE_NAMES[midi % 12]
    return f"{name}{octave}"


def _note_name_to_midi(note_name: str) -> int:
    """Convert a note name like 'A4' or 'C#5' to a MIDI integer."""
    # Parse note name: letter + optional accidental + octave
    name = note_name.strip()
    if len(name) < 2:
        raise ValueError(f"Invalid note name: {note_name!r}")

    if len(name) >= 3 and name[1] in ("#", "b"):
        step = name[:2]
        octave = int(name[2:])
    else:
        step = name[0]
        octave = int(name[1:])

    step_map = {
        "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
        "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8,
        "A": 9, "A#": 10, "Bb": 10, "B": 11,
    }
    if step not in step_map:
        raise ValueError(f"Unknown note step: {step!r} in {note_name!r}")

    return (octave + 1) * 12 + step_map[step]


def extract_nominal_tempo_bpm(musicxml_str: str) -> float:
    """Return the score's tempo (BPM) at the start of the piece.

    Falls back to 120 BPM if no metronome mark is present, matching
    `_build_metronome_map`'s own default.
    """
    try:
        import music21.converter
    except ImportError as e:
        raise RuntimeError(f"music21 is not available: {e}")

    score = music21.converter.parseData(musicxml_str, format="musicxml")
    metronome_map = _build_metronome_map(score)
    sec_per_ql = metronome_map[0][1]
    return 60.0 / sec_per_ql


def _build_metronome_map(score) -> list[tuple[float, float]]:
    """Build a list of (offset_ql, seconds_per_ql) pairs for tempo changes.

    Returns entries sorted by offset so we can binary-search for any offset.
    """
    import music21.tempo

    marks = list(score.flatten().getElementsByClass(music21.tempo.MetronomeMark))
    if not marks:
        # Default 120 BPM: 0.5 seconds per quarter note
        return [(0.0, 0.5)]

    # Sort by offset
    marks.sort(key=lambda m: float(m.offset))

    result: list[tuple[float, float]] = []
    for mark in marks:
        bpm = mark.number or 120.0
        sec_per_ql = 60.0 / bpm  # seconds per quarter note
        result.append((float(mark.offset), sec_per_ql))

    if not result or result[0][0] > 0:
        result.insert(0, (0.0, 60.0 / 120.0))  # assume 120 BPM from start

    return result


def _offset_to_seconds(offset_ql: float, metronome_map: list[tuple[float, float]]) -> float:
    """Convert a score offset in quarter lengths to wall-clock seconds."""
    # Find the last tempo change at or before offset_ql
    seconds = 0.0
    prev_offset = 0.0
    prev_sec_per_ql = metronome_map[0][1] if metronome_map else 0.5

    for i, (map_offset, sec_per_ql) in enumerate(metronome_map):
        if map_offset >= offset_ql:
            break
        # Accumulate time from prev_offset to map_offset at prev_sec_per_ql
        seconds += (map_offset - prev_offset) * prev_sec_per_ql
        prev_offset = map_offset
        prev_sec_per_ql = sec_per_ql

    seconds += (offset_ql - prev_offset) * prev_sec_per_ql
    return seconds


def _offset_to_measure_beat(elem, part) -> tuple[int, float]:
    """Return (measure_number, beat) for an element within a part."""
    try:
        site = elem.getContextByClass("Measure")
        if site is not None:
            return int(site.number), float(elem.beat)
    except Exception:
        pass
    return 1, 1.0
