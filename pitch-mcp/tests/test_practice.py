"""Practice a passage: `measures` (UX Wave 3, B2) and `start_practice` (C19); plan §3.3, §4.

`measures` cuts the score to printed bars with the core's `select_measures` before the notes are
extracted, so a session's timeline starts at the first selected bar and reported measures keep
their printed numbers. `start_practice` is `load_score` + `start_monitoring` in one call. The
microphone is never opened: `sounddevice` is replaced by a fake module whose `InputStream`
records what the session does with it.
"""

import json
import sys
import types

import pytest
from sheet_music_mcp_core.annotations import SESSION_STATE
from sheet_music_mcp_core.references import exactly_one

from pitch_mcp import engine
from pitch_mcp.engine import (
    ProcessingError,
    SessionRegistry,
    analyze_recording,
    get_position,
    list_sessions,
    load_score,
    start_monitoring,
    start_practice,
    stop_monitoring,
)
from pitch_mcp.server import call_tool, list_tools
from pitch_mcp.utils import note_name_to_hz

from .test_engine import MINIMAL_MUSICXML

STEPS = "CDEFGA"


def _six_bars(parts=(("P1", "Soprano", 5), ("P2", "Alto", 4)), *, bpm=90):
    """Six 4/4 bars per part, one whole note each (C D E F G A), tempo set once in bar 1."""
    part_list = "".join(f'<score-part id="{pid}"><part-name>{name}</part-name></score-part>' for pid, name, _ in parts)
    body = ""
    for pid, _, octave in parts:
        bars = ""
        for number, step in enumerate(STEPS, start=1):
            head = ""
            if number == 1:
                head = (
                    "<attributes><divisions>4</divisions><key><fifths>0</fifths></key>"
                    "<time><beats>4</beats><beat-type>4</beat-type></time>"
                    "<clef><sign>G</sign><line>2</line></clef></attributes>"
                    '<direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit>'
                    f"<per-minute>{bpm}</per-minute></metronome></direction-type></direction>"
                )
            bars += (
                f'<measure number="{number}">{head}<note><pitch><step>{step}</step><octave>{octave}</octave>'
                "</pitch><duration>16</duration><type>whole</type></note></measure>"
            )
        body += f'<part id="{pid}">{bars}</part>'
    return (
        '<?xml version="1.0" encoding="UTF-8"?><score-partwise version="3.1">'
        f"<part-list>{part_list}</part-list>{body}</score-partwise>"
    )


SIX_BARS = _six_bars()


class FakeInputStream:
    """Stands in for sounddevice.InputStream; never touches audio hardware."""

    instances: list = []
    fail_on = None  # "open" or "start" makes that step raise, like a missing microphone

    def __init__(self, **kwargs):
        if FakeInputStream.fail_on == "open":
            raise RuntimeError("no input device")
        self.kwargs = kwargs
        self.started = self.stopped = self.closed = False
        FakeInputStream.instances.append(self)

    def start(self):
        if FakeInputStream.fail_on == "start":
            raise RuntimeError("device busy")
        self.started = True

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


@pytest.fixture
def mic(monkeypatch):
    """A fake `sounddevice` module, and the engine on a fresh registry with the reaper off."""
    FakeInputStream.instances = []
    FakeInputStream.fail_on = None
    monkeypatch.setitem(sys.modules, "sounddevice", types.SimpleNamespace(InputStream=FakeInputStream))
    monkeypatch.setattr(engine, "_registry", SessionRegistry(idle_minutes=10))
    monkeypatch.setattr(engine, "_ensure_reaper", lambda: None)
    return FakeInputStream


def _payload(result):
    return json.loads(result[0].text)


# --- B2: measures on load_score and analyze_recording ----------------------------------------


