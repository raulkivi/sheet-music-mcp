"""
Score alignment for pitch-mcp.

Maps a sequence of detected pitches to a reference note sequence using
Dynamic Time Warping (DTW). Returns per-note pitch accuracy data.

Algorithm:
    1. Convert both sequences to MIDI note numbers (continuous float for detected,
       integer for reference).
    2. Run DTW (windowed) to find the best temporal alignment.
    3. For each reference note, find the set of detected frames aligned to it
       and compute the average frequency deviation in cents.
"""

import logging
import math
import statistics
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def align(
    detected: list[tuple[float, float, float]],
    note_sequence: list[dict],
    window: int = 50,
) -> list[dict]:
    """Align detected pitches to a reference note sequence using DTW.

    Args:
        detected: List of (time_sec, freq_hz, confidence) from pitch_detector.
        note_sequence: List of note dicts from utils.extract_note_sequence.
        window: DTW warping window in frames. Larger = more flexible alignment.

    Returns:
        List of per-note accuracy dicts:
            {
                "measure": int,
                "beat": float,
                "expected": "G4",
                "expected_hz": 392.0,
                "sung_hz": 395.2,
                "accuracy_cents": 12,
                "status": "sharp",   # "on_pitch" | "sharp" | "flat" | "no_signal"
            }
        Returns an empty list if either sequence is empty.
    """
    if not note_sequence:
        return []

    if not detected:
        # No audio — every note is "no_signal"
        return [_no_signal_result(n) for n in note_sequence]

    # --- Step 1: Build query and reference sequences in MIDI space ---
    query_times = np.array([t for t, f, c in detected], dtype=np.float64)
    query_hz = np.array([f for t, f, c in detected], dtype=np.float64)
    query_midi = _hz_to_midi_continuous(query_hz)  # fractional MIDI numbers

    ref_midis = np.array([n["midi"] for n in note_sequence], dtype=np.float64)

    # --- Step 2: DTW alignment ---
    # dtaidistance finds the pitch-optimal monotonic mapping between the
    # reference note sequence and every detected frame, banded by `window`
    # frames. Unlike a fixed per-note time window, this lets a frame near a
    # note boundary go to whichever neighbor it actually matches in pitch,
    # so real tempo drift (rubato, hesitation) no longer misattributes
    # frames to the wrong note.
    from dtaidistance import dtw

    path = dtw.warping_path(ref_midis, query_midi, window=window)

    frame_indices_by_note: list[list[int]] = [[] for _ in note_sequence]
    for ref_idx, query_idx in path:
        frame_indices_by_note[ref_idx].append(query_idx)

    # --- Step 3: Per-note accuracy, gated by temporal plausibility ---
    # DTW always assigns every reference note at least one frame (it's a
    # full-coverage alignment), even when the singer never actually
    # attempted that note. A note whose assigned frames land nowhere near
    # its own expected time window is not a real signal — report it as
    # such rather than a spurious pitch reading.
    results: list[dict] = []
    for note, frame_idxs in zip(note_sequence, frame_indices_by_note):
        start, end = note["start_sec"], note["end_sec"]
        margin = max(0.15, (end - start) * 0.75)

        frame_times = query_times[frame_idxs]
        frame_hz = query_hz[frame_idxs]
        median_time = float(np.median(frame_times))
        plausible = (start - margin) <= median_time <= (end + margin)

        if not plausible:
            results.append(_no_signal_result(note))
            continue

        # Compute median frequency (robust to outliers)
        sung_hz = float(np.median(frame_hz))
        accuracy_cents = _hz_to_cents_deviation(sung_hz, note["freq_hz"])
        status = _classify(accuracy_cents)

        results.append(
            {
                "measure": note["measure"],
                "beat": note["beat"],
                "expected": note["note_name"],
                "expected_hz": round(note["freq_hz"], 2),
                "sung_hz": round(sung_hz, 2),
                "accuracy_cents": accuracy_cents,
                "status": status,
            }
        )

    return results


def _no_signal_result(note: dict) -> dict:
    return {
        "measure": note["measure"],
        "beat": note["beat"],
        "expected": note["note_name"],
        "expected_hz": round(note["freq_hz"], 2),
        "sung_hz": None,
        "accuracy_cents": None,
        "status": "no_signal",
    }


def _hz_to_midi_continuous(hz_array: np.ndarray) -> np.ndarray:
    """Convert Hz array to fractional MIDI note numbers."""
    with np.errstate(divide="ignore", invalid="ignore"):
        midi = 69.0 + 12.0 * np.log2(np.maximum(hz_array, 1.0) / 440.0)
    return midi.astype(np.float32)


def _hz_to_cents_deviation(sung_hz: float, expected_hz: float) -> int:
    """Return cents deviation: positive = sharp, negative = flat."""
    if expected_hz <= 0 or sung_hz <= 0:
        return 0
    ratio = sung_hz / expected_hz
    cents = round(1200.0 * math.log2(ratio))
    return int(cents)


