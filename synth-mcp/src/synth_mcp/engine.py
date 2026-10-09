"""
Core synthesis engine for synth-mcp.

No MCP SDK imports here — this module is independently unit-testable.

Pipeline:
    MusicXML string
        → parse_parts()       → list of part metadata dicts
        → extract_midi()      → MIDI bytes
        → synthesize_midi()   → WAV file at output_path, returns duration (seconds)
"""

import copy
import logging
import os
import tempfile
import wave
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ProcessingError(Exception):
    """Raised when a synthesis step fails in an expected, reportable way."""

    def __init__(self, message: str, error_code: str = "PROCESSING_FAILED"):
        super().__init__(message)
        self.error_code = error_code


# ---------------------------------------------------------------------------
# Step 1 — parse parts
# ---------------------------------------------------------------------------

def parse_parts(musicxml_str: str) -> list[dict]:
    """Parse a MusicXML string and return metadata for each voice part.

    Returns:
        List of dicts: [{"id": "P1", "name": "Soprano", "measure_count": 32}, ...]

    Raises:
        ProcessingError: on parse failure or empty score.
    """
    try:
        import music21.converter  # noqa: F401 — verify availability
    except ImportError as e:
        raise ProcessingError(f"music21 is not available: {e}", "PROCESSING_FAILED")

    try:
        import music21
        score = music21.converter.parseData(musicxml_str, format="musicxml")
    except Exception as e:
        raise ProcessingError(f"Failed to parse MusicXML: {e}", "INVALID_INPUT")

    parts = list(score.parts)
    if not parts:
        raise ProcessingError(
            "No parts found in score. Verify the MusicXML contains <part> elements.",
            "INVALID_INPUT",
        )

    result = []
    for part in parts:
        measure_count = len(list(part.getElementsByClass("Measure")))
        result.append(
            {
                "id": part.id,
                "name": part.partName or part.id,
                "measure_count": measure_count,
            }
        )

    return result


# ---------------------------------------------------------------------------
# Step 2 — extract MIDI
# ---------------------------------------------------------------------------

def extract_midi(
    musicxml_str: str,
    part_ids: Optional[list[str]],
    tempo_factor: float,
) -> bytes:
    """Export selected parts of a MusicXML score to MIDI bytes.

    Args:
        musicxml_str: MusicXML document as a string.
        part_ids: Part IDs to include; None means all parts.
        tempo_factor: Tempo multiplier applied to all MetronomeMarks (0.25–4.0).

    Returns:
        Raw MIDI file bytes.

    Raises:
        ProcessingError: on parse error, invalid part ID, or MIDI export failure.
    """
    try:
        import music21
        import music21.converter
        import music21.midi.translate
        import music21.stream
        import music21.tempo
    except ImportError as e:
        raise ProcessingError(f"music21 is not available: {e}", "PROCESSING_FAILED")

    try:
        score = music21.converter.parseData(musicxml_str, format="musicxml")
    except Exception as e:
        raise ProcessingError(f"Failed to parse MusicXML: {e}", "INVALID_INPUT")

    all_parts = list(score.parts)
    if not all_parts:
        raise ProcessingError("No parts found in score", "INVALID_INPUT")

    # Validate and filter by part_ids
    if part_ids is not None:
        available_ids = {p.id for p in all_parts}
        invalid = [pid for pid in part_ids if pid not in available_ids]
        if invalid:
            raise ProcessingError(
                f"Invalid part IDs: {invalid}. Valid IDs: {sorted(available_ids)}",
                "INVALID_PARAMETER",
            )
        selected = [p for p in all_parts if p.id in part_ids]
    else:
        selected = all_parts

    # Build a new score from deep-copied parts so we don't mutate the original
    new_score = music21.stream.Score()
    for part in selected:
        new_score.append(copy.deepcopy(part))

    # MusicXML usually carries the tempo only in the top part; borrow it so a
    # lower part exported alone doesn't fall back to MIDI's 120 BPM default.
    _carry_over_tempo_marks(score, new_score)

    # Apply tempo factor to all MetronomeMarks
    if tempo_factor != 1.0:
        marks = list(new_score.recurse().getElementsByClass(music21.tempo.MetronomeMark))
        if marks:
            for mm in marks:
                if mm.number is not None:
                    mm.number = mm.number * tempo_factor
        else:
            # No explicit tempo — insert a scaled default (120 BPM) at measure 1
            first_part = new_score.parts[0]
            measures = list(first_part.getElementsByClass("Measure"))
            if measures:
                mm = music21.tempo.MetronomeMark(number=120.0 * tempo_factor)
                measures[0].insert(0, mm)

    # Export to MIDI bytes via a temp file
    try:
        midi_file = music21.midi.translate.streamToMidiFile(new_score)
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f:
            tmp_path = f.name
        try:
            midi_file.open(tmp_path, "wb")
            midi_file.write()
            midi_file.close()
            with open(tmp_path, "rb") as f:
                return f.read()
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    except Exception as e:
        raise ProcessingError(f"Failed to export MIDI: {e}", "PROCESSING_FAILED")