class TestLoadScoreMeasures:
    def test_cut_session_counts_only_the_selected_bars(self, mic):
        result = load_score(SIX_BARS, "Soprano", measures=[3, 4])
        session = engine._registry.get(result["session_id"])

        assert result["measure_count"] == 2
        assert session.note_sequence[0]["measure"] == 3
        assert [n["measure"] for n in session.note_sequence] == [3, 4]
        assert [n["note_name"] for n in session.note_sequence] == ["E5", "F5"]

    def test_timeline_starts_at_the_first_selected_bar_at_the_score_tempo(self, mic):
        result = load_score(SIX_BARS, "Soprano", measures=[3, 4])
        session = engine._registry.get(result["session_id"])

        assert session.note_sequence[0]["start_sec"] == 0.0
        # Two 4/4 bars at the 90 BPM set in bar 1, carried into bar 3.
        assert result["duration_seconds"] == pytest.approx(2 * 4 * 60 / 90, abs=0.01)

    def test_position_before_singing_is_the_first_selected_note(self, mic):
        sid = load_score(SIX_BARS, "Alto", measures=[5, 6])["session_id"]

        position = get_position(sid)

        assert position["measure"] == 5
        assert position["beat"] == 1.0
        assert position["expected_note"] == "G4"

    def test_whole_score_is_unchanged_without_measures(self, mic):
        assert load_score(SIX_BARS, "Soprano")["measure_count"] == 6
        assert load_score(SIX_BARS, "Soprano", measures=None)["measure_count"] == 6

    @pytest.mark.parametrize("measures", [[5, 9], [0, 2]])
    def test_range_outside_the_score_is_invalid_with_hint(self, mic, measures):
        with pytest.raises(ProcessingError) as exc:
            load_score(SIX_BARS, "Soprano", measures=measures)

        assert exc.value.error_code == "INVALID_PARAMETER"
        assert "1–6" in exc.value.hint
        assert list_sessions()["sessions"] == []

    def test_reversed_range_names_the_score_range(self, mic):
        with pytest.raises(ProcessingError) as exc:
            load_score(SIX_BARS, "Soprano", measures=[4, 3])

        assert exc.value.error_code == "INVALID_PARAMETER"
        assert exc.value.hint == "This score has measures 1–6."

    @pytest.mark.parametrize("measures", [[4, 3], [3], ["3", "4"]])
    def test_malformed_range_is_invalid(self, mic, measures):
        with pytest.raises(ProcessingError) as exc:
            load_score(SIX_BARS, "Soprano", measures=measures)

        assert exc.value.error_code == "INVALID_PARAMETER"

    async def test_tool_passes_measures(self, mic):
        payload = _payload(await call_tool("load_score", {"musicxml": SIX_BARS, "part": "S", "measures": [2, 4]}))

        assert payload["measure_count"] == 3
        assert engine._registry.get(payload["session_id"]).note_sequence[0]["measure"] == 2

    async def test_tool_reports_an_out_of_range_error_with_hint(self, mic):
        payload = _payload(await call_tool("load_score", {"musicxml": SIX_BARS, "part": "S", "measures": [7, 8]}))

        assert payload["error_code"] == "INVALID_PARAMETER"
        assert "1–6" in payload["hint"]


class TestAnalyzeRecordingMeasures:
    @pytest.fixture
    def sung_bars_3_4(self, monkeypatch, tmp_path):
        """A take of bars 3-4 (E5, F5 at 90 BPM) with the pitch detector faked."""
        audio = tmp_path / "take.wav"
        audio.write_bytes(b"RIFF")
        bar = 4 * 60 / 90
        frames = [
            (start + t / 20, note_name_to_hz(name), 0.9)
            for start, name in ((0.0, "E5"), (bar, "F5"))
            for t in range(1, int(bar * 20))
        ]
        monkeypatch.setattr("pitch_mcp.pitch_detector.detect_pitches", lambda path: frames)
        return str(audio)

    def test_reports_only_the_selected_measures(self, sung_bars_3_4):
        result = analyze_recording(sung_bars_3_4, SIX_BARS, "Soprano", measures=[3, 4])

        assert [n["measure"] for n in result["note_accuracy"]] == [3, 4]
        assert [n["expected"] for n in result["note_accuracy"]] == ["E5", "F5"]
        assert result["measures_covered"] == 2
        assert result["accuracy_histogram"]["on_pitch"] == 2

    def test_range_outside_the_score_is_invalid(self, sung_bars_3_4):
        with pytest.raises(ProcessingError) as exc:
            analyze_recording(sung_bars_3_4, SIX_BARS, "Soprano", measures=[6, 7])

        assert exc.value.error_code == "INVALID_PARAMETER"

    async def test_tool_passes_measures(self, sung_bars_3_4):
        payload = _payload(
            await call_tool(
                "analyze_recording",
                {"audio_path": sung_bars_3_4, "musicxml": SIX_BARS, "part": "Soprano", "measures": [3, 4]},
            )
        )

        assert [n["measure"] for n in payload["note_accuracy"]] == [3, 4]


