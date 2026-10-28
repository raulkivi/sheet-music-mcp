"""Browser-microphone mode (proposal §5.1 option B, AC-P4; §7 limits and privacy).

The Practice Coach captures 16 kHz mono PCM in the browser and pushes ~100 ms chunks with the
app-only `push_audio_chunk`; each push returns the latest position. A session takes pushed audio
once `start_monitoring` opened it with `source: "pushed"`; the server microphone is never touched.
"""

import asyncio
import base64
import builtins
import json

import jsonschema
import numpy as np
import pytest
from mcp import Client
from sheet_music_mcp_core.annotations import SESSION_STATE
from sheet_music_mcp_core.ui import is_app_only

from pitch_mcp import engine
from pitch_mcp.engine import (
    MAX_PUSHES_PER_SECOND,
    TRACKER_SAMPLE_RATE,
    AudioSource,
    ProcessingError,
    PushedChunkSource,
    SessionRegistry,
    get_position,
    list_sessions,
    load_score,
    max_chunk_bytes,
    push_audio_chunk,
    start_monitoring,
    stop_monitoring,
)
from pitch_mcp.presenter import POSITION_OUTPUT_SCHEMA
from pitch_mcp.server import app, call_tool_result, list_tools

from .test_practice import mic  # noqa: F401  (mic is a fixture)
from .test_session_timeout import FakeClock

COACH_URI = "ui://pitch/practice-coach"
RATE = 16000


def _score(*notes: tuple[str, int], bpm: int = 60) -> str:
    """One 4/4 bar per (step, octave), each a whole note; 4 s per bar at 60 BPM."""
    bars = ""
    for number, (step, octave) in enumerate(notes, start=1):
        head = ""
        if number == 1:
            head = (
                "<attributes><divisions>4</divisions><key><fifths>0</fifths></key>"
                "<time><beats>4</beats><beat-type>4</beat-type></time>"
                "<clef><sign>G</sign><line>2</line><clef-octave-change>-1</clef-octave-change></clef></attributes>"
                '<direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit>'
                f"<per-minute>{bpm}</per-minute></metronome></direction-type></direction>"
            )
        bars += (
            f'<measure number="{number}">{head}<note><pitch><step>{step}</step><octave>{octave}</octave>'
            "</pitch><duration>16</duration><type>whole</type></note></measure>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><score-partwise version="3.1">'
        '<part-list><score-part id="P1"><part-name>Tenor</part-name></score-part></part-list>'
        f'<part id="P1">{bars}</part></score-partwise>'
    )


A3_FIRST = _score(("A", 3), ("C", 4))


def pcm(freq: float, seconds: float, rate: int = RATE, amplitude: float = 0.5) -> bytes:
    """16-bit little-endian mono PCM of a sine (freq 0 = silence)."""
    t = np.arange(int(round(seconds * rate))) / rate
    samples = amplitude * np.sin(2 * np.pi * freq * t) if freq else np.zeros_like(t)
    return (samples * 32767).astype("<i2").tobytes()


def chunks(freq: float, seconds: float, rate: int = RATE, chunk_ms: int = 100) -> list[str]:
    """The tone as base64 chunks of ``chunk_ms``, as the coach's AudioWorklet sends them."""
    data = pcm(freq, seconds, rate)
    step = rate * chunk_ms // 1000 * 2
    return [base64.b64encode(data[i:i + step]).decode("ascii") for i in range(0, len(data), step)]


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def pushed(monkeypatch, clock):
    """The engine on a fresh registry (fake clock, no reaper); pushed sources share the clock."""
    registry = SessionRegistry(idle_minutes=10, clock=clock)
    monkeypatch.setattr(engine, "_registry", registry)
    monkeypatch.setattr(engine, "_ensure_reaper", lambda: None)
    monkeypatch.setattr(engine, "pushed_source", lambda: PushedChunkSource(clock=clock))
    return registry


def _open(score: str = A3_FIRST) -> str:
    sid = load_score(score, "Tenor")["session_id"]
    start_monitoring(sid, source="pushed")
    return sid


def _push_all(sid: str, encoded: list[str], rate: int = RATE) -> dict:
    position = None
    for chunk in encoded:
        position = push_audio_chunk(sid, chunk, rate)
    return position


def _code(call) -> ProcessingError:
    with pytest.raises(ProcessingError) as exc:
        call()
    return exc.value


# --- AC-P4 ---------------------------------------------------------------------------------


