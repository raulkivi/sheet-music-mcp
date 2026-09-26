# pitch-mcp — Technical Architecture

## Overview

pitch-mcp is the most complex server in the sheet-music-mcp pipeline. It has two modes of operation:

- **Phase A — Offline analysis:** accepts a pre-recorded WAV file and a reference MusicXML score; returns a per-note pitch accuracy report
- **Phase B — Real-time monitoring:** opens the microphone, tracks the singer's position in the score live, and reports pitch accuracy on demand via polling

The server is stateful in Phase B: sessions are stored in a module-level dictionary for the lifetime of the process.

---

## Component Diagram

```
┌───────────────────────────────────────────────────────────┐
│                      MCP Client                           │
└──────────────────────────┬────────────────────────────────┘
                           │  stdio (JSON-RPC)
┌──────────────────────────▼────────────────────────────────┐
│                       server.py                           │
│                                                           │
│  list_tools()         → 6 tool definitions               │
│  call_tool()          → dispatches to engine             │
│  _active_backend()    → reads PITCH_BACKEND env var      │
│  _check_microphone()  → queries sounddevice devices      │
└──────────┬────────────────────────────────────────────────┘
           │
     ┌─────┴─────────────────────────────────────────┐
     │                   engine.py                    │
     │                                               │
     │  ── Phase A (offline) ─────────────────────── │
     │  analyze_recording()                          │
     │                                               │
     │  ── Phase B (real-time) ───────────────────── │
     │  ScoreSession                                  │
     │    start() / get_position() / stop()           │
     │  load_score() / start_monitoring()             │
     │  get_position() / stop_monitoring()            │
     │  _sessions: dict[str, ScoreSession]            │
     └─────┬─────────────────┬─────────────────────┘
           │                 │
  ┌────────▼──────┐  ┌───────▼──────────────────────────┐
  │pitch_detector │  │           utils.py               │
  │               │  │                                  │
  │detect_pitches │  │  extract_note_sequence()         │
  │_detect_librosa│  │  _build_metronome_map()          │
  │_detect_crepe  │  │  _offset_to_seconds()            │
  └────────┬──────┘  │  hz_to_note()                   │
           │         │  note_name_to_hz()               │
  ┌────────▼──────┐  │  classify_accuracy()             │
  │   aligner.py  │  │  validate_audio_path()           │
  │               │  │  validate_musicxml()             │
  │  align()      │  └──────────────────────────────────┘
  │  summarize()  │
  │  _hz_to_      │
  │   cents_dev() │
  │  _classify()  │
  └───────────────┘

  ─── Python libraries ───────────────────────────────────
  librosa (pYIN)    sounddevice      music21     numpy/scipy
```

---

## Module Responsibilities

### `server.py`

MCP protocol layer. Contains no analysis logic.

- Registers six tools: `analyze_recording`, `load_score`, `start_monitoring`, `get_current_position`, `stop_monitoring`, `list_capabilities`
- Reads `PITCH_BACKEND` environment variable; defaults to `"librosa"`
- Checks microphone availability via `sounddevice.query_devices()`
- Converts engine results and `ProcessingError` exceptions to `TextContent` JSON
- Entry point via `mcp.server.stdio.stdio_server()`

### `engine.py`

Session management and offline analysis orchestration.

**Phase A:**

| Function | Description |
|----------|-------------|
| `analyze_recording(audio_path, musicxml_str, part_id)` | Full offline pipeline: validate → extract notes → detect pitches → align → summarize |

**Phase B:**

