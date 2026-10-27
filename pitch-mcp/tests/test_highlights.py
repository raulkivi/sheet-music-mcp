"""Highlights: runs of flat or sharp notes in plain words (UX Wave 3, C22; plan §3.3, W3-7).

``aligner.highlights`` groups per-note results (``analyze_recording``) or per-frame history
(``stop_monitoring``) into notes, finds runs of at least two consecutive flat or sharp notes and
names the worst three. ``summarize`` carries them, so both tools report them.
"""

import json

from pitch_mcp.aligner import highlights, summarize
from pitch_mcp.engine import ScoreSession, analyze_recording, load_score
from pitch_mcp.utils import note_name_to_hz

from .test_engine import FOUR_NOTE_MUSICXML


def _status(cents):
    if cents is None:
        return "no_signal"
    if abs(cents) <= 25:
        return "on_pitch"
    return "sharp" if cents > 0 else "flat"


def note(measure, beat, cents, expected="E5"):
    """One analyze_recording note result."""
    return {
        "measure": measure,
        "beat": beat,
        "expected": expected,
        "expected_hz": 659.26,
        "sung_hz": None if cents is None else 650.0,
        "accuracy_cents": cents,
        "status": _status(cents),
    }


def frame(measure, beat, cents, expected="E5"):
    """One live history entry (one per detected frame)."""
    return {
        "measure": measure,
        "beat": beat,
        "expected_note": expected,
        "sung_pitch_hz": 650.0,
        "accuracy_cents": cents,
        "status": _status(cents),
    }


# Four flat E5s in m.12-14 averaging -35 cents.
FLAT_E5_RUN = [note(12, 1.0, -30), note(12, 3.0, -40), note(13, 1.0, -35), note(14, 1.0, -35)]


class TestRuns:
    def test_four_flat_notes_make_one_highlight(self):
        assert highlights(FLAT_E5_RUN) == [
            {
                "direction": "flat",
                "measures": [12, 14],
                "notes": 4,
                "avg_cents": -35,
                "text": "flat on E5 in m.12–14 (-35 cents avg)",
            }
        ]

    def test_different_pitches_name_the_note_count(self):
        results = [
            note(12, 1.0, -30, "E5"),
            note(12, 3.0, -40, "D5"),
            note(13, 1.0, -35, "C5"),
            note(14, 1.0, -35, "E5"),
        ]

        assert highlights(results)[0]["text"] == "flat in m.12–14 (-35 cents avg over 4 notes)"

    def test_one_measure_is_named_once(self):
        [highlight] = highlights([note(12, 1.0, -30), note(12, 3.0, -40)])

        assert highlight["measures"] == [12, 12]
        assert highlight["text"] == "flat on E5 in m.12 (-35 cents avg)"

    def test_sharp_run(self):
        [highlight] = highlights([note(3, 1.0, 30, "A4"), note(3, 2.0, 40, "A4")])

        assert highlight["direction"] == "sharp"
        assert highlight["avg_cents"] == 35
        assert highlight["text"] == "sharp on A4 in m.3 (+35 cents avg)"

    def test_a_single_flat_note_is_not_a_highlight(self):
        assert highlights([note(1, 1.0, 10), note(2, 1.0, -40), note(3, 1.0, 5)]) == []

    def test_no_signal_splits_a_run(self):
        results = [note(1, 1.0, -40), note(2, 1.0, -40), note(3, 1.0, None), note(4, 1.0, -40)]

        [highlight] = highlights(results)

        assert highlight["measures"] == [1, 2]
        assert highlight["notes"] == 2

    def test_on_pitch_splits_a_run(self):
        results = [note(1, 1.0, -40), note(2, 1.0, 0), note(3, 1.0, -40)]

        assert highlights(results) == []

    def test_flat_then_sharp_are_separate_runs(self):
        results = [note(1, 1.0, -40), note(2, 1.0, 40)]

        assert highlights(results) == []

    def test_threshold_is_exclusive(self):
        assert highlights([note(1, 1.0, -25), note(2, 1.0, -25)]) == []
        assert len(highlights([note(1, 1.0, -26), note(2, 1.0, -26)])) == 1

    def test_four_runs_give_the_three_ranked_highest(self):
        results = [
            note(1, 1.0, -30), note(2, 1.0, -30),  # 2 x 30 = 60
            note(3, 1.0, 0),
            note(4, 1.0, 50), note(5, 1.0, 50), note(6, 1.0, 50),  # 3 x 50 = 150
            note(7, 1.0, 0),
            note(8, 1.0, -40), note(9, 1.0, -40),  # 2 x 40 = 80
            note(10, 1.0, 0),
            note(11, 1.0, -100), note(12, 1.0, -100),  # 2 x 100 = 200
        ]

        ranked = highlights(results)

        assert [h["measures"] for h in ranked] == [[11, 12], [4, 6], [8, 9]]

    def test_limit_and_min_run_and_threshold_are_parameters(self):
        results = [note(1, 1.0, -20), note(2, 1.0, 0), note(3, 1.0, -40), note(4, 1.0, -40)]

        assert len(highlights(results, threshold=10, min_run=1)) == 2
        assert len(highlights(results, threshold=10, min_run=1, limit=1)) == 1

    def test_empty(self):
        assert highlights([]) == []


