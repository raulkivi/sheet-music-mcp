"""synth-mcp -> pitch-mcp round trip (S3 in docs/research/ui-and-sound-testing-plan.md).

Each part of ``fixtures/satb_round_trip.musicxml`` is rendered by synth-mcp in its own venv
(``synth_bridge``), then pitch-mcp's detector reads it back. Every note must be within +-25 cents
of the score and start within +-50 ms of it. The comparison (``round_trip.compare``) is unit-tested
here on made-up frames; the round trip itself is an integration test that needs synth-mcp's venv and
a soundfont. Set ``PITCH_ROUND_TRIP_REQUIRED=1`` (CI does) to fail instead of skipping without them.
"""

import os
from pathlib import Path

import numpy as np
import pytest

from pitch_mcp.engine import analyze_recording
from pitch_mcp.pitch_detector import detect_pitches
from pitch_mcp.utils import extract_part_notes

from . import round_trip, synth_bridge

SCORE = Path(__file__).parent / "fixtures" / "satb_round_trip.musicxml"
HOP = 512 / 44100  # pYIN frame step at synth-mcp's sample rate


def note(name, start, end, hz, measure=1, beat=1.0):
    return {"note_name": name, "start_sec": start, "end_sec": end, "freq_hz": hz,
            "measure": measure, "beat": beat}


def frames(*segments):
    """Voiced frames: each segment is (start_s, end_s, hz)."""
    out = []
    for start, end, hz in segments:
        out += [(round(t, 4), hz, 0.9) for t in np.arange(start, end, HOP)]
    return out


A4, B4 = 440.0, 493.88
PHRASE = [note("A4", 0.0, 0.6, A4), note("B4", 0.6, 1.2, B4, beat=2.0)]


class TestCompare:
    def test_a_faithful_rendition_has_no_mismatches(self):
        assert round_trip.compare(PHRASE, frames((0.0, 0.6, A4), (0.6, 1.2, B4))) == []

    def test_a_note_30_cents_sharp_is_reported(self):
        sharp = B4 * 2 ** (30 / 1200)
        [problem] = round_trip.compare(PHRASE, frames((0.0, 0.6, A4), (0.6, 1.2, sharp)))
        assert "B4" in problem and "+30 cents" in problem

    def test_20_cents_is_within_tolerance(self):
        flat = A4 * 2 ** (-20 / 1200)
        assert round_trip.compare(PHRASE, frames((0.0, 0.6, flat), (0.6, 1.2, B4))) == []

    def test_a_note_80_ms_late_is_reported(self):
        # The previous note rings on until the late one starts, as a held key does.
        [problem] = round_trip.compare(PHRASE, frames((0.0, 0.68, A4), (0.68, 1.2, B4)))
        assert "B4" in problem and "+80 ms" in problem

    def test_an_onset_30_ms_early_is_within_tolerance(self):
        assert round_trip.compare(PHRASE, frames((0.0, 0.57, A4), (0.57, 1.2, B4))) == []

    def test_a_missing_note_is_reported(self):
        [problem] = round_trip.compare(PHRASE, frames((0.0, 0.6, A4)))
        assert "B4" in problem and "not detected" in problem

    def test_a_wrong_note_is_reported_as_missing(self):
        [problem] = round_trip.compare(PHRASE, frames((0.0, 0.6, A4), (0.6, 1.2, 523.25)))
        assert "B4" in problem and "not detected" in problem

    def test_the_settling_frames_after_the_onset_do_not_count_for_pitch(self):
        # Two frames 40 cents off right at the onset, then steady: the attack is not the pitch.
        attack = B4 * 2 ** (40 / 1200)
        detected = frames((0.0, 0.6, A4), (0.6, 0.6 + 2 * HOP, attack), (0.6 + 2 * HOP, 1.2, B4))
        assert round_trip.compare(PHRASE, detected) == []


# ---------------------------------------------------------------------------
# The round trip itself
# ---------------------------------------------------------------------------

PARTS = ["P1", "P2", "P3", "P4"]


@pytest.fixture(scope="module")
def render(tmp_path_factory):
    """Render a part with synth-mcp (once per part and timbre); skip without synth-mcp."""
    reason = synth_bridge.unavailable_reason()
    if reason:
        if os.environ.get("PITCH_ROUND_TRIP_REQUIRED"):
            pytest.fail(f"PITCH_ROUND_TRIP_REQUIRED is set but {reason}")
        pytest.skip(reason)
    out_dir = tmp_path_factory.mktemp("round_trip")
    cache: dict[tuple[str, str], Path] = {}

    def _render(part: str, timbre: str = "score") -> Path:
        if (part, timbre) not in cache:
            cache[part, timbre] = synth_bridge.render_part(
                SCORE, part, out_dir / f"{part}-{timbre}.wav",
                soundfont=os.environ["SYNTH_SOUNDFONT_PATH"], timbre=timbre,
            )
        return cache[part, timbre]

    return _render


@pytest.mark.integration
class TestSynthToPitch:
    @pytest.mark.parametrize("part", PARTS)
    def test_every_note_has_the_scores_pitch_and_onset(self, render, part):
        wav = render(part)
        _, notes = extract_part_notes(SCORE.read_text(), part)
        assert round_trip.compare(notes, detect_pitches(str(wav))) == []

    @pytest.mark.parametrize("part", PARTS)
    def test_analysis_grades_the_rendition_on_pitch(self, render, part):
        result = analyze_recording(str(render(part)), SCORE.read_text(), part)
        assert [n["status"] for n in result["note_accuracy"]] == ["on_pitch"] * len(
            result["note_accuracy"]
        ), result["note_accuracy"]

    @pytest.mark.parametrize("part", PARTS)
    def test_choir_timbre_grades_on_pitch(self, render, part):
        # Choir Aahs is nearer a voice. Its slow attack moves pitch onsets 50-190 ms late (the new
        # note only wins once the old one has faded), so only the grade is checked here.
        result = analyze_recording(str(render(part, "choir")), SCORE.read_text(), part)
        assert result["accuracy_histogram"]["on_pitch"] == len(result["note_accuracy"]), result[
            "note_accuracy"
        ]
