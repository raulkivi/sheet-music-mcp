"""Unit tests for pitch_mcp.aligner."""

import pytest

from pitch_mcp.aligner import align, summarize, _hz_to_cents_deviation, _classify


class TestHzToCentsDeviation:
    def test_same_pitch(self):
        assert _hz_to_cents_deviation(440.0, 440.0) == 0

    def test_one_semitone_sharp(self):
        a4_sharp = 440.0 * (2 ** (1 / 12))  # A#4
        assert abs(_hz_to_cents_deviation(a4_sharp, 440.0) - 100) <= 1

    def test_half_semitone_flat(self):
        hz = 440.0 * (2 ** (-50 / 1200))  # 50 cents flat
        assert abs(_hz_to_cents_deviation(hz, 440.0) - (-50)) <= 1

    def test_zero_expected_returns_zero(self):
        assert _hz_to_cents_deviation(440.0, 0.0) == 0

    def test_zero_sung_returns_zero(self):
        assert _hz_to_cents_deviation(0.0, 440.0) == 0


class TestClassify:
    def test_on_pitch_zero(self):
        assert _classify(0) == "on_pitch"

    def test_on_pitch_borderline(self):
        assert _classify(25) == "on_pitch"
        assert _classify(-25) == "on_pitch"

    def test_sharp(self):
        assert _classify(26) == "sharp"

    def test_flat(self):
        assert _classify(-26) == "flat"