class TestAcceptanceP4:
    def test_one_second_of_220_hz_on_a3_is_on_pitch(self, pushed):
        sid = _open()

        position = _push_all(sid, chunks(220.0, 1.0))

        assert position["session_id"] == sid
        assert (position["measure"], position["expected_note"]) == (1, "A3")
        assert position["status"] == "on_pitch"
        assert abs(position["accuracy_cents"]) <= 25
        assert position["sung_pitch_hz"] == pytest.approx(220.0, rel=0.01)
        jsonschema.validate(position, POSITION_OUTPUT_SCHEMA)

    def test_the_first_push_already_returns_its_own_pitch(self, pushed):
        """One round trip both pushes audio and polls: the reply reflects the chunk just sent."""
        sid = _open()

        position = push_audio_chunk(sid, chunks(220.0, 0.1)[0], RATE)

        assert position["status"] == "on_pitch"

    @pytest.mark.parametrize("rate", [8000, TRACKER_SAMPLE_RATE, 44100, 48000])
    def test_other_sample_rates_are_resampled(self, pushed, rate):
        sid = _open()

        position = _push_all(sid, chunks(220.0, 1.0, rate=rate), rate)

        assert position["status"] == "on_pitch"

    def test_a_stopped_take_summarises_the_pushed_audio(self, pushed):
        sid = _open()
        _push_all(sid, chunks(220.0, 1.0))

        summary = stop_monitoring(sid)["summary"]

        assert summary["accuracy_histogram"]["on_pitch"] > 0
        assert summary["accuracy_histogram"]["flat"] == summary["accuracy_histogram"]["sharp"] == 0


class TestSignals:
    def test_silence_is_no_signal(self, pushed):
        sid = _open()

        position = _push_all(sid, chunks(0, 1.0))

        assert position["status"] == "no_signal"
        assert position["sung_pitch_hz"] is None
        assert position["expected_note"] == "A3"

    @pytest.mark.parametrize("freq, status", [(330.0, "sharp"), (196.0, "flat")])
    def test_a_wrong_pitch_is_sharp_or_flat(self, pushed, freq, status):
        sid = _open()

        position = _push_all(sid, chunks(freq, 1.0))

        assert position["expected_note"] == "A3"
        assert position["status"] == status
        assert abs(position["accuracy_cents"]) > 25

    def test_an_empty_chunk_just_polls(self, pushed):
        sid = _open()
        _push_all(sid, chunks(220.0, 0.5))

        assert push_audio_chunk(sid, "", RATE)["status"] == "on_pitch"


# --- Limits (proposal §7: memory exhaustion) ------------------------------------------------


class TestLimits:
    def test_the_chunk_limit_is_about_a_second_at_the_stated_rate(self):
        assert RATE * 2 < max_chunk_bytes(RATE) < RATE * 2 * 1.5
        assert max_chunk_bytes(48000) == 3 * max_chunk_bytes(RATE)

    def test_a_chunk_over_the_limit_is_refused_with_the_limit_in_the_hint(self, pushed):
        sid = _open()
        too_big = base64.b64encode(b"\0" * (max_chunk_bytes(RATE) + 2)).decode()

        error = _code(lambda: push_audio_chunk(sid, too_big, RATE))

        assert error.error_code == "INVALID_PARAMETER"
        assert str(max_chunk_bytes(RATE)) in error.hint

    def test_the_limit_follows_the_rate(self, pushed):
        sid = _open()
        one_second_at_48k = base64.b64encode(pcm(220.0, 1.0, rate=48000)).decode()

        assert push_audio_chunk(sid, one_second_at_48k, 48000)["status"] == "on_pitch"
        assert _code(lambda: push_audio_chunk(sid, one_second_at_48k, RATE)).error_code == "INVALID_PARAMETER"

    def test_pushes_per_second_are_capped_per_session(self, pushed, clock):
        sid, other = _open(), _open()
        tiny = chunks(220.0, 0.01)[0]
        for _ in range(MAX_PUSHES_PER_SECOND):
            push_audio_chunk(sid, tiny, RATE)

        error = _code(lambda: push_audio_chunk(sid, tiny, RATE))

        assert error.error_code == "INVALID_PARAMETER"
        assert str(MAX_PUSHES_PER_SECOND) in error.hint
        push_audio_chunk(other, tiny, RATE)  # another session has its own budget
        clock.advance(1.0)
        push_audio_chunk(sid, tiny, RATE)  # the window has moved on

    def test_a_refused_push_feeds_nothing(self, pushed):
        sid = _open()
        too_big = base64.b64encode(pcm(220.0, 2.0)).decode()

        _code(lambda: push_audio_chunk(sid, too_big, RATE))

        assert get_position(sid)["status"] == "no_signal"
        assert stop_monitoring(sid)["summary"]["accuracy_histogram"]["on_pitch"] == 0

    @pytest.mark.parametrize("rate", [0, 4000, 96000])
    def test_a_sample_rate_out_of_range_is_refused(self, pushed, rate):
        sid = _open()

        error = _code(lambda: push_audio_chunk(sid, chunks(220.0, 0.1)[0], rate))

        assert error.error_code == "INVALID_PARAMETER"
        assert "8000" in error.hint and "48000" in error.hint

    @pytest.mark.parametrize("payload", ["not base64!", base64.b64encode(b"\0\0\0").decode()])
    def test_malformed_pcm_is_invalid_input(self, pushed, payload):
        sid = _open()

        assert _code(lambda: push_audio_chunk(sid, payload, RATE)).error_code == "INVALID_INPUT"


