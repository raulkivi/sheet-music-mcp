"""Idle timeout for practice sessions: SessionRegistry, Reaper, env parsing and list_sessions.

Every test drives ``reap()`` directly with a fake clock, so nothing here waits on real time.
"""

import json
import logging
import threading

import pytest

from pitch_mcp import engine
from pitch_mcp.engine import (
    DEFAULT_IDLE_MINUTES,
    EXPIRED_RETENTION_SECONDS,
    ProcessingError,
    Reaper,
    ScoreSession,
    SessionRegistry,
    get_position,
    idle_minutes_from_env,
    list_sessions,
    load_score,
    start_monitoring,
    stop_monitoring,
)
from pitch_mcp.server import call_tool

from .test_engine import MINIMAL_MUSICXML

TIMEOUT_MIN = 10
TIMEOUT_SEC = TIMEOUT_MIN * 60


class FakeClock:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


class FakeStream:
    """Stands in for a sounddevice.InputStream."""

    def __init__(self):
        self.stopped = False
        self.closed = False

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class FakeWorker:
    """Stands in for the pitch worker thread of a monitoring session."""

    def join(self, timeout=None):
        pass


def _session() -> ScoreSession:
    return ScoreSession(MINIMAL_MUSICXML, "Soprano")


def _monitoring_session() -> tuple[ScoreSession, FakeStream]:
    """A session that looks as if start_monitoring had opened the microphone."""
    session = _session()
    stream = FakeStream()
    session._stream = stream
    session._worker_thread = FakeWorker()
    return session, stream


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def registry(clock):
    return SessionRegistry(idle_minutes=TIMEOUT_MIN, clock=clock)


@pytest.fixture
def engine_registry(monkeypatch, clock):
    """Swap the engine's registry for one on the fake clock, and keep the reaper thread off."""
    reg = SessionRegistry(idle_minutes=TIMEOUT_MIN, clock=clock)
    monkeypatch.setattr(engine, "_registry", reg)
    monkeypatch.setattr(engine, "_ensure_reaper", lambda: None)
    return reg


# ---------------------------------------------------------------------------
# SessionRegistry
# ---------------------------------------------------------------------------


