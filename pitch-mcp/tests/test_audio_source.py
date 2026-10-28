"""The capture interface a monitoring session consumes (proposal §5.1 option B, §6.4).

`ScoreSession` depends on the `AudioSource` protocol, not on sounddevice: `SoundDeviceSource` is
today's server-microphone capture, moved behind the interface unchanged, and any other source
(the browser's pushed chunks, a test double) can be injected. `PitchFrames` is the analysis both
share: one YIN pitch frame per 512-sample hop at 22 050 Hz.
"""

import sys
import threading

import numpy as np
import pytest

from pitch_mcp import engine
from pitch_mcp.engine import (
    HOP_SIZE,
    TRACKER_SAMPLE_RATE,
    AudioSource,
    PitchFrames,
    ProcessingError,
    ScoreSession,
    SoundDeviceSource,
)
from pitch_mcp.utils import note_name_to_hz

from .test_engine import FOUR_NOTE_MUSICXML
from .test_practice import mic  # noqa: F401  (mic is a fixture)


class RecordingSource:
    """An AudioSource double: records the calls and lets the test play the sink."""

    def __init__(self):
        self.sink = None
        self.calls: list[str] = []

    def start(self, sink):
        self.calls.append("start")
        self.sink = sink

    def stop(self):
        self.calls.append("stop")

    def close(self):
        self.calls.append("close")
        self.sink = None


class FailingSource(RecordingSource):
    def start(self, sink):
        raise ProcessingError("no input device", "PROCESSING_FAILED")


def tone(name: str, seconds: float, rate: int = TRACKER_SAMPLE_RATE) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (0.5 * np.sin(2 * np.pi * note_name_to_hz(name) * t)).astype(np.float32)


def _session() -> ScoreSession:
    return ScoreSession(FOUR_NOTE_MUSICXML, "Soprano")


class TestInjectedSource:
    def test_both_sources_satisfy_the_protocol(self):
        assert isinstance(SoundDeviceSource(), AudioSource)
        assert isinstance(RecordingSource(), AudioSource)

    def test_the_session_tracks_what_the_source_delivers(self):
        session, source = _session(), RecordingSource()

        session.start(source=source)
        source.sink(tone("C4", 0.3))
        position = session.get_position()

        assert session.is_monitoring
        assert position["expected_note"] == "C4"
        assert position["sung_pitch_hz"] is not None

    def test_stop_stops_then_closes_the_source(self):
        session, source = _session(), RecordingSource()
        session.start(source=source)

        result = session.stop()

        assert source.calls == ["start", "stop", "close"]
        assert not session.is_monitoring
        assert result["session_id"] == session.session_id
        session.stop()  # a second stop is harmless
        assert source.calls == ["start", "stop", "close"]

    def test_the_default_source_comes_from_the_module_factory(self, monkeypatch):
        made: list[RecordingSource] = []
        monkeypatch.setattr(engine, "server_mic_source", lambda: made.append(RecordingSource()) or made[-1])
        session = _session()

        session.start(tempo_bpm=80)

        assert session.audio_source is made[0]
        assert made[0].calls == ["start"]
        assert session.tempo_bpm == 80
        session.stop()

    def test_a_source_that_fails_leaves_the_session_loaded(self):
        session = _session()

        with pytest.raises(ProcessingError) as exc:
            session.start(source=FailingSource())

        assert exc.value.error_code == "PROCESSING_FAILED"
        assert not session.is_monitoring
        assert session.audio_source is None

    def test_a_restart_follows_from_the_first_note_again(self):
        session, first = _session(), RecordingSource()
        session.start(source=first)
        first.sink(tone("E4", 0.7))
        session.stop()

        second = RecordingSource()
        session.start(source=second)
        second.sink(tone("C4", 0.2))

        assert session.get_position()["expected_note"] == "C4"


class TestSoundDeviceSource:
    """Today's capture behind the interface: same stream settings, callback only queues."""

    def test_opens_the_stream_with_the_same_settings(self, mic):  # noqa: F811
        source = SoundDeviceSource()

        source.start(lambda chunk: None)
        [stream] = mic.instances

        assert {k: v for k, v in stream.kwargs.items() if k != "callback"} == {
            "samplerate": 22050,
            "channels": 1,
            "dtype": "float32",
            "blocksize": 512,
        }
        assert stream.started
        source.stop()
        source.close()
        assert stream.stopped and stream.closed

    def test_blocks_reach_the_sink_on_the_worker_thread(self, mic):  # noqa: F811
        received, threads, done = [], [], threading.Event()

        def sink(chunk):
            received.append(chunk)
            threads.append(threading.get_ident())
            done.set()

        source = SoundDeviceSource()
        source.start(sink)
        callback = mic.instances[0].kwargs["callback"]

        callback(np.ones((HOP_SIZE, 1), dtype=np.float32), HOP_SIZE, None, None)

        assert done.wait(2.0)
        source.stop()
        source.close()
        assert received[0].shape == (HOP_SIZE,)
        # The PortAudio callback only queued the block; the analysis runs elsewhere.
        assert threads[0] != threading.get_ident()

    def test_a_stream_that_fails_to_start_is_closed(self, mic):  # noqa: F811
        mic.fail_on = "start"

        with pytest.raises(ProcessingError) as exc:
            SoundDeviceSource().start(lambda chunk: None)

        assert exc.value.error_code == "PROCESSING_FAILED"
        assert "microphone" in str(exc.value)
        assert mic.instances[0].closed

    def test_missing_sounddevice_is_processing_failed(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "sounddevice", None)

        with pytest.raises(ProcessingError) as exc:
            SoundDeviceSource().start(lambda chunk: None)

        assert exc.value.error_code == "PROCESSING_FAILED"
        assert "portaudio" in str(exc.value)

    def test_stop_and_close_without_start_are_harmless(self):
        source = SoundDeviceSource()

        source.stop()
        source.close()


class TestPitchFrames:
    def test_one_frame_per_hop_whatever_the_chunk_size(self):
        frames = PitchFrames()

        assert len(frames.feed(np.zeros(HOP_SIZE, dtype=np.float32))) == 1
        assert frames.feed(np.zeros(1000, dtype=np.float32))[-1][2] == pytest.approx(
            2 * HOP_SIZE / TRACKER_SAMPLE_RATE
        )
        # 1000 - 512 = 488 samples wait for the next hop.
        assert frames.feed(np.zeros(23, dtype=np.float32)) == []
        [(_, _, elapsed)] = frames.feed(np.zeros(1, dtype=np.float32))
        assert elapsed == pytest.approx(3 * HOP_SIZE / TRACKER_SAMPLE_RATE)

    def test_a_tone_gives_its_frequency(self):
        freq, confidence, _ = PitchFrames().feed(tone("A3", 0.2))[-1]

        assert freq == pytest.approx(220.0, rel=0.05)
        assert confidence > 0.3

    def test_silence_gives_no_pitch(self):
        assert all(freq == 0.0 for freq, _, _ in PitchFrames().feed(np.zeros(4096, dtype=np.float32)))