class TestFrameHistory:
    def test_frames_give_the_same_highlight_as_notes(self):
        frames = [
            *(frame(12, 1.0, c) for c in (-28, -30, -33)),  # median -30
            *(frame(12, 3.0, c) for c in (-40, -45, -38, -40)),  # median -40
            frame(13, 1.0, -35),
            *(frame(14, 1.0, c) for c in (-35, -35)),
        ]

        assert highlights(frames) == highlights(FLAT_E5_RUN)

    def test_same_note_with_another_expected_pitch_is_another_note(self):
        frames = [frame(5, 1.0, -40, "E5"), frame(5, 1.0, -40, "F5")]

        [highlight] = highlights(frames)

        assert highlight["notes"] == 2
        assert highlight["text"] == "flat in m.5 (-40 cents avg over 2 notes)"


class TestSummaries:
    def test_summarize_carries_highlights(self):
        assert summarize(FLAT_E5_RUN)["highlights"] == highlights(FLAT_E5_RUN)

    def test_empty_summary_has_no_highlights(self):
        assert summarize([])["highlights"] == []

    def test_stop_summary_without_singing_has_empty_highlights(self):
        session = ScoreSession(FOUR_NOTE_MUSICXML, "Soprano")

        assert session.stop()["summary"]["highlights"] == []

    def test_stop_summary_names_a_flat_run(self):
        session = ScoreSession(FOUR_NOTE_MUSICXML, "Soprano")
        flat = 2 ** (-40 / 1200)
        for elapsed, name in ((0.1, "C4"), (0.2, "C4"), (0.6, "E4"), (0.7, "E4")):
            session._process_pitch_frame(note_name_to_hz(name) * flat, 0.9, elapsed)

        [highlight] = session.stop()["summary"]["highlights"]

        assert highlight["direction"] == "flat"
        assert highlight["notes"] == 2
        assert highlight["text"] == "flat in m.1 (-40 cents avg over 2 notes)"

    async def test_stop_monitoring_tool_returns_highlights(self):
        from pitch_mcp.server import call_tool

        sid = load_score(FOUR_NOTE_MUSICXML, "Soprano")["session_id"]

        payload = json.loads((await call_tool("stop_monitoring", {"session_id": sid}))[0].text)

        assert payload["summary"]["highlights"] == []

    def test_analyze_recording_returns_highlights(self, monkeypatch, tmp_path):
        audio = tmp_path / "take.wav"
        audio.write_bytes(b"RIFF")
        flat = 2 ** (-40 / 1200)
        # C4 E4 G4 C5 at 120 BPM, one quarter (0.5 s) each, all sung 40 cents flat.
        frames = [
            (t / 100, note_name_to_hz(name) * flat, 0.9)
            for start, name in ((0, "C4"), (50, "E4"), (100, "G4"), (150, "C5"))
            for t in range(start + 5, start + 45, 5)
        ]
        monkeypatch.setattr("pitch_mcp.pitch_detector.detect_pitches", lambda path: frames)

        result = analyze_recording(str(audio), FOUR_NOTE_MUSICXML, "Soprano")

        assert result["highlights"] == [
            {
                "direction": "flat",
                "measures": [1, 1],
                "notes": 4,
                "avg_cents": -40,
                "text": "flat in m.1 (-40 cents avg over 4 notes)",
            }
        ]