class TestAlign:
    def _make_note(self, note_name, midi, freq_hz, start_sec, end_sec, measure=1, beat=1.0):
        return {
            "note_name": note_name,
            "freq_hz": freq_hz,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "measure": measure,
            "beat": beat,
            "midi": midi,
        }

    def _make_detected(self, times, freq_hz):
        """Create detected pitch list with given times and constant freq."""
        return [(t, freq_hz, 0.9) for t in times]

    def test_empty_detected_returns_no_signal(self):
        notes = [self._make_note("A4", 69, 440.0, 0.0, 0.5)]
        result = align([], notes)
        assert result[0]["status"] == "no_signal"

    def test_empty_notes_returns_empty(self):
        detected = [(0.1, 440.0, 0.9)]
        result = align(detected, [])
        assert result == []

    def test_both_empty_returns_empty(self):
        assert align([], []) == []

    def test_on_pitch_detection(self):
        notes = [self._make_note("A4", 69, 440.0, 0.0, 0.5)]
        detected = self._make_detected([0.1, 0.2, 0.3, 0.4], 440.0)
        result = align(detected, notes)
        assert len(result) == 1
        assert result[0]["status"] == "on_pitch"
        assert result[0]["expected"] == "A4"
        assert result[0]["sung_hz"] is not None

    def test_sharp_detection(self):
        # Sing 50 cents sharp
        sharp_hz = 440.0 * (2 ** (50 / 1200))
        notes = [self._make_note("A4", 69, 440.0, 0.0, 0.5)]
        detected = self._make_detected([0.1, 0.2, 0.3, 0.4], sharp_hz)
        result = align(detected, notes)
        assert result[0]["status"] == "sharp"
        assert result[0]["accuracy_cents"] > 0

    def test_flat_detection(self):
        flat_hz = 440.0 * (2 ** (-50 / 1200))
        notes = [self._make_note("A4", 69, 440.0, 0.0, 0.5)]
        detected = self._make_detected([0.1, 0.2, 0.3, 0.4], flat_hz)
        result = align(detected, notes)
        assert result[0]["status"] == "flat"
        assert result[0]["accuracy_cents"] < 0

    def test_no_frames_in_window_gives_no_signal(self):
        # Note is at 0.0-0.5, detected frames are at 1.0+
        notes = [self._make_note("A4", 69, 440.0, 0.0, 0.5)]
        detected = [(1.0, 440.0, 0.9), (1.5, 440.0, 0.9)]
        result = align(detected, notes)
        assert result[0]["status"] == "no_signal"

    def test_multiple_notes(self):
        notes = [
            self._make_note("C4", 60, 261.63, 0.0, 0.5, measure=1, beat=1.0),
            self._make_note("E4", 64, 329.63, 0.5, 1.0, measure=1, beat=2.0),
            self._make_note("G4", 67, 392.0, 1.0, 1.5, measure=1, beat=3.0),
        ]
        detected = (
            [(t, 261.63, 0.9) for t in [0.1, 0.2, 0.3, 0.4]]
            + [(t, 329.63, 0.9) for t in [0.6, 0.7, 0.8, 0.9]]
            + [(t, 392.0, 0.9) for t in [1.1, 1.2, 1.3, 1.4]]
        )
        result = align(detected, notes)
        assert len(result) == 3
        assert all(r["status"] == "on_pitch" for r in result), [r["status"] for r in result]

    def test_result_structure(self):
        notes = [self._make_note("A4", 69, 440.0, 0.0, 0.5)]
        detected = self._make_detected([0.25], 440.0)
        result = align(detected, notes)
        r = result[0]
        assert "measure" in r
        assert "beat" in r
        assert "expected" in r
        assert "expected_hz" in r
        assert "sung_hz" in r
        assert "accuracy_cents" in r
        assert "status" in r

    def test_tempo_drift_does_not_misattribute_frames(self):
        """A singer running consistently behind the written tempo should still
        align correctly to each note by pitch — not bleed into the neighbor
        the way a fixed ±10% time window did (see docs/todo.md)."""
        notes = [
            self._make_note("C4", 60, 261.63, 0.0, 0.3, beat=1.0),
            self._make_note("E4", 64, 329.63, 0.3, 0.6, beat=2.0),
        ]
        # Singer starts ~0.25s late and stays that far behind for both notes.
        c4_times = [0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
        e4_times = [0.60, 0.65, 0.70, 0.75, 0.80]
        detected = (
            [(t, 261.63, 0.9) for t in c4_times]
            + [(t, 329.63, 0.9) for t in e4_times]
        )
        result = align(detected, notes)
        assert result[0]["status"] == "on_pitch"
        assert result[0]["sung_hz"] == pytest.approx(261.63, abs=0.5)
        assert result[1]["status"] == "on_pitch"
        assert result[1]["sung_hz"] == pytest.approx(329.63, abs=0.5)

    def test_note_singer_never_attempted_is_no_signal_among_others(self):
        """A note the singer skipped entirely (with a real pause around it)
        stays no_signal even when surrounded by correctly-sung notes — DTW
        forces full note coverage, so this depends on the temporal
        plausibility gate, not just an empty frame set."""
        notes = [
            self._make_note("C4", 60, 261.63, 0.0, 0.5, beat=1.0),
            self._make_note("E4", 64, 329.63, 0.5, 1.0, beat=2.0),
            self._make_note("G4", 67, 392.0, 2.0, 2.5, beat=3.0),
        ]
        # Middle note (E4) is skipped; singer pauses before resuming on G4.
        detected = (
            [(t, 261.63, 0.9) for t in [0.1, 0.2, 0.3, 0.4]]
            + [(t, 392.0, 0.9) for t in [2.1, 2.2, 2.3, 2.4]]
        )
        result = align(detected, notes)
        assert result[0]["status"] == "on_pitch"
        assert result[1]["status"] == "no_signal"
        assert result[1]["sung_hz"] is None
        assert result[2]["status"] == "on_pitch"

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT: DTW gives every frame after the score's end to the final note, and the "
        "plausibility gate tests the median time of those frames, so a release or room tail of "
        "more than 2.5x the note's length (median past end + 0.75 x length) makes a well-sung "
        "final note no_signal. "
        "See docs/todo.md (round trip, FluidSynth 2.4 reverb).",
    )
    def test_a_long_tail_after_the_final_note_still_grades_it(self):
        # Measured shape of the synth-mcp choir round trip on FluidSynth 2.4 defaults: the final
        # 1.25 s note (3.75-5.0 s) stays voiced at its pitch until 8.2 s, a 3.2 s reverb tail.
        hop = 512 / 44100
        notes = [
            self._make_note("E5", 76, 659.26, 0.0, 3.75, beat=1.0),
            self._make_note("F5", 77, 698.46, 3.75, 5.0, beat=3.0),
        ]
        detected = [(i * hop, 659.26, 0.9) for i in range(int(3.75 / hop))] + [
            (3.75 + i * hop, 698.46, 0.9) for i in range(int(4.45 / hop))
        ]
        result = align(detected, notes)
        assert [r["status"] for r in result] == ["on_pitch", "on_pitch"]


class TestSummarize:
    def _make_result(self, status, cents=None):
        return {
            "measure": 1, "beat": 1.0,
            "expected": "A4", "expected_hz": 440.0,
            "sung_hz": 440.0 if status != "no_signal" else None,
            "accuracy_cents": cents,
            "status": status,
        }

    def test_empty_results(self):
        s = summarize([])
        assert s["measures_covered"] == 0
        assert s["avg_accuracy_cents"] is None

    def test_all_on_pitch(self):
        results = [self._make_result("on_pitch", 5) for _ in range(4)]
        s = summarize(results)
        assert s["accuracy_histogram"]["on_pitch"] == 4
        assert s["avg_accuracy_cents"] == 5

    def test_mixed_results(self):
        results = [
            self._make_result("on_pitch", 10),
            self._make_result("sharp", 50),
            self._make_result("flat", -30),
            self._make_result("no_signal", None),
        ]
        s = summarize(results)
        assert s["accuracy_histogram"]["on_pitch"] == 1
        assert s["accuracy_histogram"]["sharp"] == 1
        assert s["accuracy_histogram"]["flat"] == 1
        assert s["accuracy_histogram"]["no_signal"] == 1
        # avg of abs(10), abs(50), abs(-30) = (10+50+30)/3 = 30
        assert s["avg_accuracy_cents"] == 30