class TestSessionRegistry:
    def test_add_get_remove(self, registry):
        session = _session()
        registry.add(session)

        assert registry.get(session.session_id) is session
        assert registry.remove(session.session_id) is session
        assert registry.get(session.session_id) is None
        assert registry.remove(session.session_id) is None

    def test_no_reap_before_timeout(self, registry, clock):
        session, stream = _monitoring_session()
        registry.add(session)

        reaped = registry.reap(clock.advance(TIMEOUT_SEC))  # exactly the timeout: not yet

        assert reaped == []
        assert registry.get(session.session_id) is session
        assert not stream.closed

    def test_reap_after_timeout_closes_stream_and_stores_summary(self, registry, clock):
        session, stream = _monitoring_session()
        sid = session.session_id
        registry.add(session)

        reaped = registry.reap(clock.advance(TIMEOUT_SEC + 1))

        assert reaped == [sid]
        assert stream.stopped and stream.closed
        assert registry.get(sid) is None
        assert registry.expired_minutes(sid) == TIMEOUT_MIN
        result = registry.pop_expired(sid)
        assert result["session_id"] == sid
        assert "summary" in result

    def test_loaded_but_never_started_session_expires(self, registry, clock):
        session = _session()
        registry.add(session)

        assert registry.reap(clock.advance(TIMEOUT_SEC + 1)) == [session.session_id]

    def test_touch_resets_idle_time(self, registry, clock):
        session = _session()
        registry.add(session)

        clock.advance(TIMEOUT_SEC - 1)
        assert registry.touch(session.session_id) is session
        assert registry.reap(clock.advance(TIMEOUT_SEC - 1)) == []
        assert registry.reap(clock.advance(2)) == [session.session_id]

    def test_touch_unknown_returns_none(self, registry):
        assert registry.touch("nope") is None

    def test_zero_disables_timeout(self, clock):
        registry = SessionRegistry(idle_minutes=0, clock=clock)
        session, stream = _monitoring_session()
        registry.add(session)

        assert registry.reap(clock.advance(365 * 24 * 3600)) == []
        assert registry.get(session.session_id) is session
        assert not stream.closed

    def test_reap_only_idle_sessions(self, registry, clock):
        old, new = _session(), _session()
        registry.add(old)
        clock.advance(TIMEOUT_SEC - 5)
        registry.add(new)

        assert registry.reap(clock.advance(10)) == [old.session_id]
        assert registry.get(new.session_id) is new

    def test_expired_summaries_dropped_after_one_hour(self, registry, clock):
        session = _session()
        sid = session.session_id
        registry.add(session)
        registry.reap(clock.advance(TIMEOUT_SEC + 1))

        registry.reap(clock.advance(EXPIRED_RETENTION_SECONDS))  # exactly an hour: kept
        assert registry.expired_minutes(sid) == TIMEOUT_MIN

        registry.reap(clock.advance(1))
        assert registry.expired_minutes(sid) is None
        assert registry.pop_expired(sid) is None

    def test_pop_expired_removes_it(self, registry, clock):
        session = _session()
        registry.add(session)
        registry.reap(clock.advance(TIMEOUT_SEC + 1))

        assert registry.pop_expired(session.session_id) is not None
        assert registry.pop_expired(session.session_id) is None

    def test_list_reports_state_and_idle_seconds(self, registry, clock):
        loaded = _session()
        monitoring, _ = _monitoring_session()
        registry.add(loaded)
        clock.advance(30)
        registry.add(monitoring)
        clock.advance(12.34)

        rows = {row["session_id"]: row for row in registry.list()}

        assert rows[loaded.session_id] == {
            "session_id": loaded.session_id,
            "part_id": "P1",
            "part_name": "Soprano",
            "state": "loaded",
            "idle_seconds": 42.3,
        }
        assert rows[monitoring.session_id]["state"] == "monitoring"
        assert rows[monitoring.session_id]["idle_seconds"] == 12.3

    def test_list_leaves_out_expired(self, registry, clock):
        session = _session()
        registry.add(session)
        registry.reap(clock.advance(TIMEOUT_SEC + 1))

        assert registry.list() == []


# ---------------------------------------------------------------------------
# Engine functions on a timed-out session
# ---------------------------------------------------------------------------


