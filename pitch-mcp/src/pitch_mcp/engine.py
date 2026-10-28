"""
Core engine for pitch-mcp.

Phase A: Offline analysis of pre-recorded WAV files.
Phase B: Real-time monitoring via microphone (stateful session management).

No MCP SDK imports here.
"""

from __future__ import annotations  # SessionRegistry.list shadows the builtin in its class body

import base64
import binascii
import logging
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Protocol, Sequence, runtime_checkable

import numpy as np
from sheet_music_mcp_core.errors import ProcessingError  # re-exported for server.py
from sheet_music_mcp_core.measures import select_measures

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase A: Offline analysis
# ---------------------------------------------------------------------------

def analyze_recording(
    audio_path: str, musicxml_str: str, part_id: str, measures: Optional[Sequence[int]] = None
) -> dict:
    """Analyse a pre-recorded WAV file against a reference score.

    Args:
        audio_path: Path to a 16-bit PCM WAV file.
        musicxml_str: MusicXML document as a string.
        part_id: Part to compare against: ID, name or voice (e.g. 'P1', 'Soprano', 'S').
        measures: Optional inclusive [start, end] printed measure numbers; the recording is
            compared against those bars only (it starts at ``start``).

    Returns:
        {
            "measures_covered": int,
            "avg_accuracy_cents": int | None,
            "note_accuracy": [...],
            "accuracy_histogram": {...},
            "highlights": [...],
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

    musicxml_str = _select(musicxml_str, measures)

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
        "highlights": summary["highlights"],
    }


def _select(musicxml_str: str, measures: Optional[Sequence[int]]) -> str:
    """The score cut to ``measures`` (printed numbers), or unchanged when it is None.

    Raises ProcessingError (INVALID_PARAMETER with the score's range as hint) for a bad range.
    """
    return select_measures(musicxml_str, measures)


# ---------------------------------------------------------------------------
# Phase B: live audio, wherever it comes from
# ---------------------------------------------------------------------------

TRACKER_SAMPLE_RATE = 22050  # the rate the live pitch analysis runs at
HOP_SIZE = 512  # samples per pitch frame (about 23 ms)
YIN_WINDOW = 2048  # samples the YIN estimate looks at (about 93 ms)

AudioSink = Callable[[np.ndarray], None]


@runtime_checkable
class AudioSource(Protocol):
    """Where a monitoring session's audio comes from (proposal §6.4, dependency inversion).

    ``start(sink)`` begins delivering mono float32 chunks at ``TRACKER_SAMPLE_RATE`` to ``sink``
    and raises ProcessingError when the source cannot open. The sink is called one chunk at a
    time, from whichever thread the source uses. ``stop`` halts delivery and ``close`` releases
    what the source holds; both are safe to call more than once, or before ``start``.
    """

    def start(self, sink: AudioSink) -> None: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...


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
            # Interpolating from the dip's first sample, not its minimum, read about 40 cents
            # flat on every note; walk down to the minimum first (YIN step 4).
            while tau + 1 < half and cmnd[tau + 1] < cmnd[tau]:
                tau += 1
            tau_est = tau
            if tau + 1 < half:
                # Parabolic interpolation through the minimum and its neighbours
                left, centre, right = cmnd[tau - 1], cmnd[tau], cmnd[tau + 1]
                curvature = left - 2 * centre + right
                if curvature > 0:
                    tau_est = tau + (left - right) / (2 * curvature)
            break
    if tau_est < 2:
        return 0.0, 0.0
    freq = sr / tau_est
    confidence = 1.0 - cmnd[min(half - 1, int(round(tau_est)))]
    return float(freq), max(0.0, float(confidence))


class PitchFrames:
    """Turns audio chunks of any length into pitch frames, one per hop.

    Uses a lightweight autocorrelation-based YIN on a rolling window, since librosa's pYIN needs
    a full recording. Holds only that window and the samples short of the next hop; elapsed time
    counts hops, so it is audio time, not wall-clock time.
    """

    def __init__(self, sample_rate: int = TRACKER_SAMPLE_RATE, hop_size: int = HOP_SIZE, window: int = YIN_WINDOW):
        self._sample_rate = sample_rate
        self._hop_size = hop_size
        self._buffer = np.zeros(window, dtype=np.float32)
        self._pending = np.zeros(0, dtype=np.float32)
        self._hops = 0

    def feed(self, chunk: np.ndarray) -> list[tuple[float, float, float]]:
        """``(freq_hz, confidence, elapsed_sec)`` for every hop the chunk completes."""
        samples = np.concatenate([self._pending, np.asarray(chunk, dtype=np.float32)])
        frames = []
        offset = 0
        while len(samples) - offset >= self._hop_size:
            hop = samples[offset:offset + self._hop_size]
            offset += self._hop_size
            # Shift the window and add the new hop
            self._buffer = np.roll(self._buffer, -len(hop))
            self._buffer[-len(hop):] = hop
            freq, confidence = _yin_pitch(self._buffer, self._sample_rate)
            self._hops += 1
            frames.append((freq, confidence, self._hops * self._hop_size / self._sample_rate))
        self._pending = samples[offset:].copy()
        return frames


class SoundDeviceSource:
    """The server host's microphone through sounddevice / PortAudio (Practice Coach option A).

    The PortAudio callback only queues a copy of each block: no analysis, no locks. A daemon
    worker hands the blocks to the sink, where the pitch analysis runs.
    """

    def __init__(self, sample_rate: int = TRACKER_SAMPLE_RATE, block_size: int = HOP_SIZE):
        self._sample_rate = sample_rate
        self._block_size = block_size
        self._stream = None
        self._worker: Optional[threading.Thread] = None
        self._queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()

    def start(self, sink: AudioSink) -> None:
        try:
            import sounddevice as sd
        except (ImportError, OSError) as e:
            raise ProcessingError(
                f"sounddevice is not available: {e}. "
                "Install libportaudio2 (Linux) or portaudio (macOS).",
                "PROCESSING_FAILED",
            )

        self._queue = queue.Queue()
        self._stop_event.clear()

        def _audio_callback(indata, frames, time_info, status):
            if status:
                logger.warning("sounddevice status: %s", status)
            # Copy audio data to queue (non-blocking)
            self._queue.put(indata[:, 0].copy() if indata.ndim > 1 else indata.copy())

        try:
            self._stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=1,
                dtype="float32",
                blocksize=self._block_size,
                callback=_audio_callback,
            )
            self._stream.start()
        except Exception as e:
            # A stream that opened but failed to start would otherwise hold the device.
            self.close()
            raise ProcessingError(
                f"Failed to open microphone: {e}", "PROCESSING_FAILED"
            )

        self._worker = threading.Thread(target=self._pump, args=(sink,), daemon=True)
        self._worker.start()

    def _pump(self, sink: AudioSink) -> None:
        while not self._stop_event.is_set():
            try:
                chunk = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            sink(chunk)

    def stop(self) -> None:
        self._stop_event.set()
        if self._stream is not None:
            self._stream.stop()

    def close(self) -> None:
        self._stop_event.set()
        stream, self._stream = self._stream, None
        worker, self._worker = self._worker, None
        try:
            if stream is not None:
                stream.close()
        finally:
            if worker is not None:
                worker.join(timeout=2.0)
            self._queue = queue.Queue()  # drop blocks nobody analysed


# Pushed audio (proposal §7, memory exhaustion): a chunk holds at most about a second of audio
# at its stated rate, with margin for a late flush, and a session takes a bounded number of pushes
# per second. The Practice Coach sends ~100 ms chunks, about 10 per second.
MIN_PUSH_SAMPLE_RATE = 8000
MAX_PUSH_SAMPLE_RATE = 48000
MAX_CHUNK_SECONDS = 1.25
MAX_PUSHES_PER_SECOND = 25
_PCM_BYTES_PER_SAMPLE = 2  # 16-bit little-endian mono


def max_chunk_bytes(sample_rate: int) -> int:
    """The largest PCM chunk, in bytes, a push at ``sample_rate`` may carry."""
    return int(sample_rate * MAX_CHUNK_SECONDS) * _PCM_BYTES_PER_SAMPLE


class _LinearResampler:
    """Streaming linear interpolation to ``target_rate``, continuous across chunk edges.

    Keeps only the last input sample and the fractional read position between calls. Linear
    interpolation keeps the time base exact, which is all pitch tracking needs; its slight
    high-frequency roll-off does not move a sung fundamental.
    """

    def __init__(self, target_rate: int):
        self._target_rate = target_rate
        self._rate: Optional[int] = None
        self._last: Optional[float] = None
        self._phase = 0.0

    def __call__(self, samples: np.ndarray, rate: int) -> np.ndarray:
        if rate != self._rate:
            # A new rate restarts the stream rather than mixing two time bases.
            self._rate, self._last, self._phase = rate, None, 0.0
        if rate == self._target_rate or len(samples) == 0:
            return samples
        x = samples if self._last is None else np.concatenate([[self._last], samples]).astype(np.float32)
        step = rate / self._target_rate  # input samples per output sample
        positions = np.arange(self._phase, len(x) - 1, step)
        resampled = np.interp(positions, np.arange(len(x)), x).astype(np.float32)
        next_position = positions[-1] + step if len(positions) else self._phase
        # The last input sample becomes index 0 of the next call.
        self._phase = next_position - (len(x) - 1)
        self._last = float(x[-1])
        return resampled


class PushedChunkSource:
    """Audio the Practice Coach captured in the browser and pushed (Practice Coach option B).

    ``push`` decodes a base64 chunk of 16-bit little-endian mono PCM, resamples it to
    ``TRACKER_SAMPLE_RATE`` and hands it to the sink on the caller's thread, so the position the
    push returns already reflects that chunk, and no queue can grow behind a slow analysis.
    Nothing is written to disk and no audio is kept once the sink has it (proposal §7,
    microphone privacy).
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        max_pushes_per_second: int = MAX_PUSHES_PER_SECOND,
    ):
        self._clock = clock
        self._max_pushes = max_pushes_per_second
        self._recent: list[float] = []  # times of the pushes in the last second
        self._sink: Optional[AudioSink] = None
        self._resampler = _LinearResampler(TRACKER_SAMPLE_RATE)
        self._lock = threading.Lock()

    def start(self, sink: AudioSink) -> None:
        with self._lock:
            self._sink = sink

    def stop(self) -> None:
        with self._lock:
            self._sink = None

    def close(self) -> None:
        with self._lock:
            self._sink = None
            self._resampler = _LinearResampler(TRACKER_SAMPLE_RATE)
            self._recent = []

    def push(self, pcm_b64: str, sample_rate: int) -> None:
        """Feed one chunk; raises ProcessingError (INVALID_PARAMETER, INVALID_INPUT) and feeds
        nothing when the chunk breaks a limit or is not 16-bit PCM in base64."""
        with self._lock:
            if self._sink is None:
                raise ProcessingError(
                    "This session is no longer listening for pushed audio.",
                    "INVALID_PARAMETER",
                    hint="Call start_monitoring with source 'pushed' to listen again.",
                )
            _check_sample_rate(sample_rate)
            # Checked before decoding, so an oversized chunk costs nothing.
            limit = max_chunk_bytes(sample_rate)
            if len(pcm_b64) > 4 * -(-limit // 3):
                raise _chunk_too_large(len(pcm_b64) * 3 // 4, sample_rate)
            self._admit_push()
            pcm = _decode_pcm(pcm_b64)
            if len(pcm) > limit:
                raise _chunk_too_large(len(pcm), sample_rate)
            samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
            resampled = self._resampler(samples, sample_rate)
            if len(resampled):
                self._sink(resampled)

    def _admit_push(self) -> None:
        """Count a push against the per-second budget, or refuse it (it is then not counted)."""
        now = self._clock()
        self._recent = [t for t in self._recent if now - t < 1.0]
        if len(self._recent) >= self._max_pushes:
            raise ProcessingError(
                "Too many audio pushes for this session.",
                "INVALID_PARAMETER",
                hint=(
                    f"At most {self._max_pushes} pushes per second per session; "
                    "send about 100 ms of audio per push."
                ),
            )
        self._recent.append(now)


def _check_sample_rate(sample_rate) -> None:
    if (
        isinstance(sample_rate, bool)
        or not isinstance(sample_rate, int)
        or not MIN_PUSH_SAMPLE_RATE <= sample_rate <= MAX_PUSH_SAMPLE_RATE
    ):
        raise ProcessingError(
            f"sample_rate {sample_rate!r} is not supported.",
            "INVALID_PARAMETER",
            hint=(
                f"Push whole-number rates from {MIN_PUSH_SAMPLE_RATE} to {MAX_PUSH_SAMPLE_RATE} Hz "
                "(16000 is usual)."
            ),
        )


def _chunk_too_large(size: int, sample_rate: int) -> ProcessingError:
    limit = max_chunk_bytes(sample_rate)
    return ProcessingError(
        f"Audio chunk of about {size} bytes is too large.",
        "INVALID_PARAMETER",
        hint=(
            f"At {sample_rate} Hz a chunk may hold at most {limit} bytes "
            f"({MAX_CHUNK_SECONDS} s of 16-bit mono PCM); send about 100 ms per push."
        ),
    )


def _decode_pcm(pcm_b64: str) -> bytes:
    try:
        pcm = base64.b64decode(pcm_b64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ProcessingError(f"pcm_b64 is not valid base64: {e}", "INVALID_INPUT")
    if len(pcm) % _PCM_BYTES_PER_SAMPLE:
        raise ProcessingError(
            f"pcm_b64 holds {len(pcm)} bytes, not whole 16-bit samples.", "INVALID_INPUT"
        )
    return pcm


# The sources a session opens: the default when none is injected, and the one start_monitoring
# opens for source "pushed". Tests replace them with fakes or a fake clock.
server_mic_source: Callable[[], AudioSource] = SoundDeviceSource
pushed_source: Callable[[], PushedChunkSource] = PushedChunkSource
AUDIO_SOURCES = ("server_mic", "pushed")


# ---------------------------------------------------------------------------
# Phase B: Real-time monitoring
# ---------------------------------------------------------------------------

class ScoreSession:
    """Holds state for one active monitoring session."""

    def __init__(self, musicxml_str: str, part_id: str, measures: Optional[Sequence[int]] = None):
        from .utils import extract_nominal_tempo_bpm, extract_part_notes

        self.session_id = str(uuid.uuid4())
        # A cut score's timeline starts at its first selected bar; measures keep printed numbers.
        # select_measures validates the range itself, so a reversed one gets the score's bars as hint
        musicxml_str = select_measures(musicxml_str, measures)
        # Kept so an app can show the bars being practised (get_session_score).
        self.musicxml = musicxml_str
        self._first_measure = measures[0] if measures is not None else 1

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

        # The AudioSource while monitoring, None otherwise.
        self._stream: Optional[AudioSource] = None
        self._frames = PitchFrames()
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
    def tempo_bpm(self) -> float:
        """The tempo the session follows: the start() override, else the score's own."""
        return self._tempo_bpm or self._nominal_bpm

    @property
    def is_monitoring(self) -> bool:
        """True while an audio source is feeding the session."""
        return self._stream is not None

    @property
    def audio_source(self) -> Optional[AudioSource]:
        """The source feeding the session, or None when it is not monitoring."""
        with self._lock:
            return self._stream

    @property
    def measure_count(self) -> int:
        """Bars from the first one practised (bar 1, or the start of ``measures``) to the last note."""
        if not self.note_sequence:
            return 0
        return self.note_sequence[-1]["measure"] - self._first_measure + 1

    @property
    def duration_seconds(self) -> float:
        if not self.note_sequence:
            return 0.0
        return self.note_sequence[-1]["end_sec"]

    def start(self, tempo_bpm: Optional[int] = None, source: Optional[AudioSource] = None):
        """Begin pitch detection on ``source`` (default: a new ``server_mic_source()``).

        Following restarts from the first note. If the source fails to open, its
        ProcessingError propagates and the session stays loaded.
        """
        source = server_mic_source() if source is None else source
        self._note_idx = 0
        self._tempo_bpm = tempo_bpm
        self._frames = PitchFrames()
        source.start(self._feed)
        with self._lock:
            self._stream = source

    def _feed(self, chunk: np.ndarray) -> None:
        """The sink every source delivers to: analyse the chunk and update the position."""
        for freq, confidence, elapsed_sec in self._frames.feed(chunk):
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
                # Before any singing: the first note (a session always has one).
                first = self.note_sequence[0]
                return {
                    "session_id": self.session_id,
                    "measure": first["measure"],
                    "beat": first["beat"],
                    "expected_note": first["note_name"],
                    "sung_pitch_hz": None,
                    "accuracy_cents": None,
                    "status": "no_signal",
                }
            return {"session_id": self.session_id, **self._current_position}

    def stop(self) -> dict:
        """Stop the audio source and return a session summary."""
        from .aligner import summarize

        # Take the source under the lock, so a reaper and a stop_monitoring call racing each
        # other close it only once.
        with self._lock:
            source, self._stream = self._stream, None

        if source is not None:
            # close() runs even if stop() fails, so the device and worker are released.
            for step in (source.stop, source.close):
                try:
                    step()
                except Exception as e:
                    logger.warning("Error closing audio stream: %s", e)
            # No audio outlives the take (microphone privacy, proposal §7).
            self._frames = PitchFrames()

        with self._lock:
            history = list(self._history)

        # An empty history gives zero counts and no highlights.
        return {"session_id": self.session_id, "summary": summarize(history)}


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


def load_score(musicxml_str: str, part_id: str, measures: Optional[Sequence[int]] = None) -> dict:
    """Load a reference score and create a new session.

    ``measures`` ([start, end], printed numbers) practises only those bars: the session's
    timeline starts at ``start`` and positions keep the printed measure numbers.

    Returns:
        {
            "session_id": "...",
            "part_id": "P1",            # stable MusicXML score-part id
            "part_name": "Soprano",
            "measure_count": 32,
            "duration_seconds": 142.0,
        }
    """
    session = ScoreSession(musicxml_str, part_id, measures)
    _registry.add(session)
    _ensure_reaper()

    return {
        "session_id": session.session_id,
        "part_id": session.part_id,
        "part_name": session.part_name,
        "measure_count": session.measure_count,
        "duration_seconds": round(session.duration_seconds, 2),
    }


def start_monitoring(session_id: str, tempo_bpm: Optional[int] = None, source: str = "server_mic") -> dict:
    """Start monitoring a session from the server microphone, or from audio the app pushes.

    ``source="pushed"`` opens a PushedChunkSource fed by ``push_audio_chunk``; its result also
    names the source. The server-mic result is unchanged.
    """
    if source not in AUDIO_SOURCES:
        raise ProcessingError(
            f"Unknown audio source {source!r}.",
            "INVALID_PARAMETER",
            hint=(
                "source is 'server_mic' (this machine's microphone) or 'pushed' "
                "(the Practice Coach sends the browser's audio)."
            ),
            choices=list(AUDIO_SOURCES),
        )
    session = _active_session(session_id)
    if source == "pushed":
        session.start(tempo_bpm=tempo_bpm, source=pushed_source())
    else:
        session.start(tempo_bpm=tempo_bpm)  # the session's default: the server microphone
    _registry.touch(session_id)
    result = {"status": "started", "session_id": session_id}
    return {**result, "source": "pushed"} if source == "pushed" else result


def push_audio_chunk(session_id: str, pcm_b64: str, sample_rate: int) -> dict:
    """Feed one chunk of browser audio to a pushed session; return the position it leads to.

    Counts as activity. Raises SESSION_NOT_FOUND for a closed session, INVALID_PARAMETER for a
    session not listening for pushed audio or a chunk over the limits, INVALID_INPUT for PCM
    that does not decode.
    """
    session = _active_session(session_id)
    source = session.audio_source
    if not isinstance(source, PushedChunkSource):
        state = "listens to the server microphone" if source is not None else "is not listening yet"
        raise ProcessingError(
            f"Session '{session_id}' {state}; it takes no pushed audio.",
            "INVALID_PARAMETER",
            hint="Call start_monitoring with source 'pushed' before pushing audio.",
        )
    source.push(pcm_b64, sample_rate)
    return session.get_position()


def start_practice(
    musicxml_str: str,
    part_id: str,
    tempo_bpm: Optional[int] = None,
    measures: Optional[Sequence[int]] = None,
) -> dict:
    """load_score + start_monitoring in one call; their fields together (session_id once).

    If the microphone fails to open, the session just loaded is discarded before the error is
    raised, so no orphan session is left behind.
    """
    loaded = load_score(musicxml_str, part_id, measures)
    try:
        started = start_monitoring(loaded["session_id"], tempo_bpm)
    except Exception:
        _discard(loaded["session_id"])
        raise
    return {**loaded, **started}


def describe_session(session_id: str) -> dict:
    """An open session's facts for an app: ids, size and the tempo it follows.

    Not counted as activity; callers have just opened or used the session.
    """
    session = _registry.get(session_id)
    if session is None:
        raise _session_not_found(session_id)
    return {
        "session_id": session.session_id,
        "part_id": session.part_id,
        "part_name": session.part_name,
        "measure_count": session.measure_count,
        "duration_seconds": round(session.duration_seconds, 2),
        "tempo_bpm": session.tempo_bpm,
    }


def get_session_score(session_id: str) -> dict:
    """The MusicXML an open session practises (cut to ``measures`` if it was)."""
    session = _active_session(session_id)
    return {"session_id": session.session_id, "musicxml": session.musicxml}


def _discard(session_id: str) -> None:
    """Remove a session and release whatever its failed start left open."""
    session = _registry.remove(session_id)
    if session is not None:
        try:
            session.stop()
        except Exception as e:
            logger.warning("Error discarding session %s: %s", session_id, e)


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
