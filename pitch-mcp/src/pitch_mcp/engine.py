"""
Core engine for pitch-mcp.

Phase A: Offline analysis of pre-recorded WAV files.
Phase B: Real-time monitoring via microphone (stateful session management).

No MCP SDK imports here.
"""

from __future__ import annotations  # SessionRegistry.list shadows the builtin in its class body

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional

from sheet_music_mcp_core.errors import ProcessingError  # re-exported for server.py

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase A: Offline analysis
# ---------------------------------------------------------------------------

def analyze_recording(audio_path: str, musicxml_str: str, part_id: str) -> dict:
    """Analyse a pre-recorded WAV file against a reference score.

    Args:
        audio_path: Path to a 16-bit PCM WAV file.
        musicxml_str: MusicXML document as a string.
        part_id: Part to compare against: ID, name or voice (e.g. 'P1', 'Soprano', 'S').

    Returns:
        {
            "measures_covered": int,
            "avg_accuracy_cents": int | None,
            "note_accuracy": [...],
            "accuracy_histogram": {...},
        }

    Raises:
        ProcessingError: on any failure with a structured error_code.
    """
    from .aligner import align, summarize
    from .pitch_detector import detect_pitches
    from .utils import extract_part_notes

    if not Path(audio_path).exists():
        raise ProcessingError(
            f"Audio file not found: {audio_path!r}", "FILE_NOT_FOUND"
        )

    # Extract reference note sequence
    try:
        info, note_sequence = extract_part_notes(musicxml_str, part_id)
    except ProcessingError:
        raise
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise ProcessingError(msg, "INVALID_PARAMETER")
        raise ProcessingError(msg, "INVALID_INPUT")
    except Exception as e:
        raise ProcessingError(f"Failed to parse MusicXML: {e}", "INVALID_INPUT")

    if not note_sequence:
        raise ProcessingError(
            f"Part '{part_id}' has no notes.", "INVALID_INPUT"
        )

    # Detect pitches in recording
    try:
        detected = detect_pitches(audio_path)
    except FileNotFoundError as e:
        raise ProcessingError(str(e), "FILE_NOT_FOUND")
    except Exception as e:
        raise ProcessingError(f"Pitch detection failed: {e}", "PROCESSING_FAILED")

    if not detected:
        raise ProcessingError(
            "No pitch frames detected in the recording. "
            "Check audio levels and ensure the file contains vocal audio.",
            "PROCESSING_FAILED",
        )

    # Align detected pitches to note sequence
    try:
        note_results = align(detected, note_sequence)
    except Exception as e:
        raise ProcessingError(f"Score alignment failed: {e}", "PROCESSING_FAILED")

    summary = summarize(note_results)

    return {
        "part_id": info.id,
        "part_name": info.name or info.id,
        "measures_covered": summary["measures_covered"],
        "avg_accuracy_cents": summary["avg_accuracy_cents"],
        "note_accuracy": note_results,
        "accuracy_histogram": summary["accuracy_histogram"],
    }


# ---------------------------------------------------------------------------
# Phase B: Real-time monitoring
# ---------------------------------------------------------------------------

