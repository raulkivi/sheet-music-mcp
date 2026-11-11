"""Compare detected pitch frames with the score's notes (test support for the S3 round trip).

Pure: score notes (``pitch_mcp.utils.extract_part_notes``) and frames
(``pitch_detector.detect_pitches``: ``(time_s, hz, confidence)``) in, problems out.

- **Onset**: the first frame within ``MATCH_CENTS`` of the note, searched from ``SEARCH_S`` before
  the note's start to its end. A note that repeats the previous pitch would match the previous
  note's frames, so the fixture has no repeated pitches.
- **Pitch**: the median of the frames from ``SETTLE_S`` after the onset to ``SETTLE_S`` before the
  note's end (the attack and the release are not the pitch), in cents from the score.

``off_notes`` lists the notes ``analyze_recording`` did not grade on_pitch, for failure messages.
"""

import math
from collections.abc import Sequence

SEARCH_S = 0.2
MATCH_CENTS = 50.0
SETTLE_S = 0.05
PITCH_TOLERANCE_CENTS = 25.0
ONSET_TOLERANCE_S = 0.05


def _cents(hz: float, reference_hz: float) -> float:
    return 1200 * math.log2(hz / reference_hz)


def compare(
    score_notes: Sequence[dict],
    frames: Sequence[tuple[float, float, float]],
    *,
    pitch_tolerance_cents: float = PITCH_TOLERANCE_CENTS,
    onset_tolerance_s: float = ONSET_TOLERANCE_S,
) -> list[str]:
    """One readable line per note whose pitch or onset is off the score; empty when all match."""
    problems = []
    for note in score_notes:
        start, end, hz = note["start_sec"], note["end_sec"], note["freq_hz"]
        where = f"{note['note_name']} (m{note['measure']} b{note['beat']:g}, {start:.3f}s)"
        onset = next(
            (
                t
                for t, f, _ in frames
                if start - SEARCH_S <= t < end and abs(_cents(f, hz)) <= MATCH_CENTS
            ),
            None,
        )
        if onset is None:
            problems.append(f"{where}: not detected")
            continue
        error = onset - start
        if abs(error) > onset_tolerance_s:
            problems.append(f"{where}: onset {error * 1000:+.0f} ms")
        steady = sorted(f for t, f, _ in frames if onset + SETTLE_S <= t < end - SETTLE_S)
        if not steady:
            problems.append(f"{where}: no steady frames after the onset")
            continue
        cents = _cents(steady[len(steady) // 2], hz)
        if abs(cents) > pitch_tolerance_cents:
            problems.append(f"{where}: {cents:+.0f} cents")
    return problems


def off_notes(note_accuracy: Sequence[dict]) -> list[str]:
    """One readable line per ``analyze_recording`` note not graded on_pitch; empty when all are."""
    lines = []
    for note in note_accuracy:
        if note["status"] == "on_pitch":
            continue
        where = f"m{note['measure']} b{note['beat']:g} {note['expected']}"
        expected = f"expected {note['expected_hz']:.2f} Hz"
        if note["sung_hz"] is None:
            lines.append(f"{where}: {expected}, detected nothing ({note['status']})")
        else:
            lines.append(
                f"{where}: {expected}, detected {note['sung_hz']:.2f} Hz, "
                f"{note['accuracy_cents']:+d} cents ({note['status']})"
            )
    return lines