| Class / Function | Description |
|-----------------|-------------|
| `ScoreSession` | One active monitoring session (UUID, note sequence, audio stream, worker thread) |
| `ScoreSession.start(tempo_bpm)` | Open sounddevice stream; spawn worker thread |
| `ScoreSession.get_position()` | Thread-safe read of current position dict |
| `ScoreSession.stop()` | Close stream; join worker thread; return summary |
| `ScoreSession._worker_loop(sr, hop)` | Background thread: buffer audio → YIN pitch → `_process_pitch_frame` |
| `ScoreSession._process_pitch_frame(freq, confidence, elapsed_sec)` | Per-frame update: tempo-scale elapsed time, pick the current note via `_find_best_note_index`, update `_current_position` and append to `_history` |
| `ScoreSession._find_best_note_index(score_time, freq_hz)` | Audio-driven note selection: best pitch match among plausible upcoming notes, with a timeline fallback |
| `load_score(musicxml, part_id)` | Create ScoreSession; store in `_sessions`; return session_id |
| `start_monitoring(session_id, tempo_bpm)` | Call session.start() |
| `get_position(session_id)` | Call session.get_position() |
| `stop_monitoring(session_id)` | Call session.stop(); remove from `_sessions` |

### `pitch_detector.py`

Pitch detection from audio files.

| Function | Description |
|----------|-------------|
| `detect_pitches(audio_path)` | Dispatch to librosa or crepe backend |
| `_detect_librosa(audio_path)` | librosa pYIN pitch detection; returns voiced frames only |
| `_detect_crepe(audio_path)` | crepe CNN pitch detection (optional; requires TensorFlow) |
| `get_backend()` | Return `PITCH_BACKEND` env var or `"librosa"` |

### `aligner.py`

Maps detected pitch sequence against the reference note sequence.

| Function | Description |
|----------|-------------|
| `align(detected, note_sequence)` | DTW (dtaidistance) pitch-space alignment, gated by per-note temporal plausibility; per-note accuracy |
| `summarize(results)` | Aggregate: measures covered, average cents, histogram |
| `_hz_to_cents_deviation(sung, expected)` | `1200 * log2(sung / expected)` |
| `_classify(cents, threshold=25)` | `"on_pitch"` / `"sharp"` / `"flat"` |

### `utils.py`

Score parsing, time conversion, and validation.

| Function | Description |
|----------|-------------|
| `extract_note_sequence(musicxml, part_id)` | Parse score; build time-stamped note list |
| `_build_metronome_map(score)` | List of `(offset_ql, sec_per_ql)` from MetronomeMarks |
| `_offset_to_seconds(offset_ql, map)` | Convert score offset (quarter notes) to wall-clock seconds |
| `_offset_to_measure_beat(element, part)` | Extract `(measure_number, beat)` from element context |
| `hz_to_note(hz)` | Convert Hz to `(note_name, cents_deviation)` |
| `note_name_to_hz(name)` | Convert `"A4"` → 440.0 Hz |
| `classify_accuracy(cents, threshold)` | `"on_pitch"` / `"sharp"` / `"flat"` |
| `validate_audio_path(path)` | Exists; `.wav` extension |
| `validate_musicxml(xml)` | Non-empty; contains score element |
| `validate_session_id(sid)` | Non-empty string |

---

## Phase A: Offline Analysis Data Flow