def _classify(cents: int, threshold: int = 25) -> str:
    if abs(cents) <= threshold:
        return "on_pitch"
    return "sharp" if cents > 0 else "flat"


def summarize(note_results: list[dict]) -> dict:
    """Compute summary statistics from per-note alignment results.

    Returns:
        {
            "measures_covered": int,
            "avg_accuracy_cents": float | None,
            "accuracy_histogram": {"on_pitch": N, "sharp": N, "flat": N, "no_signal": N},
            "highlights": [...],  # see highlights()
        }
    """
    histogram = {"on_pitch": 0, "sharp": 0, "flat": 0, "no_signal": 0}
    cents_values: list[int] = []

    measures_seen: set[int] = set()

    for note in note_results:
        status = note.get("status", "no_signal")
        histogram[status] = histogram.get(status, 0) + 1
        if note.get("accuracy_cents") is not None:
            cents_values.append(abs(note["accuracy_cents"]))
        if note.get("measure") is not None:
            measures_seen.add(note["measure"])

    avg_cents = round(sum(cents_values) / len(cents_values)) if cents_values else None

    return {
        "measures_covered": len(measures_seen),
        "avg_accuracy_cents": avg_cents,
        "accuracy_histogram": histogram,
        "highlights": highlights(note_results),
    }


# ---------------------------------------------------------------------------
# Highlights: runs of flat or sharp notes in plain words (UX Wave 3, W3-7)
# ---------------------------------------------------------------------------

def highlights(
    note_results: list[dict], *, threshold: int = 25, min_run: int = 2, limit: int = 3
) -> list[dict]:
    """Name the worst runs of consecutive flat or sharp notes.

    ``note_results`` are analyze_recording's per-note results (``expected``) or a live
    session's per-frame history (``expected_note``); consecutive entries for the same note are
    merged first. A run is at least ``min_run`` consecutive notes all below ``-threshold`` cents
    (flat) or all above ``threshold`` (sharp); a no-signal or on-pitch note ends it. Runs are
    ranked by notes x |average cents| and the top ``limit`` are returned in that order:

        {"direction": "flat", "measures": [12, 14], "notes": 4, "avg_cents": -35,
         "text": "flat on E5 in m.12–14 (-35 cents avg)"}
    """
    runs = [run for run in _runs(_notes(note_results), threshold) if len(run) >= min_run]
    runs.sort(key=lambda run: len(run) * abs(_mean_cents(run)), reverse=True)  # stable on ties
    return [_highlight(run) for run in runs[:limit]]


def _notes(note_results: list[dict]) -> list[tuple[int, str, Optional[float]]]:
    """(measure, pitch, median cents or None) per note, merging consecutive entries of one note."""
    notes: list[tuple[int, str, Optional[float]]] = []
    key = None
    cents: list[int] = []
    for entry in note_results:
        pitch = entry.get("expected", entry.get("expected_note"))
        entry_key = (entry.get("measure"), entry.get("beat"), pitch)
        if entry_key != key:
            if key is not None:
                notes.append(_note(key, cents))
            key, cents = entry_key, []
        if entry.get("accuracy_cents") is not None:
            cents.append(entry["accuracy_cents"])
    if key is not None:
        notes.append(_note(key, cents))
    return notes


def _note(key: tuple, cents: list[int]) -> tuple[int, str, Optional[float]]:
    measure, _beat, pitch = key
    return measure, pitch, statistics.median(cents) if cents else None


def _runs(notes: list[tuple[int, str, Optional[float]]], threshold: int) -> list[list[tuple]]:
    """Maximal runs of consecutive notes off pitch in the same direction."""
    runs: list[list[tuple]] = []
    run: list[tuple] = []
    direction = None
    for note in notes:
        cents = note[2]
        note_direction = None if cents is None else _classify(cents, threshold)
        if note_direction not in ("flat", "sharp") or note_direction != direction:
            if run:
                runs.append(run)
            run = []
        direction = note_direction
        if note_direction in ("flat", "sharp"):
            run.append(note)
    if run:
        runs.append(run)
    return runs


def _mean_cents(run: list[tuple]) -> float:
    return sum(note[2] for note in run) / len(run)


def _highlight(run: list[tuple]) -> dict:
    avg_cents = round(_mean_cents(run))
    direction = "flat" if avg_cents < 0 else "sharp"
    first, last = run[0][0], run[-1][0]
    span = f"m.{first}" if first == last else f"m.{first}–{last}"
    pitches = {note[1] for note in run}
    if len(pitches) == 1:
        text = f"{direction} on {run[0][1]} in {span} ({avg_cents:+d} cents avg)"
    else:
        text = f"{direction} in {span} ({avg_cents:+d} cents avg over {len(run)} notes)"
    return {
        "direction": direction,
        "measures": [first, last],
        "notes": len(run),
        "avg_cents": avg_cents,
        "text": text,
    }