class ScoreSession:
    """Holds state for one active monitoring session."""

    def __init__(self, musicxml_str: str, part_id: str):
        from .utils import extract_nominal_tempo_bpm, extract_part_notes

        self.session_id = str(uuid.uuid4())

        try:
            info, self.note_sequence = extract_part_notes(musicxml_str, part_id)
        except ProcessingError:
            raise
        except ValueError as e:
            msg = str(e)
            if "not found" in msg.lower():
                raise ProcessingError(msg, "INVALID_PARAMETER")
            raise ProcessingError(msg, "INVALID_INPUT")
        except Exception as e:
            raise ProcessingError(f"Failed to parse MusicXML: {e}", "INVALID_INPUT")

        if not self.note_sequence:
            raise ProcessingError(
                f"Part '{part_id}' has no notes.", "INVALID_INPUT"
            )

        self.part_id = info.id
        self._part_name = info.name or info.id

        try:
            self._nominal_bpm = extract_nominal_tempo_bpm(musicxml_str)
        except Exception:
            self._nominal_bpm = 120.0

        self._stream = None
        self._audio_queue: "queue.Queue" = None
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # Current position state (updated by worker thread)
        self._current_position: Optional[dict] = None
        self._history: list[dict] = []  # all per-note results so far
        self._note_idx = 0  # causal position pointer, never moves backward
        self._tempo_bpm: Optional[int] = None  # set by start(); overrides score tempo

    @property
    def part_name(self) -> str:
        return self._part_name

    @property
    def is_monitoring(self) -> bool:
        """True while the microphone stream and pitch worker are running."""
        return self._worker_thread is not None

    @property
    def measure_count(self) -> int:
        if not self.note_sequence:
            return 0
        return self.note_sequence[-1]["measure"]

    @property
    def duration_seconds(self) -> float:
        if not self.note_sequence:
            return 0.0
        return self.note_sequence[-1]["end_sec"]

    def start(self, tempo_bpm: Optional[int] = None):
        """Open the microphone stream and begin pitch detection."""
        import queue

        try:
            import sounddevice as sd
        except (ImportError, OSError) as e:
            raise ProcessingError(
                f"sounddevice is not available: {e}. "
                "Install libportaudio2 (Linux) or portaudio (macOS).",
                "PROCESSING_FAILED",
            )

        from .pitch_detector import get_backend
        from .utils import extract_note_sequence

        self._audio_queue = queue.Queue()
        self._stop_event.clear()
        self._note_idx = 0
        self._tempo_bpm = tempo_bpm

        sample_rate = 22050
        hop_size = 512

        def _audio_callback(indata, frames, time_info, status):
            if status:
                logger.warning("sounddevice status: %s", status)
            # Copy audio data to queue (non-blocking)
            self._audio_queue.put(indata[:, 0].copy() if indata.ndim > 1 else indata.copy())

        try:
            self._stream = sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                blocksize=hop_size,
                callback=_audio_callback,
            )
            self._stream.start()
        except Exception as e:
            raise ProcessingError(
                f"Failed to open microphone: {e}", "PROCESSING_FAILED"
            )

        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            args=(sample_rate, hop_size),
            daemon=True,
        )
        self._worker_thread.start()

    def _worker_loop(self, sample_rate: int, hop_size: int):
        """Background thread: run pitch detection on incoming audio chunks.

        Uses a lightweight autocorrelation-based YIN implementation that operates
        on accumulated audio buffers, since librosa's pYIN needs a full recording.
        """
        import queue as queue_module
        import numpy as np

        # Accumulate audio into a rolling buffer for YIN estimation
        buffer = np.zeros(2048, dtype=np.float32)
        chunk_count = 0

        def _yin_pitch(buf: np.ndarray, sr: int) -> tuple[float, float]:
            """Simple YIN pitch estimate. Returns (freq_hz, confidence)."""
            # Autocorrelation-based fundamental frequency estimation
            n = len(buf)
            half = n // 2
            # Difference function
            d = np.zeros(half)
            for tau in range(1, half):
                d[tau] = np.sum((buf[:half] - buf[tau:tau + half]) ** 2)
            # Cumulative mean normalized difference
            cmnd = np.zeros(half)
            cmnd[0] = 1.0
            running_sum = 0.0
            for tau in range(1, half):
                running_sum += d[tau]
                cmnd[tau] = d[tau] * tau / running_sum if running_sum > 0 else 1.0
            # Find first dip below threshold
            threshold = 0.15
            tau_est = 0
            for tau in range(2, half):
                if cmnd[tau] < threshold:
                    # Parabolic interpolation
                    if tau + 1 < half:
                        better = tau + (cmnd[tau + 1] - cmnd[tau - 1]) / (
                            2 * (2 * cmnd[tau] - cmnd[tau - 1] - cmnd[tau + 1]) + 1e-10
                        )
                        tau_est = better
                    else:
                        tau_est = tau
                    break
            if tau_est < 2:
                return 0.0, 0.0
            freq = sr / tau_est
            confidence = 1.0 - cmnd[int(tau_est)]
            return float(freq), max(0.0, float(confidence))

        while not self._stop_event.is_set():
            try:
                chunk = self._audio_queue.get(timeout=0.1)
            except queue_module.Empty:
                continue

            chunk = chunk.astype(np.float32)
            # Shift buffer and add new chunk
            shift = min(len(chunk), len(buffer))
            buffer = np.roll(buffer, -shift)
            buffer[-shift:] = chunk[:shift]

            freq, confidence = _yin_pitch(buffer, sample_rate)

            chunk_count += 1
            elapsed_sec = chunk_count * hop_size / sample_rate

            self._process_pitch_frame(freq, confidence, elapsed_sec)

    def _find_best_note_index(self, score_time: float, freq_hz: float) -> int:
        """Pick the note whose pitch best matches the detected frequency,
        among notes plausible given how much score-time has elapsed.

        This is what makes position tracking audio-driven rather than a pure
        wall-clock pointer: the singer's actual pitch decides which note is
        current, not just elapsed time. Never moves backward, and never
        jumps further ahead than a short lookahead window, so a brief
        mismatch can't cause a wild skip.
        """
        from .aligner import _hz_to_cents_deviation

        n = len(self.note_sequence)
        start_idx = self._note_idx
        lookahead = 4
        end_idx = min(n, start_idx + 1 + lookahead)

        best_idx = start_idx
        best_cents = None
        for idx in range(start_idx, end_idx):
            note = self.note_sequence[idx]
            # Only consider notes plausible given elapsed score-time — don't
            # let a coincidentally-matching pitch far in the future win.
            if note["start_sec"] > score_time + 1.0:
                break
            cents = abs(_hz_to_cents_deviation(freq_hz, note["freq_hz"]))
            if best_cents is None or cents < best_cents:
                best_cents = cents
                best_idx = idx

        # If nothing nearby matched well, fall back to whatever note the
        # timeline says we should be on, so a missed/mismatched note doesn't
        # stall position forever.
        if best_cents is not None and best_cents > 150:
            timeline_idx = start_idx
            while (
                timeline_idx < n - 1
                and self.note_sequence[timeline_idx]["end_sec"] < score_time
            ):
                timeline_idx += 1
            if timeline_idx > best_idx:
                best_idx = timeline_idx

        return best_idx

    def _process_pitch_frame(self, freq_hz: float, confidence: float, elapsed_sec: float) -> None:
        """Update current position/history from one detected pitch frame."""
        from .aligner import _classify, _hz_to_cents_deviation

        if freq_hz <= 0 or confidence < 0.3 or freq_hz < 50 or freq_hz > 2100:
            with self._lock:
                if self._current_position is not None:
                    self._current_position = {
                        **self._current_position,
                        "sung_pitch_hz": None,
                        "accuracy_cents": None,
                        "status": "no_signal",
                    }
            return

        # A tempo_bpm override means the singer intends to perform faster or
        # slower than the score's written tempo — scale wall-clock time into
        # score-time before using it to bound plausible notes (IR-4).
        score_time = elapsed_sec
        if self._tempo_bpm and self._nominal_bpm:
            score_time = elapsed_sec * (self._tempo_bpm / self._nominal_bpm)

        note_idx = self._find_best_note_index(score_time, freq_hz)
        self._note_idx = note_idx

        note = self.note_sequence[note_idx]
        cents = _hz_to_cents_deviation(freq_hz, note["freq_hz"])
        status = _classify(cents)
        new_pos = {
            "measure": note["measure"],
            "beat": note["beat"],
            "expected_note": note["note_name"],
            "sung_pitch_hz": round(freq_hz, 2),
            "accuracy_cents": cents,
            "status": status,
        }

        with self._lock:
            self._current_position = new_pos
            self._history.append(new_pos)

    def get_position(self) -> dict:
        """Return the most recent position/accuracy snapshot."""
        with self._lock:
            if self._current_position is None:
                return {
                    "session_id": self.session_id,
                    "measure": 1,
                    "beat": 1.0,
                    "expected_note": (
                        self.note_sequence[0]["note_name"] if self.note_sequence else "?"
                    ),
                    "sung_pitch_hz": None,
                    "accuracy_cents": None,
                    "status": "no_signal",
                }
            return {"session_id": self.session_id, **self._current_position}

    def stop(self) -> dict:
        """Stop the microphone stream and return a session summary."""
        from .aligner import summarize

        self._stop_event.set()

        # Take the stream and worker under the lock, so a reaper and a stop_monitoring call
        # racing each other close them only once.
        with self._lock:
            stream, self._stream = self._stream, None
            worker, self._worker_thread = self._worker_thread, None

        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as e:
                logger.warning("Error closing audio stream: %s", e)

        if worker is not None:
            worker.join(timeout=2.0)

        with self._lock:
            history = list(self._history)

        # Build summary from history (or zero if no data)
        if history:
            summary = summarize(history)
        else:
            summary = {
                "measures_covered": 0,
                "avg_accuracy_cents": None,
                "accuracy_histogram": {
                    "on_pitch": 0, "sharp": 0, "flat": 0, "no_signal": 0
                },
            }

        return {"session_id": self.session_id, "summary": summary}