```
analyze_recording(audio_path, musicxml_str, part_id)
  │
  ├─ validate audio file exists + is .wav
  │
  ├─ utils.extract_note_sequence(musicxml_str, part_id)
  │     ├─ music21.converter.parseData(musicxml)
  │     ├─ find part where part.id == part_id
  │     ├─ _build_metronome_map(score)
  │     │     └─ extract all MetronomeMarks, sort by offset
  │     └─ for each Note in part (skip Rests, take highest pitch of Chord):
  │           offset_ql  = note.offset
  │           start_sec  = _offset_to_seconds(offset_ql, map)
  │           end_sec    = _offset_to_seconds(offset_ql + note.duration.quarterLength, map)
  │           measure, beat = _offset_to_measure_beat(note, part)
  │           emit: {note_name, freq_hz, start_sec, end_sec, measure, beat, midi}
  │
  ├─ pitch_detector.detect_pitches(audio_path)
  │     └─ librosa.load(audio_path, sr=None, mono=True)
  │     └─ librosa.pyin(y,
  │             fmin=librosa.note_to_hz("C2"),   ← 65 Hz
  │             fmax=librosa.note_to_hz("C7"),   ← 2093 Hz
  │             sr=sr,
  │             hop_length=512
  │        )
  │     → (f0_array, voiced_flag_array, voiced_prob_array)
  │     → filter: voiced=True, freq>0, not NaN
  │     → return [(time_sec, freq_hz, confidence), ...]
  │
  ├─ aligner.align(detected_pitches, note_sequence)
  │     ├─ ref_midis  = [note.midi for note in note_sequence]
  │     ├─ query_midi = hz_to_midi_continuous(detected freqs)
  │     ├─ path = dtaidistance.dtw.warping_path(ref_midis, query_midi, window=50)
  │     │      ← pitch-optimal monotonic mapping; a frame near a note
  │     │        boundary goes to whichever neighbor it matches in pitch,
  │     │        not whichever neighbor's fixed time window it falls in.
  │     │        This is what makes alignment tolerant of real tempo
  │     │        drift/rubato (a fixed ±10% window silently assumed the
  │     │        singer never strayed from the score's nominal tempo).
  │     └─ for each ref_note, frames := query frames DTW assigned to it:
  │           margin = max(0.15, 0.75 * (end_sec - start_sec))
  │           if median(frame.time for frame in frames) not in
  │              [start_sec - margin, end_sec + margin]:
  │               status = "no_signal"   ← DTW always assigns every note at
  │                                         least one frame; this gate catches
  │                                         notes the singer never attempted
  │           else:
  │               sung_hz = median(frame.freq for frame in frames)
  │               cents   = _hz_to_cents_deviation(sung_hz, ref_note.freq_hz)
  │               status  = _classify(cents, threshold=25)
  │           emit: {measure, beat, expected, sung_hz, accuracy_cents, status}
  │
  ├─ aligner.summarize(results)
  │     ├─ measures_covered = len({r.measure for r in results})
  │     ├─ avg_accuracy_cents = mean(abs(r.accuracy_cents) for r if status != "no_signal")
  │     └─ histogram: count on_pitch, sharp, flat, no_signal
  │
  └─ return {measures_covered, avg_accuracy_cents, note_accuracy: [...], accuracy_histogram}
```

---

## Phase B: Real-Time Monitoring Architecture

### Session Lifecycle

```
load_score(musicxml, part_id)
  → create ScoreSession(musicxml, part_id)
       ├─ session_id = str(uuid4())
       └─ note_sequence = extract_note_sequence(musicxml, part_id)
  → _sessions[session_id] = session
  → return {session_id, part_name, measure_count, duration_seconds}

start_monitoring(session_id, tempo_bpm)
  → session = _sessions[session_id]
  → session.start(tempo_bpm)
       ├─ open sounddevice.InputStream(
       │       samplerate=22050,
       │       channels=1,
       │       blocksize=512,
       │       callback=_audio_callback
       │  )
       ├─ spawn threading.Thread(target=_worker_loop)
       └─ stream.start()
  → return {status: "started"}

get_current_position(session_id)
  → session._lock.acquire()
  → return copy of session._current_position
  → session._lock.release()

stop_monitoring(session_id)
  → session.stop()
       ├─ stream.stop(); stream.close()
       ├─ _stop_event.set()
       ├─ worker_thread.join()
       └─ build summary from accumulated results
  → del _sessions[session_id]
  → return {session_id, summary}
```

### Worker Thread (YIN Autocorrelation)

```
_worker_loop(sample_rate=22050, hop_size=512):
  buffer = np.zeros(2048)    ← rolling audio window

  while not _stop_event.is_set():
    chunk = _audio_queue.get(timeout=0.1)  ← non-blocking
    buffer = np.roll(buffer, -len(chunk))
    buffer[-len(chunk):] = chunk

    ── YIN autocorrelation ──────────────────────────────
    half = len(buffer) // 2
    d = [sum((buf[:half] - buf[tau:tau+half])**2)
         for tau in range(1, half)]       ← difference function
    cmnd = d[tau] * tau / sum(d[1:tau+1]) ← cumulative mean normalized
    tau_est = first tau where cmnd[tau] < 0.15
    ── parabolic interpolation for sub-sample accuracy ──
    freq = sample_rate / tau_est

    _process_pitch_frame(freq, confidence, elapsed_sec)
```