def _carry_over_tempo_marks(source_score, target_score) -> None:
    """Copy the source score's tempo marks into target_score if it has none.

    Each mark is placed at its original score offset, in the first part of
    target_score. When several parts carry a mark at the same offset, the one
    from the topmost part wins.
    """
    import music21.tempo

    if target_score.recurse().getElementsByClass(music21.tempo.MetronomeMark).first():
        return

    marks_by_offset = {}
    for mm in source_score.recurse().getElementsByClass(music21.tempo.MetronomeMark):
        marks_by_offset.setdefault(mm.getOffsetInHierarchy(source_score), mm)
    if not marks_by_offset:
        return

    measures = list(target_score.parts[0].getElementsByClass("Measure"))
    for offset, mm in sorted(marks_by_offset.items()):
        for measure in reversed(measures):
            if measure.offset <= offset:
                measure.insert(offset - measure.offset, copy.deepcopy(mm))
                break


# ---------------------------------------------------------------------------
# Step 3 — synthesize to WAV
# ---------------------------------------------------------------------------

def synthesize_midi(midi_bytes: bytes, output_path: str) -> float:
    """Render MIDI bytes to a WAV file using the FluidSynth CLI.

    The soundfont is read from the SYNTH_SOUNDFONT_PATH environment variable.

    Args:
        midi_bytes: Raw MIDI file bytes.
        output_path: Destination path for the WAV file.

    Returns:
        Duration of the rendered audio in seconds.

    Raises:
        ProcessingError: if the soundfont is missing, FluidSynth is unavailable,
                         or rendering fails.
    """
    soundfont_path = os.environ.get("SYNTH_SOUNDFONT_PATH", "")
    if not soundfont_path:
        raise ProcessingError(
            "Soundfont not configured. Set SYNTH_SOUNDFONT_PATH to an SF2 file path. "
            "Download MuseScore General from "
            "https://musescore.org/en/handbook/soundfonts-and-sfz-files",
            "PROCESSING_FAILED",
        )

    if not Path(soundfont_path).exists():
        raise ProcessingError(
            f"Soundfont file not found: {soundfont_path!r}. "
            "Update SYNTH_SOUNDFONT_PATH to a valid SF2 file path.",
            "PROCESSING_FAILED",
        )

    # Verify the pyfluidsynth binding (catches a missing C library early)
    try:
        import fluidsynth
    except (ImportError, OSError) as e:
        raise ProcessingError(
            f"FluidSynth library not available: {e}. "
            "Install libfluidsynth-dev (Linux) or brew install fluid-synth (macOS)",
            "PROCESSING_FAILED",
        )

    # Write MIDI bytes to a temp file for the player
    with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f:
        f.write(midi_bytes)
        tmp_midi = f.name

    try:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        fs = fluidsynth.Synth(
            gain=0.5,
            samplerate=44100,
            **{
                "audio.driver": "file",
                "audio.file.name": output_path,
                "audio.file.type": "wav",
                "player.timing-source": "sample",
                "synth.lock-memory": 0,
            },
        )
        try:
            sfid = fs.sfload(soundfont_path)
            if sfid == fluidsynth.FLUID_FAILED:
                raise ProcessingError(
                    f"Failed to load soundfont: {soundfont_path!r}",
                    "PROCESSING_FAILED",
                )
            fs.sfont_select(0, sfid)
            fs.start(driver="file")
            status = fs.play_midi_file(tmp_midi)
            if status == fluidsynth.FLUID_FAILED:
                raise ProcessingError("FluidSynth MIDI player failed to start", "PROCESSING_FAILED")
            fluidsynth.fluid_player_join(fs.player)
        finally:
            fs.delete()

        if not Path(output_path).exists():
            raise ProcessingError(
                "Synthesis completed but did not produce an output WAV file.",
                "PROCESSING_FAILED",
            )

        return _get_wav_duration(output_path)

    except ProcessingError:
        raise
    except Exception as e:
        raise ProcessingError(f"Synthesis failed: {e}", "PROCESSING_FAILED")
    finally:
        Path(tmp_midi).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_wav_duration(wav_path: str) -> float:
    """Return the duration of a WAV file in seconds."""
    with wave.open(wav_path, "r") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        return frames / rate if rate > 0 else 0.0
