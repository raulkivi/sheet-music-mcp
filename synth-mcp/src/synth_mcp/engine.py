"""
Core synthesis engine for synth-mcp.

No MCP SDK imports here — this module is independently unit-testable.

Pipeline:
    MusicXML string
        → parse_parts()       → list of part metadata dicts
        → resolve_part_ids()  → stable part IDs for the requested parts (ID, name or voice)
        → extract_midi()      → MIDI bytes (practice options: practice.py)
        → synthesize_midi()   → WAV file at output_path, returns duration (seconds)
"""

import copy
import logging
import os
import tempfile
import wave
from pathlib import Path
from typing import Optional

from sheet_music_mcp_core.errors import ProcessingError  # re-exported for server.py
from sheet_music_mcp_core.measures import select_measures
from sheet_music_mcp_core.parts import music21_part_infos, resolve_parts

from .practice import (
    add_clicks,
    expand_repeats,
    is_percussion,
    repeat_music,
    resolve_gains,
    scale_tempo,
    tune_midi,
    validate_options,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step 1 — parse parts
# ---------------------------------------------------------------------------

def parse_parts(musicxml_str: str) -> list[dict]:
    """Parse a MusicXML string and return metadata for each voice part.

    Part IDs are the MusicXML score-part ids (docs/conventions.md, Part Selection), never
    music21's part.id.

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
    for part, info in zip(parts, music21_part_infos(parts)):
        measure_count = len(list(part.getElementsByClass("Measure")))
        result.append(
            {
                "id": info.id,
                "name": info.name or info.id,
                "measure_count": measure_count,
            }
        )

    return result


def resolve_part_ids(musicxml_str: str, requested: list[str]) -> list[str]:
    """Return the stable IDs of the parts matching ``requested`` (IDs, names or voices).

    Raises:
        ProcessingError: on parse failure; PartSelectionError (INVALID_PARAMETER, with choices)
        when a request matches no part.
    """
    try:
        import music21
        score = music21.converter.parseData(musicxml_str, format="musicxml")
    except ImportError as e:
        raise ProcessingError(f"music21 is not available: {e}", "PROCESSING_FAILED")
    except Exception as e:
        raise ProcessingError(f"Failed to parse MusicXML: {e}", "INVALID_INPUT")

    return resolve_parts(requested, music21_part_infos(score.parts))


# ---------------------------------------------------------------------------
# Step 2 — extract MIDI
# ---------------------------------------------------------------------------

def extract_midi(
    musicxml_str: str,
    part_ids: Optional[list[str]],
    tempo_factor: float,
    *,
    measures=None,
    repeat: int = 1,
    count_in_bars: int = 0,
    metronome: bool = False,
    timbre: str = "score",
    part_gains: Optional[dict] = None,
    preset: Optional[str] = None,
    focus_part: Optional[str] = None,
) -> bytes:
    """Export selected parts of a MusicXML score to MIDI bytes.

    Args:
        musicxml_str: MusicXML document as a string.
        part_ids: Parts to include (IDs, names or voices, see resolve_part_ids); None means all.
        tempo_factor: Tempo multiplier applied to all MetronomeMarks (0.25–4.0).
        measures: Inclusive [start, end] printed measure numbers; None means the whole score.
        repeat: Play the selected music this many times (1–20).
        count_in_bars: Bars of clicks before the music (0–4).
        metronome: Clicks on every beat of the music too.
        timbre: "score" (the score's instruments), "piano", "choir" or "organ".
        part_gains: Part (ID, name or voice) → gain 0.0–2.0, sent as CC7.
        preset: "learning", "karaoke" or "equal": base gains around ``focus_part``.
        focus_part: The part a learning or karaoke preset is for.

    Every practice option at its default gives the same MIDI as before (docs/conventions.md,
    Practice Audio).

    Returns:
        Raw MIDI file bytes.

    Raises:
        ProcessingError: on parse error, unknown part, invalid option, or MIDI export failure.
    """
    try:
        import music21
        import music21.converter
        import music21.midi.translate
        import music21.stream
    except ImportError as e:
        raise ProcessingError(f"music21 is not available: {e}", "PROCESSING_FAILED")

    program = validate_options(repeat, count_in_bars, metronome, timbre)
    # Cut the bars before music21 sees the score (docs/conventions.md, Measure Ranges).
    musicxml_str = select_measures(musicxml_str, measures)

    try:
        score = music21.converter.parseData(musicxml_str, format="musicxml")
    except Exception as e:
        raise ProcessingError(f"Failed to parse MusicXML: {e}", "INVALID_INPUT")

    all_parts = list(score.parts)
    if not all_parts:
        raise ProcessingError("No parts found in score", "INVALID_INPUT")

    # Select by position against the stable part IDs, never by music21's part.id
    infos = music21_part_infos(all_parts)
    if part_ids is not None:
        wanted = set(resolve_parts(part_ids, infos))
        chosen = [(p, info) for p, info in zip(all_parts, infos) if info.id in wanted]
    else:
        chosen = list(zip(all_parts, infos))
    selected = [p for p, _ in chosen]

    gains = resolve_gains([info for _, info in chosen], part_gains, preset, focus_part)

    # Build a new score from deep-copied parts so we don't mutate the original
    new_score = music21.stream.Score()
    for part in selected:
        new_score.append(copy.deepcopy(part))

    # MusicXML usually carries the tempo only in the top part; borrow it so a
    # lower part exported alone doesn't fall back to MIDI's 120 BPM default.
    _carry_over_tempo_marks(score, new_score)

    # Practice steps (practice.py); each is a no-op at its default.
    if count_in_bars or metronome:
        new_score = expand_repeats(new_score)  # clicks follow the bars as played
    repeat_music(new_score, repeat)
    scale_tempo(new_score, tempo_factor)
    clicks = add_clicks(new_score, count_in_bars, metronome)

    try:
        midi_file = music21.midi.translate.streamToMidiFile(new_score)
    except Exception as e:
        raise ProcessingError(f"Failed to export MIDI: {e}", "PROCESSING_FAILED")

    if gains is not None or program is not None or clicks:
        tune_midi(
            midi_file,
            percussion=[is_percussion(p) for p in selected],
            gains=gains,
            program=program,
            clicks=clicks,
        )

    # Write the MIDI bytes via a temp file
    try:
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

def wav_format(wav_path: str) -> tuple[int, int]:
    """``(sample_rate, channels)`` of a WAV file, as the player needs them to decode it."""
    with wave.open(wav_path, "r") as wf:
        return wf.getframerate(), wf.getnchannels()


def describe_mix(
    musicxml_str: str,
    part_ids: Optional[list[str]],
    *,
    part_gains: Optional[dict] = None,
    preset: Optional[str] = None,
    focus_part: Optional[str] = None,
) -> list[dict]:
    """Every part of the score with whether ``extract_midi`` plays it and at which gain.

    Takes the same selection and gain options as ``extract_midi`` and resolves them with the
    same functions, so the player's mixer shows what was really rendered. A part that was left
    out reports gain 0.0 (it is silent in the track).

    Raises:
        ProcessingError: on parse failure, unknown part or invalid gain option.
    """
    try:
        import music21.converter
        score = music21.converter.parseData(musicxml_str, format="musicxml")
    except ImportError as e:
        raise ProcessingError(f"music21 is not available: {e}", "PROCESSING_FAILED")
    except Exception as e:
        raise ProcessingError(f"Failed to parse MusicXML: {e}", "INVALID_INPUT")

    infos = music21_part_infos(score.parts)
    wanted = {info.id for info in infos} if part_ids is None else set(resolve_parts(part_ids, infos))
    chosen = [info for info in infos if info.id in wanted]
    gains = resolve_gains(chosen, part_gains, preset, focus_part) or [1.0] * len(chosen)
    gain_of = {info.id: gain for info, gain in zip(chosen, gains)}
    return [
        {
            "id": info.id,
            "name": info.name or info.id,
            "included": info.id in wanted,
            "gain": float(gain_of.get(info.id, 0.0)),
        }
        for info in infos
    ]


def _get_wav_duration(wav_path: str) -> float:
    """Return the duration of a WAV file in seconds."""
    with wave.open(wav_path, "r") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        return frames / rate if rate > 0 else 0.0
