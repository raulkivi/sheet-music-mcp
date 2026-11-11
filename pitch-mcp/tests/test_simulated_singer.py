"""Grading with a simulated singer (S4 in docs/research/ui-and-sound-testing-plan.md).

The reference phrase is rendered as a harmonic tone with one known fault injected, then run
through ``analyze_recording``. Each fault is its own test and asserts what the grading reports for
the faulty note. Deterministic (fixed seed), no hardware.
"""

from pathlib import Path

import pytest

from pitch_mcp.engine import analyze_recording

from . import simulated_singer as singer

FIXTURE_MUSICXML = Path(__file__).parent / "fixtures" / "reference.musicxml"
TOLERANCE = 25  # cents; aligner._classify calls |cents| <= 25 "on_pitch"
SLIPPED = 5  # index of "F4" in measure 2 beat 2 (the fault target in most cases)
VIBRATO = 8  # a C4 quarter note (0.67 s, about 3.7 vibrato cycles) between different pitches
HELD = 19  # the final half note (about 1.33 s), long enough for vibrato and a breath gap


@pytest.fixture(scope="module")
def phrase():
    return singer.reference_notes(FIXTURE_MUSICXML.read_text())


def grade(tmp_path, audio):
    path = tmp_path / "take.wav"
    singer.write_wav(path, audio)
    return analyze_recording(str(path), FIXTURE_MUSICXML.read_text(), "Soprano")


def others_on_pitch(result, faulty):
    return [
        n for i, n in enumerate(result["note_accuracy"]) if i not in faulty and n["status"] != "on_pitch"
    ]