class TestMeasuresSchema:
    @pytest.mark.parametrize("tool_name", ["load_score", "analyze_recording", "start_practice"])
    async def test_measures_property(self, tool_name):
        schema = next(t for t in await list_tools() if t.name == tool_name).input_schema

        assert schema["properties"]["measures"]["type"] == "array"
        assert schema["properties"]["measures"]["minItems"] == 2
        assert "measures" not in schema.get("required", [])

    async def test_capabilities_list_measures(self):
        payload = _payload(await call_tool("list_capabilities", {}))

        assert "measures" in payload["input_parameters"]
        assert "start_practice" in payload["tools"]


# --- C19: start_practice ---------------------------------------------------------------------


class TestStartPracticeEngine:
    def test_returns_load_score_and_start_monitoring_fields(self, mic):
        loaded = load_score(SIX_BARS, "Alto", measures=[2, 3])
        started = start_monitoring(loaded["session_id"])
        stop_monitoring(loaded["session_id"])

        result = start_practice(SIX_BARS, "Alto", measures=[2, 3])

        assert set(result) == set(loaded) | set(started)
        assert {k: v for k, v in result.items() if k != "session_id"} == {
            **{k: v for k, v in loaded.items() if k != "session_id"},
            "status": "started",
        }
        stop_monitoring(result["session_id"])

    def test_session_is_monitoring(self, mic):
        sid = start_practice(SIX_BARS, "Soprano")["session_id"]

        [row] = list_sessions()["sessions"]
        assert row["session_id"] == sid
        assert row["state"] == "monitoring"
        assert mic.instances[-1].started

        stop_monitoring(sid)
        assert mic.instances[-1].closed
        assert list_sessions()["sessions"] == []

    def test_tempo_reaches_the_session(self, mic):
        sid = start_practice(SIX_BARS, "Soprano", tempo_bpm=60)["session_id"]

        assert engine._registry.get(sid)._tempo_bpm == 60
        stop_monitoring(sid)

    @pytest.mark.parametrize("fail_on", ["open", "start"])
    def test_mic_failure_leaves_no_session(self, mic, fail_on):
        mic.fail_on = fail_on

        with pytest.raises(ProcessingError) as exc:
            start_practice(SIX_BARS, "Soprano")

        assert exc.value.error_code == "PROCESSING_FAILED"
        assert list_sessions()["sessions"] == []

    def test_missing_sounddevice_leaves_no_session(self, mic, monkeypatch):
        monkeypatch.setitem(sys.modules, "sounddevice", None)  # import raises ImportError

        with pytest.raises(ProcessingError) as exc:
            start_practice(SIX_BARS, "Soprano")

        assert exc.value.error_code == "PROCESSING_FAILED"
        assert list_sessions()["sessions"] == []

    def test_bad_part_opens_nothing(self, mic):
        with pytest.raises(ProcessingError) as exc:
            start_practice(SIX_BARS, "Tenor")

        assert exc.value.error_code == "INVALID_PARAMETER"
        assert mic.instances == []
        assert list_sessions()["sessions"] == []