# --- Sessions -------------------------------------------------------------------------------


class TestSessions:
    def test_start_monitoring_opens_a_pushed_session_without_the_server_mic(self, pushed, mic):  # noqa: F811
        sid = load_score(A3_FIRST, "Tenor")["session_id"]

        result = start_monitoring(sid, source="pushed")

        assert result == {"status": "started", "session_id": sid, "source": "pushed"}
        assert isinstance(engine._registry.get(sid).audio_source, PushedChunkSource)
        assert [row["state"] for row in list_sessions()["sessions"]] == ["monitoring"]
        assert mic.instances == []

    def test_the_server_mic_stays_the_default(self, pushed, mic):  # noqa: F811
        sid = load_score(A3_FIRST, "Tenor")["session_id"]

        assert start_monitoring(sid) == {"status": "started", "session_id": sid}
        assert len(mic.instances) == 1
        stop_monitoring(sid)

    def test_an_unknown_source_is_refused(self, pushed):
        sid = load_score(A3_FIRST, "Tenor")["session_id"]

        error = _code(lambda: start_monitoring(sid, source="browser"))

        assert error.error_code == "INVALID_PARAMETER"
        assert "server_mic" in error.hint and "pushed" in error.hint

    def test_unknown_session_is_not_found(self, pushed):
        error = _code(lambda: push_audio_chunk("no-such-session", "", RATE))

        assert error.error_code == "SESSION_NOT_FOUND"

    def test_a_stopped_session_is_not_found(self, pushed):
        sid = _open()
        stop_monitoring(sid)

        assert _code(lambda: push_audio_chunk(sid, "", RATE)).error_code == "SESSION_NOT_FOUND"

    def test_a_server_mic_session_takes_no_pushed_audio(self, pushed, mic):  # noqa: F811
        sid = load_score(A3_FIRST, "Tenor")["session_id"]
        start_monitoring(sid)

        error = _code(lambda: push_audio_chunk(sid, chunks(220.0, 0.1)[0], RATE))

        assert error.error_code == "INVALID_PARAMETER"
        assert "pushed" in error.hint
        stop_monitoring(sid)

    def test_a_loaded_session_takes_no_pushed_audio_yet(self, pushed):
        sid = load_score(A3_FIRST, "Tenor")["session_id"]

        error = _code(lambda: push_audio_chunk(sid, "", RATE))

        assert error.error_code == "INVALID_PARAMETER"
        assert "start_monitoring" in error.hint

    def test_pushing_keeps_the_session_from_timing_out(self, pushed, clock):
        sid = _open()
        limit = pushed.idle_minutes * 60

        clock.advance(limit - 1)
        push_audio_chunk(sid, "", RATE)

        assert pushed.reap(clock.advance(limit - 1)) == []


class TestPushedChunkSource:
    def test_satisfies_the_audio_source_protocol(self):
        assert isinstance(PushedChunkSource(), AudioSource)

    def test_delivers_float_samples_at_the_trackers_rate(self):
        received = []
        source = PushedChunkSource()
        source.start(received.append)

        source.push(base64.b64encode(pcm(220.0, 1.0)).decode(), RATE)

        delivered = np.concatenate(received)
        assert delivered.dtype == np.float32
        assert abs(len(delivered) - TRACKER_SAMPLE_RATE) <= 2
        assert 0.45 < np.max(np.abs(delivered)) <= 0.5

    def test_resampling_is_continuous_across_chunks(self):
        """Chunk by chunk gives the same samples as one push, so chunk edges add no clicks."""
        whole, parts = [], []
        one, many = PushedChunkSource(), PushedChunkSource()
        one.start(whole.append)
        many.start(parts.append)

        one.push(base64.b64encode(pcm(220.0, 0.5)).decode(), RATE)
        for chunk in chunks(220.0, 0.5, chunk_ms=30):
            many.push(chunk, RATE)

        a, b = np.concatenate(whole), np.concatenate(parts)
        assert abs(len(a) - len(b)) <= 1
        n = min(len(a), len(b))
        np.testing.assert_allclose(a[:n], b[:n], atol=1e-4)

    def test_a_closed_source_takes_no_audio(self):
        source = PushedChunkSource()
        source.start(lambda chunk: None)
        source.stop()
        source.close()

        error = _code(lambda: source.push("", RATE))

        assert error.error_code == "INVALID_PARAMETER"

    def test_pushed_audio_never_touches_the_disk(self, pushed, monkeypatch):
        sid = _open()
        encoded = chunks(220.0, 0.5)

        def no_files(*args, **kwargs):
            raise AssertionError(f"pushed audio opened a file: {args!r}")

        monkeypatch.setattr(builtins, "open", no_files)
        _push_all(sid, encoded)
        stop_monitoring(sid)