class TestSimulatedSinger:
    def test_the_phrase_has_the_notes_the_cases_index(self, phrase):
        assert len(phrase) == 20
        assert phrase[SLIPPED]["note_name"] == "F4"
        assert phrase[HELD]["end_sec"] - phrase[HELD]["start_sec"] > 1.0

    def test_render_is_deterministic(self, phrase):
        a = singer.add_noise(singer.render(singer.sung_notes(phrase)), snr_db=20, seed=1)
        b = singer.add_noise(singer.render(singer.sung_notes(phrase)), snr_db=20, seed=1)
        assert (a == b).all()

    def test_noise_has_the_requested_snr(self, phrase):
        clean = singer.render(singer.sung_notes(phrase))
        noisy = singer.add_noise(clean, snr_db=20, seed=1)
        snr = 10 * __import__("numpy").log10((clean**2).mean() / ((noisy - clean) ** 2).mean())
        assert snr == pytest.approx(20, abs=0.1)

    def test_clean_take_grades_accurate(self, tmp_path, phrase):
        result = grade(tmp_path, singer.render(singer.sung_notes(phrase)))
        assert result["accuracy_histogram"] == {"on_pitch": 20, "sharp": 0, "flat": 0, "no_signal": 0}
        assert result["avg_accuracy_cents"] <= 10
        assert result["highlights"] == []

    def test_25_cents_sharp_is_reported_as_25_cents(self, tmp_path, phrase):
        notes = singer.sharpen(singer.sung_notes(phrase), SLIPPED, cents=25)
        result = grade(tmp_path, singer.render(notes))
        # 25 cents sits on the documented on_pitch edge (|cents| <= 25), so the deviation is the
        # contract, not the label.
        assert result["note_accuracy"][SLIPPED]["accuracy_cents"] == pytest.approx(25, abs=6)
        assert others_on_pitch(result, {SLIPPED}) == []

    def test_40_cents_sharp_is_graded_sharp(self, tmp_path, phrase):
        notes = singer.sharpen(singer.sung_notes(phrase), SLIPPED, cents=40)
        result = grade(tmp_path, singer.render(notes))
        note = result["note_accuracy"][SLIPPED]
        assert note["status"] == "sharp"
        assert note["accuracy_cents"] == pytest.approx(40, abs=6)
        assert others_on_pitch(result, {SLIPPED}) == []

    def test_two_flat_notes_in_a_row_become_a_highlight(self, tmp_path, phrase):
        notes = singer.sung_notes(phrase)
        notes = singer.sharpen(singer.sharpen(notes, 4, cents=-40), 5, cents=-40)
        result = grade(tmp_path, singer.render(notes))
        assert len(result["highlights"]) == 1
        found = result["highlights"][0]
        assert (found["direction"], found["measures"], found["notes"]) == ("flat", [2, 2], 2)
        assert found["avg_cents"] == pytest.approx(-40, abs=6)

    def test_a_note_150_ms_late_is_still_matched_on_pitch(self, tmp_path, phrase):
        # Grading is by pitch: DTW absorbs timing slips within the plausibility margin
        # (aligner.align: max(0.15 s, 75% of the note)). No timing metric exists to assert.
        notes = singer.delay(singer.sung_notes(phrase), SLIPPED, seconds=0.150)
        result = grade(tmp_path, singer.render(notes))
        assert result["note_accuracy"][SLIPPED]["status"] == "on_pitch"
        assert abs(result["note_accuracy"][SLIPPED]["accuracy_cents"]) <= TOLERANCE
        assert others_on_pitch(result, set()) == []

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT: an octave slip is not graded. The detector reports the up note at half "
        "its pitch, and for both directions the DTW aligner hands the slipped note a neighbour's "
        "frames, so it grades on_pitch (up) or against the wrong pitch (down). See HANDOVER.md.",
    )
    @pytest.mark.parametrize("octaves, direction", [(1, "sharp"), (-1, "flat")])
    def test_an_octave_slip_is_graded_by_about_1200_cents(self, tmp_path, phrase, octaves, direction):
        notes = singer.octave_slip(singer.sung_notes(phrase), SLIPPED, octaves=octaves)
        result = grade(tmp_path, singer.render(notes))
        note = result["note_accuracy"][SLIPPED]
        assert note["status"] == direction
        assert note["accuracy_cents"] == pytest.approx(1200 * octaves, abs=30)
        assert others_on_pitch(result, {SLIPPED}) == []

    def test_vibrato_grades_on_the_centre_pitch(self, tmp_path, phrase):
        notes = singer.vibrato(singer.sung_notes(phrase), VIBRATO, rate_hz=5.5, depth_cents=50)
        result = grade(tmp_path, singer.render(notes))
        note = result["note_accuracy"][VIBRATO]
        assert note["status"] == "on_pitch"
        assert abs(note["accuracy_cents"]) <= TOLERANCE
        assert others_on_pitch(result, set()) == []

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT: the final C4 repeats the previous note's pitch, DTW gives it a single "
        "frame, and that one vibrato extreme (+50 cents) is graded sharp. See HANDOVER.md.",
    )
    def test_vibrato_on_the_held_final_note_grades_on_its_centre_pitch(self, tmp_path, phrase):
        notes = singer.vibrato(singer.sung_notes(phrase), HELD, rate_hz=5.5, depth_cents=50)
        result = grade(tmp_path, singer.render(notes))
        note = result["note_accuracy"][HELD]
        assert note["status"] == "on_pitch"
        assert abs(note["accuracy_cents"]) <= TOLERANCE
        assert others_on_pitch(result, set()) == []

    def test_white_noise_at_20_db_snr_still_grades_accurate(self, tmp_path, phrase):
        audio = singer.add_noise(singer.render(singer.sung_notes(phrase)), snr_db=20, seed=7)
        result = grade(tmp_path, audio)
        assert result["accuracy_histogram"]["on_pitch"] == 20
        assert result["highlights"] == []

    def test_a_breath_gap_inside_a_note_does_not_lose_the_note(self, tmp_path, phrase):
        held = phrase[HELD]
        middle = (held["start_sec"] + held["end_sec"]) / 2
        audio = singer.breath_gap(singer.render(singer.sung_notes(phrase)), middle, middle + 0.15)
        result = grade(tmp_path, audio)
        assert result["note_accuracy"][HELD]["status"] == "on_pitch"
        assert result["accuracy_histogram"]["no_signal"] == 0
        assert others_on_pitch(result, set()) == []