class TestStartPracticeTool:
    async def test_schema(self):
        tool = next(t for t in await list_tools() if t.name == "start_practice")
        schema = tool.input_schema

        assert tool.title == "Start practice"
        assert tool.annotations.model_dump(exclude_none=True) == dict(SESSION_STATE)
        assert schema["required"] == ["part"]
        assert "part_id" not in schema["properties"]
        assert schema["oneOf"] == exactly_one("musicxml", "musicxml_path")["oneOf"]
        assert schema["properties"]["tempo_bpm"]["type"] == "integer"

    async def test_returns_a_monitoring_session(self, mic):
        payload = _payload(
            await call_tool("start_practice", {"musicxml": SIX_BARS, "part": "Alto", "measures": [3, 4], "tempo_bpm": 80})
        )

        assert payload["status"] == "started"
        assert payload["part_id"] == "P2"
        assert payload["measure_count"] == 2
        assert list_sessions()["sessions"][0]["state"] == "monitoring"
        assert engine._registry.get(payload["session_id"])._tempo_bpm == 80

        stop = _payload(await call_tool("stop_monitoring", {"session_id": payload["session_id"]}))
        assert stop["summary"]["highlights"] == []

    async def test_mic_failure_is_an_error_and_leaves_no_session(self, mic):
        mic.fail_on = "open"

        payload = _payload(await call_tool("start_practice", {"musicxml": SIX_BARS, "part": "Alto"}))

        assert payload["error_code"] == "PROCESSING_FAILED"
        assert list_sessions()["sessions"] == []

    async def test_through_the_protocol(self, mic):
        from mcp import Client

        from pitch_mcp.server import app

        async with Client(app) as client:
            ok = await client.call_tool("start_practice", {"musicxml": SIX_BARS, "part": "Alto", "measures": [3, 4]})
            missing_part = await client.call_tool("start_practice", {"musicxml": SIX_BARS})
            bad_range = await client.call_tool("start_practice", {"musicxml": SIX_BARS, "part": "Alto", "measures": [3]})

        assert not ok.is_error
        assert json.loads(ok.content[0].text)["measure_count"] == 2
        assert missing_part.is_error
        assert bad_range.is_error
        assert len(list_sessions()["sessions"]) == 1
        stop_monitoring(json.loads(ok.content[0].text)["session_id"])

    async def test_inline_score_is_validated(self, mic):
        payload = _payload(await call_tool("start_practice", {"musicxml": "<html/>", "part": "Alto"}))

        assert payload["error_code"] == "INVALID_INPUT"
        assert mic.instances == []

    async def test_score_by_path(self, mic, tmp_path, monkeypatch):
        monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
        monkeypatch.delenv("SHEET_MUSIC_INPUT_ROOTS", raising=False)
        (tmp_path / "six.musicxml").write_text(SIX_BARS, encoding="utf-8")

        payload = _payload(
            await call_tool("start_practice", {"musicxml_path": str(tmp_path / "six.musicxml"), "part": "Soprano"})
        )

        assert payload["status"] == "started"
        assert payload["measure_count"] == 6
        stop_monitoring(payload["session_id"])


def test_existing_load_score_default_position_is_unchanged():
    """A score whose first note is in bar 1 on beat 1 still starts at measure 1, beat 1."""
    sid = load_score(MINIMAL_MUSICXML, "Soprano")["session_id"]
    try:
        position = get_position(sid)
        assert (position["measure"], position["beat"]) == (1, 1.0)
    finally:
        stop_monitoring(sid)


# --- Tempo given only as <sound tempo> (what select_measures carries into a cut score) -------


class TestSoundTempo:
    SOUND_ONLY = _six_bars().replace(
        '<direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit>'
        "<per-minute>90</per-minute></metronome></direction-type></direction>",
        '<sound tempo="84"/>',
    )

    def test_sound_tempo_sets_the_nominal_tempo_and_map(self):
        import music21

        from pitch_mcp.utils import _build_metronome_map, extract_nominal_tempo_bpm

        assert '<sound tempo="84"/>' in self.SOUND_ONLY and "metronome" not in self.SOUND_ONLY
        assert extract_nominal_tempo_bpm(self.SOUND_ONLY) == pytest.approx(84.0)
        score = music21.converter.parseData(self.SOUND_ONLY, format="musicxml")
        assert _build_metronome_map(score)[0][1] == pytest.approx(60 / 84)

    def test_sound_tempo_times_the_notes(self, mic):
        result = load_score(self.SOUND_ONLY, "Soprano")

        assert result["duration_seconds"] == pytest.approx(6 * 4 * 60 / 84, abs=0.01)

    def test_cut_keeps_a_tempo_set_in_bar_1(self, mic):
        score = _six_bars(bpm=84)
        sid = load_score(score, "Soprano", measures=[3, 4])["session_id"]

        assert engine._registry.get(sid)._nominal_bpm == pytest.approx(84.0)
        assert engine._registry.get(sid).duration_seconds == pytest.approx(2 * 4 * 60 / 84, abs=0.01)