# --- The tool -------------------------------------------------------------------------------


def _with_client(call):
    async def _go():
        async with Client(app) as client:
            return await call(client)

    return asyncio.run(_go())


async def _tool(name):
    return next(t for t in await list_tools() if t.name == name)


class TestTool:
    async def test_is_app_only_with_a_closed_schema(self):
        tool = await _tool("push_audio_chunk")

        assert is_app_only(tool)
        assert tool.meta == {"ui": {"visibility": ["app"]}}
        assert tool.title
        assert tool.annotations.model_dump(exclude_none=True) == dict(SESSION_STATE)
        schema = tool.input_schema
        assert set(schema["properties"]) == {"session_id", "pcm_b64", "sample_rate"}
        assert set(schema["required"]) == {"session_id", "pcm_b64", "sample_rate"}
        assert schema["additionalProperties"] is False
        assert schema["properties"]["sample_rate"]["type"] == "integer"
        assert tool.output_schema == POSITION_OUTPUT_SCHEMA

    async def test_links_the_coach_when_packaged(self, packaged_ui):
        tool = await _tool("push_audio_chunk")

        assert tool.meta == {"ui": {"resourceUri": COACH_URI, "visibility": ["app"]}}

    def test_hidden_from_clients_without_ui(self):
        names = {t.name for t in _with_client(lambda c: c.list_tools()).tools}

        assert "push_audio_chunk" not in names

    async def test_start_monitoring_takes_a_source(self):
        source = (await _tool("start_monitoring")).input_schema["properties"]["source"]

        assert source["enum"] == ["server_mic", "pushed"]
        assert source["default"] == "server_mic"

    def test_a_take_through_the_protocol(self, pushed):
        encoded = chunks(220.0, 1.0)

        async def go(client):
            opened = await client.call_tool("load_score", {"musicxml": A3_FIRST, "part": "Tenor"})
            sid = opened.structured_content["session_id"]
            started = await client.call_tool("start_monitoring", {"session_id": sid, "source": "pushed"})
            results = [
                await client.call_tool("push_audio_chunk", {"session_id": sid, "pcm_b64": c, "sample_rate": RATE})
                for c in encoded
            ]
            return sid, started, results

        sid, started, results = _with_client(go)

        assert not started.is_error
        assert json.loads(started.content[0].text)["source"] == "pushed"
        last = results[-1]
        assert not last.is_error
        jsonschema.validate(last.structured_content, POSITION_OUTPUT_SCHEMA)
        assert last.structured_content["session_id"] == sid
        assert last.structured_content["status"] == "on_pitch"
        # One short line for the model's eyes, never the audio.
        [block] = last.content
        assert "\n" not in block.text and len(block.text) < 120
        assert encoded[-1][:16] not in block.text
        assert "A3" in block.text and "on pitch" in block.text

    @pytest.mark.parametrize(
        "arguments, code",
        [
            ({"session_id": "no-such-session", "pcm_b64": "", "sample_rate": RATE}, "SESSION_NOT_FOUND"),
            ({"session_id": "", "pcm_b64": "", "sample_rate": RATE}, "INVALID_INPUT"),
            ({"session_id": "x", "pcm_b64": "", "sample_rate": RATE, "path": "/tmp/a.wav"}, "INVALID_PARAMETER"),
            ({"session_id": "x", "pcm_b64": ""}, "INVALID_PARAMETER"),
        ],
    )
    def test_errors_keep_the_envelope(self, pushed, arguments, code):
        result = _with_client(lambda c: c.call_tool("push_audio_chunk", arguments))

        assert result.is_error
        assert result.structured_content is None
        assert json.loads(result.content[0].text)["error_code"] == code

    async def test_a_server_mic_session_is_invalid_parameter(self, pushed, mic):  # noqa: F811
        sid = load_score(A3_FIRST, "Tenor")["session_id"]
        start_monitoring(sid)

        result = await call_tool_result(
            "push_audio_chunk", {"session_id": sid, "pcm_b64": chunks(220.0, 0.1)[0], "sample_rate": RATE}
        )

        assert result.is_error
        assert json.loads(result.content[0].text)["error_code"] == "INVALID_PARAMETER"
        stop_monitoring(sid)