`_process_pitch_frame` is what makes position tracking audio-driven rather than
a wall-clock pointer:

```
_process_pitch_frame(freq_hz, confidence, elapsed_sec):
  if freq_hz invalid/unvoiced:
    current_position.status = "no_signal"; return

  score_time = elapsed_sec
  if tempo_bpm override set:
    score_time *= tempo_bpm / nominal_bpm   ← IR-4: singer-chosen tempo,
                                                not the score's written one

  note_idx = _find_best_note_index(score_time, freq_hz)
    ├─ scan note_sequence[_note_idx : _note_idx + 1 + lookahead(4)]
    ├─ stop scanning once a candidate's start_sec is implausibly far
    │  ahead of score_time (> score_time + 1.0s)
    ├─ pick whichever candidate's expected pitch is closest to freq_hz
    │  ← this is the audio-driven part: the sung pitch decides which
    │    note is current, not just elapsed time
    └─ if even the best match is a poor one (>150 cents off), fall back
       to whatever note the timeline says we should be on, so a missed
       note doesn't stall position forever
  _note_idx = note_idx   ← never moves backward

  ref_note = note_sequence[note_idx]
  cents = hz_to_cents_deviation(freq_hz, ref_note.freq_hz)
  status = classify_accuracy(cents)

  with _lock:
    _current_position = {
      measure: ref_note.measure,
      beat: ref_note.beat,
      expected_note: ref_note.note_name,
      sung_pitch_hz: freq_hz,
      accuracy_cents: cents,
      status: status
    }
    _history.append(_current_position)   ← consumed by stop()'s summary
```

**The audio callback is minimal** — it only puts chunks into `_audio_queue` and returns immediately. All computation happens in the worker thread, keeping the PortAudio callback deadline-safe.

---

## Pitch Detection Algorithms

### Primary: librosa pYIN (offline)

Probabilistic YIN — a state-of-the-art algorithm for singing voice pitch tracking.

```python
f0, voiced_flag, voiced_prob = librosa.pyin(
    y,
    fmin=librosa.note_to_hz("C2"),   # 65 Hz (low bass)
    fmax=librosa.note_to_hz("C7"),   # 2093 Hz (high soprano)
    sr=sr,
    hop_length=512                    # ~23 ms frame step at 22050 Hz
)
```

Returns one frequency estimate per hop. Only voiced (singing) frames are returned; unvoiced/silent frames are filtered.

### Real-time: YIN autocorrelation (Phase B)

Simple YIN with parabolic interpolation. Runs entirely in the worker thread with no external library dependencies.

**Why not pYIN for real-time?** librosa.pyin is batch-only (processes entire files). The real-time worker uses the simpler YIN algorithm which operates on short rolling windows.

### Optional: crepe (requires manual install)

A CNN-based pitch detector with excellent accuracy in noisy environments. Requires TensorFlow (~500 MB). Not installed by default because `pkg_resources` is missing from the build environment and the download is large.

```python
time, frequency, confidence, _ = crepe.predict(audio, sr, viterbi=True)
# filter by confidence >= 0.5
```

---

## Frequency / Note Conversion

All pitch arithmetic uses semitones and cents relative to A4 = 440 Hz:

```
MIDI float:    midi = 69 + 12 * log2(hz / 440)
Nearest MIDI:  midi_int = round(midi)
Cents dev:     cents = round(1200 * (midi - midi_int))
Note name:     MIDI_NAMES[midi_int % 12] + str(midi_int // 12 - 1)

Cents deviation between sung and expected:
  cents = round(1200 * log2(sung_hz / expected_hz))
```

Accuracy classification threshold: ±25 cents = `"on_pitch"`.

---

## Metronome Map and Time Conversion

To align score positions (in quarter-note offsets) with wall-clock seconds, a metronome map is built from all `MetronomeMark` objects in the score:

```
metronome_map = [
  (offset=0.0,  sec_per_ql=0.50),   ← 120 BPM
  (offset=32.0, sec_per_ql=0.40),   ← 150 BPM (tempo change)
  ...
]

def _offset_to_seconds(offset_ql, map):
  t = 0.0
  for i, (seg_start, sec_per_ql) in enumerate(map):
    seg_end = map[i+1].offset if i+1 < len(map) else inf
    if offset_ql <= seg_end:
      t += (offset_ql - seg_start) * sec_per_ql
      return t
    else:
      t += (seg_end - seg_start) * sec_per_ql
```

---

## Session State and Thread Safety

```
_sessions: dict[str, ScoreSession]     ← module-level
_sessions_lock: threading.Lock          ← protects dict access

ScoreSession:
  session_id: str                  (UUID4)
  note_sequence: list[dict]        (immutable after load)
  _stream: sounddevice.InputStream (Phase B only)
  _worker: threading.Thread        (Phase B only)
  _audio_queue: queue.Queue        (audio chunks)
  _stop_event: threading.Event     (signals worker to exit)
  _current_position: dict          (latest position, mutated by worker)
  _lock: threading.Lock            (guards _current_position/_history)
  _history: list[dict]             (every processed frame's position; feeds stop()'s summary)
  _note_idx: int                   (causal position pointer; never moves backward)
  _nominal_bpm: float              (score's own tempo, from its first MetronomeMark)
  _tempo_bpm: int | None           (start()'s override; scales elapsed time into score-time)
```

`_current_position` is written only by the worker thread and read by `get_position()` (called from the MCP handler). Access is guarded by `_lock` to prevent torn reads.

---

## Error Handling

```json
{"error": "<message>", "error_code": "<CODE>"}
```

| Scenario | Code |
|----------|------|
| Audio file not found | `FILE_NOT_FOUND` |
| Non-WAV audio format | `UNSUPPORTED_FORMAT` |
| MusicXML parse failure | `INVALID_INPUT` |
| Part name not found | `INVALID_PARAMETER` |
| Unknown session ID | `SESSION_NOT_FOUND` |
| Microphone unavailable / access denied | `PROCESSING_FAILED` |
| No pitch detected in recording | `PROCESSING_FAILED` |

---

## Key Dependencies

| Package | Role |
|---------|------|
| `librosa` ≥0.10 | pYIN offline pitch detection |
| `sounddevice` ≥0.4 | Real-time microphone input (requires `libportaudio2`) |
| `music21` ≥9.0 | MusicXML parsing, note sequence extraction |
| `dtaidistance` | Windowed DTW for `aligner.align()` |
| `numpy` ≥1.24 | Audio buffers, DSP arithmetic |
| `scipy` ≥1.10 | WAV file reading (crepe backend) |
| `mcp` | MCP protocol SDK |

`crepe` (optional): CNN pitch detection. Manual install only. Requires TensorFlow.

---

## File Layout

```
pitch-mcp/
├── pyproject.toml
├── src/
│   └── pitch_mcp/
│       ├── __init__.py
│       ├── server.py          ← MCP layer (tool registration, dispatch)
│       ├── engine.py          ← Session management, offline analysis orchestration
│       ├── pitch_detector.py  ← librosa / crepe pitch detection
│       ├── aligner.py         ← Time-domain alignment, accuracy classification
│       └── utils.py           ← Note sequence extraction, Hz↔note, metronome map
└── tests/
    ├── conftest.py         ← skips @integration/@manual unless requested via -m
    ├── test_server.py
    ├── test_engine.py
    ├── test_pitch_detector.py
    ├── test_aligner.py
    ├── test_utils.py
    ├── test_integration.py ← @pytest.mark.integration, runs against the fixture pair
    ├── test_manual.py      ← @pytest.mark.manual, requires a real microphone
    └── fixtures/
        ├── soprano_phrase.wav   ← synthetic (sine-tone) proxy, not a real recording
        └── reference.musicxml
```