# ---------------------------------------------------------------------------
# Session registry and idle timeout (lives for the process lifetime)
# ---------------------------------------------------------------------------

IDLE_MINUTES_ENV = "PITCH_SESSION_IDLE_MINUTES"
DEFAULT_IDLE_MINUTES = 10
REAP_INTERVAL_SECONDS = 30.0
# How long a timed-out session's summary stays available to stop_monitoring.
EXPIRED_RETENTION_SECONDS = 3600.0


def idle_minutes_from_env(environ: Optional[Mapping[str, str]] = None) -> int:
    """Read PITCH_SESSION_IDLE_MINUTES: whole minutes, 0 disables the timeout.

    Unset or empty gives the default. Anything else that is not an integer >= 0 logs a
    warning and gives the default too, so a typo never disables the timeout.
    """
    environ = os.environ if environ is None else environ
    raw = environ.get(IDLE_MINUTES_ENV, "").strip()
    if not raw:
        return DEFAULT_IDLE_MINUTES
    try:
        minutes = int(raw)
    except ValueError:
        minutes = -1
    if minutes < 0:
        logger.warning(
            "%s=%r is not a whole number of minutes (0 or more); using the default %d.",
            IDLE_MINUTES_ENV, raw, DEFAULT_IDLE_MINUTES,
        )
        return DEFAULT_IDLE_MINUTES
    return minutes