class TestEngineAfterReap:
    def test_load_score_counts_as_activity(self, engine_registry, clock):
        sid = load_score(MINIMAL_MUSICXML, "Soprano")["session_id"]

        assert engine_registry.reap(clock.advance(TIMEOUT_SEC)) == []
        assert engine_registry.reap(clock.advance(1)) == [sid]

    def test_get_position_resets_idle_time(self, engine_registry, clock):
        sid = load_score(MINIMAL_MUSICXML, "Soprano")["session_id"]
        clock.advance(TIMEOUT_SEC - 1)
        get_position(sid)

        assert engine_registry.reap(clock.advance(TIMEOUT_SEC - 1)) == []
        stop_monitoring(sid)

    def test_start_monitoring_resets_idle_time(self, engine_registry, clock, monkeypatch):
        monkeypatch.setattr(ScoreSession, "start", lambda self, tempo_bpm=None: None)
        sid = load_score(MINIMAL_MUSICXML, "Soprano")["session_id"]
        clock.advance(TIMEOUT_SEC - 1)
        start_monitoring(sid)

        assert engine_registry.reap(clock.advance(TIMEOUT_SEC - 1)) == []
        stop_monitoring(sid)

    def test_stop_after_reap_returns_summary_with_timed_out(self, engine_registry, clock):
        sid = load_score(MINIMAL_MUSICXML, "Soprano")["session_id"]
        engine_registry.reap(clock.advance(TIMEOUT_SEC + 1))

        result = stop_monitoring(sid)

        assert result["session_id"] == sid
        assert result["timed_out"] is True
        assert result["summary"]["measures_covered"] == 0
        # The stored summary is handed out once, like a normal stop.
        with pytest.raises(ProcessingError) as exc:
            stop_monitoring(sid)
        assert exc.value.error_code == "SESSION_NOT_FOUND"

    def test_normal_stop_is_not_timed_out(self, engine_registry):
        sid = load_score(MINIMAL_MUSICXML, "Soprano")["session_id"]

        assert stop_monitoring(sid)["timed_out"] is False

    def test_get_position_after_reap_gives_hint(self, engine_registry, clock):
        sid = load_score(MINIMAL_MUSICXML, "Soprano")["session_id"]
        engine_registry.reap(clock.advance(TIMEOUT_SEC + 1))

        with pytest.raises(ProcessingError) as exc:
            get_position(sid)

        assert exc.value.error_code == "SESSION_NOT_FOUND"
        assert f"{TIMEOUT_MIN} minutes idle" in exc.value.hint
        assert "stop_monitoring" in exc.value.hint

    def test_start_monitoring_after_reap_gives_hint(self, engine_registry, clock):
        sid = load_score(MINIMAL_MUSICXML, "Soprano")["session_id"]
        engine_registry.reap(clock.advance(TIMEOUT_SEC + 1))

        with pytest.raises(ProcessingError) as exc:
            start_monitoring(sid)

        assert exc.value.error_code == "SESSION_NOT_FOUND"
        assert "stop_monitoring" in exc.value.hint

    def test_unknown_session_has_no_hint(self, engine_registry):
        with pytest.raises(ProcessingError) as exc:
            get_position("never-existed")

        assert exc.value.error_code == "SESSION_NOT_FOUND"
        assert exc.value.hint is None

    def test_after_retention_stop_is_plain_not_found(self, engine_registry, clock):
        sid = load_score(MINIMAL_MUSICXML, "Soprano")["session_id"]
        engine_registry.reap(clock.advance(TIMEOUT_SEC + 1))
        engine_registry.reap(clock.advance(EXPIRED_RETENTION_SECONDS + 1))

        with pytest.raises(ProcessingError) as exc:
            stop_monitoring(sid)
        assert exc.value.error_code == "SESSION_NOT_FOUND"
        assert exc.value.hint is None

    def test_list_sessions_shape(self, engine_registry, clock):
        sid = load_score(MINIMAL_MUSICXML, "Soprano")["session_id"]
        clock.advance(5)

        result = list_sessions()

        assert result["idle_timeout_minutes"] == TIMEOUT_MIN
        assert result["sessions"] == [
            {
                "session_id": sid,
                "part_id": "P1",
                "part_name": "Soprano",
                "state": "loaded",
                "idle_seconds": 5.0,
            }
        ]
        stop_monitoring(sid)
        assert list_sessions()["sessions"] == []


class TestLazyReaperStart:
    def test_first_load_score_starts_reaper(self, monkeypatch, clock):
        monkeypatch.setattr(engine, "_registry", SessionRegistry(idle_minutes=TIMEOUT_MIN, clock=clock))
        monkeypatch.setattr(engine, "_reaper", None)

        sid = load_score(MINIMAL_MUSICXML, "Soprano")["session_id"]
        reaper = engine._reaper
        try:
            assert reaper is not None and reaper.is_alive()
            load_score(MINIMAL_MUSICXML, "Soprano")
            assert engine._reaper is reaper  # started once
        finally:
            reaper.stop()
        assert not reaper.is_alive()
        stop_monitoring(sid)

    def test_no_reaper_when_timeout_disabled(self, monkeypatch, clock):
        monkeypatch.setattr(engine, "_registry", SessionRegistry(idle_minutes=0, clock=clock))
        monkeypatch.setattr(engine, "_reaper", None)

        sid = load_score(MINIMAL_MUSICXML, "Soprano")["session_id"]

        assert engine._reaper is None
        stop_monitoring(sid)


# ---------------------------------------------------------------------------
# PITCH_SESSION_IDLE_MINUTES
# ---------------------------------------------------------------------------