@dataclass
class _Expired:
    """A session closed by the idle timeout, kept so stop_monitoring can still report it."""

    expired_at: float
    idle_minutes: int
    session: Optional[ScoreSession]  # set until reap() has finished stopping it
    result: Optional[dict] = None  # the stop() result once it has


class SessionRegistry:
    """Holds the open sessions, when each was last used, and the ones the timeout closed.

    Activity (creation, ``touch``) resets a session's idle time. ``reap(now)`` stops every
    session idle longer than the timeout and keeps its summary for an hour.

    One lock guards all maps. It is held only for dict operations, never while a stream
    closes, and it is never taken in the audio callback (that only queues chunks).
    """

    def __init__(
        self,
        idle_minutes: int = DEFAULT_IDLE_MINUTES,
        clock: Callable[[], float] = time.monotonic,
        expired_retention_seconds: float = EXPIRED_RETENTION_SECONDS,
    ):
        self._idle_minutes = idle_minutes
        self._clock = clock
        self._retention = expired_retention_seconds
        self._lock = threading.Lock()
        self._sessions: dict[str, ScoreSession] = {}
        self._last_active: dict[str, float] = {}
        self._expired: dict[str, _Expired] = {}

    @property
    def idle_minutes(self) -> int:
        """The timeout in minutes; 0 means sessions never time out."""
        return self._idle_minutes

    @property
    def clock(self) -> Callable[[], float]:
        return self._clock

    def add(self, session: ScoreSession) -> None:
        with self._lock:
            self._sessions[session.session_id] = session
            self._last_active[session.session_id] = self._clock()

    def get(self, session_id: str) -> Optional[ScoreSession]:
        """Look a session up without counting it as activity."""
        with self._lock:
            return self._sessions.get(session_id)

    def touch(self, session_id: str) -> Optional[ScoreSession]:
        """Record activity on a session and return it (None if it is not open)."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                self._last_active[session_id] = self._clock()
            return session

    def remove(self, session_id: str) -> Optional[ScoreSession]:
        with self._lock:
            self._last_active.pop(session_id, None)
            return self._sessions.pop(session_id, None)

    def list(self) -> list[dict]:
        """One row per open session, in the order they were loaded."""
        now = self._clock()
        with self._lock:
            return [
                {
                    "session_id": session_id,
                    "part_id": session.part_id,
                    "part_name": session.part_name,
                    "state": "monitoring" if session.is_monitoring else "loaded",
                    "idle_seconds": round(max(0.0, now - self._last_active[session_id]), 1),
                }
                for session_id, session in self._sessions.items()
            ]

    def expired_minutes(self, session_id: str) -> Optional[int]:
        """The timeout that closed this session, or None if the timeout did not close it."""
        with self._lock:
            entry = self._expired.get(session_id)
            return None if entry is None else entry.idle_minutes

    def pop_expired(self, session_id: str) -> Optional[dict]:
        """Hand out (once) the stop() result of a session the timeout closed."""
        with self._lock:
            entry = self._expired.pop(session_id, None)
        if entry is None:
            return None
        if entry.result is not None:
            return entry.result
        # reap() is still closing it; ScoreSession.stop() is safe to call twice.
        return entry.session.stop()

    def reap(self, now: float) -> list[str]:
        """Stop every session idle longer than the timeout; return their IDs.

        Also forgets timed-out summaries older than the retention period.
        """
        with self._lock:
            for session_id in [
                sid for sid, e in self._expired.items() if now - e.expired_at > self._retention
            ]:
                del self._expired[session_id]

            if self._idle_minutes <= 0:
                return []
            limit = self._idle_minutes * 60
            idle = [
                session
                for session_id, session in self._sessions.items()
                if now - self._last_active[session_id] > limit
            ]
            for session in idle:
                del self._sessions[session.session_id]
                del self._last_active[session.session_id]
                self._expired[session.session_id] = _Expired(now, self._idle_minutes, session)

        # Close the streams outside the lock, so tool calls are not held up meanwhile.
        for session in idle:
            try:
                result = session.stop()
            except Exception as e:
                logger.warning("Error stopping idle session %s: %s", session.session_id, e)
                result = {"session_id": session.session_id, "summary": None}
            with self._lock:
                entry = self._expired.get(session.session_id)
                if entry is not None and entry.session is session:
                    entry.result, entry.session = result, None
            logger.info(
                "Closed session %s after %d minutes idle.", session.session_id, self._idle_minutes
            )
        return [session.session_id for session in idle]


class Reaper(threading.Thread):
    """Daemon thread that calls ``registry.reap(clock())`` every ``interval`` seconds.

    ``sleep`` defaults to waiting on the stop event, so ``stop()`` wakes it at once. Tests
    inject ``sleep`` and ``stop_event`` and call ``run()`` directly.
    """

    def __init__(
        self,
        registry,
        interval: float = REAP_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Optional[Callable[[float], object]] = None,
        stop_event: Optional[threading.Event] = None,
    ):
        super().__init__(name="pitch-session-reaper", daemon=True)
        self._registry = registry
        self._interval = interval
        self._clock = clock
        self._stop_event = threading.Event() if stop_event is None else stop_event
        self._sleep = self._stop_event.wait if sleep is None else sleep

    def run(self) -> None:
        while True:
            self._sleep(self._interval)
            if self._stop_event.is_set():
                return
            try:
                self._registry.reap(self._clock())
            except Exception:
                logger.exception("Session reaper failed; retrying next tick.")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self.is_alive():
            self.join(timeout)


_registry = SessionRegistry(idle_minutes=idle_minutes_from_env())
_reaper: Optional[Reaper] = None
_reaper_lock = threading.Lock()


def _ensure_reaper() -> None:
    """Start the reaper thread on first use (not at import), unless the timeout is off."""
    global _reaper
    if _registry.idle_minutes <= 0:
        return
    with _reaper_lock:
        if _reaper is None or not _reaper.is_alive():
            _reaper = Reaper(_registry, clock=_registry.clock)
            _reaper.start()


def _stop_reaper() -> None:
    """Stop the reaper thread if it is running (used by the test suite)."""
    global _reaper
    with _reaper_lock:
        if _reaper is not None:
            _reaper.stop()
            _reaper = None


def load_score(musicxml_str: str, part_id: str) -> dict:
    """Load a reference score and create a new session.

    Returns:
        {
            "session_id": "...",
            "part_id": "P1",            # stable MusicXML score-part id
            "part_name": "Soprano",
            "measure_count": 32,
            "duration_seconds": 142.0,
        }
    """
    session = ScoreSession(musicxml_str, part_id)
    _registry.add(session)
    _ensure_reaper()

    return {
        "session_id": session.session_id,
        "part_id": session.part_id,
        "part_name": session.part_name,
        "measure_count": session.measure_count,
        "duration_seconds": round(session.duration_seconds, 2),
    }


def start_monitoring(session_id: str, tempo_bpm: Optional[int] = None) -> dict:
    """Start microphone monitoring for a session."""
    session = _active_session(session_id)
    session.start(tempo_bpm=tempo_bpm)
    _registry.touch(session_id)
    return {"status": "started", "session_id": session_id}


def get_position(session_id: str) -> dict:
    """Get the current score position and pitch accuracy for a session."""
    return _active_session(session_id).get_position()


def stop_monitoring(session_id: str) -> dict:
    """Stop monitoring and return the session summary.

    A session the idle timeout already closed returns the summary kept at that moment,
    with ``timed_out: true``.
    """
    session = _registry.remove(session_id)
    if session is not None:
        return {**session.stop(), "timed_out": False}
    result = _registry.pop_expired(session_id)
    if result is not None:
        return {**result, "timed_out": True}
    raise _session_not_found(session_id)


def list_sessions() -> dict:
    """List the open sessions and the idle timeout that applies to them."""
    return {"idle_timeout_minutes": _registry.idle_minutes, "sessions": _registry.list()}


def _active_session(session_id: str) -> ScoreSession:
    """Return an open session, counting the call as activity, or raise SESSION_NOT_FOUND."""
    session = _registry.touch(session_id)
    if session is None:
        raise _session_not_found(session_id)
    return session


def _session_not_found(session_id: str) -> ProcessingError:
    minutes = _registry.expired_minutes(session_id)
    if minutes is None:
        return ProcessingError(
            f"Session '{session_id}' not found. Call load_score first.",
            "SESSION_NOT_FOUND",
        )
    return ProcessingError(
        f"Session '{session_id}' was closed after {minutes} minutes idle.",
        "SESSION_NOT_FOUND",
        hint=(
            f"The session timed out after {minutes} minutes idle; call stop_monitoring for "
            "the summary, then load_score to start again."
        ),
    )


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def health_check() -> dict:
    """Check availability of all runtime dependencies.

    Returns a structured dict with status for each subsystem:
      - offline_analysis: librosa/pYIN (required for analyze_recording)
      - realtime_monitoring: sounddevice + portaudio (required for start_monitoring)

    Missing portaudio is a warning, not an error — offline mode still works.
    """
    # --- Offline analysis backend (librosa/pYIN) ---
    librosa_ok = False
    librosa_version = "unavailable"
    try:
        import librosa  # noqa: F401
        librosa_ok = True
        librosa_version = getattr(librosa, "__version__", "unknown")
    except Exception:
        pass

    # --- Real-time backend (sounddevice + portaudio) ---
    sounddevice_ok = False
    sounddevice_version = "unavailable"
    portaudio_ok = False
    mic_available = False
    try:
        import sounddevice as sd
        sounddevice_ok = True
        sounddevice_version = getattr(sd, "__version__", "unknown")
        devices = sd.query_devices()
        portaudio_ok = True
        mic_available = any(d["max_input_channels"] > 0 for d in devices)
    except Exception:
        pass

    realtime_ready = sounddevice_ok and portaudio_ok

    if not librosa_ok:
        overall = "error"
        summary = (
            "Offline analysis backend (librosa) is not available. "
            "Run 'uv sync' inside the pitch-mcp directory to install dependencies."
        )
    elif not realtime_ready:
        overall = "degraded"
        summary = (
            "Offline analysis (analyze_recording) is ready. "
            "Real-time monitoring (start_monitoring) requires libportaudio2 — "
            "install it with: sudo apt-get install libportaudio2"
        )
    else:
        overall = "ok"
        summary = "All systems operational. Offline analysis and real-time monitoring are ready."

    return {
        "status": overall,
        "summary": summary,
        "offline_analysis": {
            "available": librosa_ok,
            "backend": "librosa/pYIN",
            "librosa_version": librosa_version,
        },
        "realtime_monitoring": {
            "available": realtime_ready,
            "sounddevice_available": sounddevice_ok,
            "sounddevice_version": sounddevice_version,
            "portaudio_available": portaudio_ok,
            "microphone_detected": mic_available,
        },
    }