class TestIdleMinutesFromEnv:
    def test_default_when_unset(self):
        assert idle_minutes_from_env({}) == DEFAULT_IDLE_MINUTES == 10

    def test_empty_means_default(self):
        assert idle_minutes_from_env({"PITCH_SESSION_IDLE_MINUTES": ""}) == 10

    @pytest.mark.parametrize("raw, expected", [("15", 15), (" 3 ", 3), ("0", 0)])
    def test_valid(self, raw, expected):
        assert idle_minutes_from_env({"PITCH_SESSION_IDLE_MINUTES": raw}) == expected

    @pytest.mark.parametrize("raw", ["abc", "1.5", "-5"])
    def test_invalid_falls_back_with_warning(self, raw, caplog):
        with caplog.at_level(logging.WARNING, logger="pitch_mcp.engine"):
            assert idle_minutes_from_env({"PITCH_SESSION_IDLE_MINUTES": raw}) == 10

        assert "PITCH_SESSION_IDLE_MINUTES" in caplog.text


# ---------------------------------------------------------------------------
# Reaper
# ---------------------------------------------------------------------------


class RecordingRegistry:
    def __init__(self):
        self.calls = []

    def reap(self, now):
        self.calls.append(now)
        return []


class TestReaper:
    def test_reaps_once_per_tick_and_stops_on_its_event(self, clock):
        registry = RecordingRegistry()
        stop_event = threading.Event()
        sleeps = []

        def fake_sleep(seconds):
            sleeps.append(seconds)
            clock.advance(seconds)
            if len(sleeps) == 3:
                stop_event.set()

        reaper = Reaper(registry, interval=30, clock=clock, sleep=fake_sleep, stop_event=stop_event)
        reaper.run()  # in this thread; returns once the event is set

        assert sleeps == [30, 30, 30]
        assert registry.calls == [1030.0, 1060.0]

    def test_keeps_running_when_reap_raises(self, clock):
        stop_event = threading.Event()
        calls = []

        class Failing:
            def reap(self, now):
                calls.append(now)
                raise RuntimeError("boom")

        def fake_sleep(seconds):
            if len(calls) == 2:
                stop_event.set()

        Reaper(Failing(), clock=clock, sleep=fake_sleep, stop_event=stop_event).run()

        assert len(calls) == 2

    def test_thread_starts_and_stops(self):
        reaper = Reaper(RecordingRegistry(), interval=30)
        reaper.start()
        assert reaper.is_alive()
        assert reaper.daemon

        reaper.stop()

        assert not reaper.is_alive()


# ---------------------------------------------------------------------------
# list_sessions tool
# ---------------------------------------------------------------------------


class TestListSessionsTool:
    async def test_states(self, engine_registry, clock):
        loaded = _session()
        monitoring, _ = _monitoring_session()
        engine_registry.add(loaded)
        engine_registry.add(monitoring)
        clock.advance(7)

        result = await call_tool("list_sessions", {})
        payload = json.loads(result[0].text)

        assert payload["idle_timeout_minutes"] == TIMEOUT_MIN
        states = {row["session_id"]: row["state"] for row in payload["sessions"]}
        assert states == {loaded.session_id: "loaded", monitoring.session_id: "monitoring"}
        for row in payload["sessions"]:
            assert set(row) == {"session_id", "part_id", "part_name", "state", "idle_seconds"}
            assert row["idle_seconds"] == 7.0

    async def test_empty(self, engine_registry):
        payload = json.loads((await call_tool("list_sessions", {}))[0].text)

        assert payload["sessions"] == []

    async def test_get_position_after_reap_returns_hint_in_payload(self, engine_registry, clock):
        session = _session()
        engine_registry.add(session)
        engine_registry.reap(clock.advance(TIMEOUT_SEC + 1))

        result = await call_tool("get_current_position", {"session_id": session.session_id})
        payload = json.loads(result[0].text)

        assert payload["error_code"] == "SESSION_NOT_FOUND"
        assert "stop_monitoring" in payload["hint"]

    async def test_stop_after_reap_returns_timed_out(self, engine_registry, clock):
        session = _session()
        engine_registry.add(session)
        engine_registry.reap(clock.advance(TIMEOUT_SEC + 1))

        result = await call_tool("stop_monitoring", {"session_id": session.session_id})
        payload = json.loads(result[0].text)

        assert payload["timed_out"] is True
        assert "summary" in payload
