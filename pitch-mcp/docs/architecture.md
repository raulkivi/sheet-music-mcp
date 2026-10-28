# pitch-mcp — Technical Architecture

## Overview

pitch-mcp is the most complex server in the sheet-music-mcp pipeline. It has two modes of operation:

- **Phase A — Offline analysis:** accepts a pre-recorded WAV file and a reference MusicXML score; returns a per-note pitch accuracy report
- **Phase B — Real-time monitoring:** opens the microphone, tracks the singer's position in the score live, and reports pitch accuracy on demand via polling

The server is stateful in Phase B: sessions live in a module-level `SessionRegistry` until they are stopped, the idle timeout closes them (`PITCH_SESSION_IDLE_MINUTES`, default 10), or the process ends.

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
│  list_tools()         → 12 tool definitions              │
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
     │  AudioSource: SoundDeviceSource (server mic)   │
     │               PushedChunkSource (browser mic)  │
     │  PitchFrames (rolling YIN, one frame per hop)  │
     │  ScoreSession                                  │
     │    start(source) / get_position() / stop()     │
     │  load_score() / start_monitoring(source)       │
     │  push_audio_chunk() (app-only, pushed mode)    │
     │  start_practice() (= both, no orphan on error) │
     │  get_position() / stop_monitoring()            │
     │  list_sessions()                               │
     │  _registry: SessionRegistry (+ Reaper thread)  │
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
  │  highlights() │
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

- Registers twelve tools: `analyze_recording`, `load_score`, `start_practice`, `describe_score` (shared, from `sheet_music_mcp_core.references`), `start_monitoring` (`source: server_mic | pushed`), `get_current_position`, `stop_monitoring`, `list_sessions`, `get_score_for_session` (app-only), `push_audio_chunk` (app-only), `list_capabilities`, `health_check`
- MCP Apps: `PRACTICE_COACH` (`ui://pitch/practice-coach`) in a `UiRegistry` over `PackageAssetSource("pitch_mcp")`, served with `make_resource_handlers`; `meta_for()` drops the link while the HTML is not packaged. `call_tool_result()` returns `CallToolResult` for the tools in `_RESULT_TOOLS` (the six structured ones, plus `start_monitoring`, `stop_monitoring` and `list_sessions`, whose errors set `isError` through `_text_result`), `call_tool()` keeps returning the content blocks
- `analyze_recording`, `load_score` and `start_practice` take `measures` (`MEASURES_PROPERTY` from `sheet_music_mcp_core.measures`); `_measures(arguments)` passes it to the engine only when given, so calls without it are unchanged
- Resolves the score of `analyze_recording`, `load_score` and `start_practice` with `_reference_score()`: the core's `references.load_score()` (inline `musicxml`, or `musicxml_path` confined to the read roots, `.mxl` unpacked) followed by the same `validate_musicxml()` check inline text always had. The engine still receives MusicXML text, so it is unchanged
- `call_tool(name, arguments, ctx=None)` is wired with `make_handlers(..., pass_context=True)` so `load_score` can ask the client for its MCP roots
- Reads `PITCH_BACKEND` environment variable; defaults to `"librosa"`
- Checks microphone availability via `sounddevice.query_devices()`
- Converts engine results and `ProcessingError` exceptions to `TextContent` JSON
- Entry point via `mcp.server.stdio.stdio_server()`

### `presenter.py`

Turns engine results into `(content, structured_content)` for the Practice Coach tools. `content`
is the JSON text the tools always returned; `structured_content` carries the same data (for the
session openers, `engine.describe_session()`, which adds `tempo_bpm`). Output schemas live here.
No engine logic. `present_pushed_position()` gives `push_audio_chunk` the position snapshot as
`structured_content` and one short line of text, never the audio.

### `engine.py`

Session management and offline analysis orchestration.

**Phase A:**

| Function | Description |
|----------|-------------|
| `analyze_recording(audio_path, musicxml_str, part_id, measures=None)` | Full offline pipeline: validate → cut to `measures` → extract notes → detect pitches → align → summarize (with highlights) |
| `_select(musicxml_str, measures)` | `select_measures(text, measures)`; unchanged text for `None`, `INVALID_PARAMETER` + hint for a bad range |

**Phase B:**

| Class / Function | Description |
|-----------------|-------------|
| `AudioSource` (protocol) | Where a session's audio comes from: `start(sink)` delivers mono float32 chunks at 22 050 Hz to `sink`, `stop()`, `close()` (both idempotent). Raises `ProcessingError` if it cannot open |
| `SoundDeviceSource` | Server microphone (option A): `sd.InputStream(22050 Hz, mono, float32, blocksize 512)`; the callback only queues blocks, a daemon worker hands them to the sink. A stream that opened but failed to start is closed before the error |
| `PushedChunkSource(clock, max_pushes_per_second)` | Browser microphone (option B): `push(pcm_b64, sample_rate)` checks the limits, decodes 16-bit LE PCM, resamples (`_LinearResampler`, streaming, continuous across chunks) and calls the sink on the caller's thread |
| `server_mic_source`, `pushed_source` | Module-level factories (dependency inversion); tests replace them |
| `PitchFrames` | The analysis every source feeds: a 2048-sample rolling window, one `(freq, confidence, elapsed_sec)` per 512-sample hop, elapsed = hops × 512 / 22 050 (audio time) |
| `_yin_pitch(buf, sr)` | YIN: difference function, CMND, first dip below 0.15, walk down to its minimum, parabolic interpolation |
| `ScoreSession(musicxml, part_id, measures=None)` | One active monitoring session (UUID, note sequence, audio source). Cuts the score to `measures` first; `measure_count` = last note's measure − first practised bar (`measures[0]`, else 1) + 1 |
| `ScoreSession.start(tempo_bpm, source=None)` | Fresh `PitchFrames`; `source.start(self._feed)` (default `server_mic_source()`); the session keeps the source only once it started |
| `ScoreSession._feed(chunk)` | The sink: `PitchFrames.feed` → `_process_pitch_frame` per frame |
| `ScoreSession.audio_source`, `is_monitoring` | The started source (None when loaded); monitoring = a source is set |
| `ScoreSession.get_position()` | Thread-safe read of current position dict; before any pitch, the first note's measure, beat and name |
| `ScoreSession.stop()` | Take the source under the lock; `stop()` then `close()` (each attempted); drop the analysis window; return summary |
| `ScoreSession._process_pitch_frame(freq, confidence, elapsed_sec)` | Per-frame update: tempo-scale elapsed time, pick the current note via `_find_best_note_index`, update `_current_position` and append to `_history` |
| `ScoreSession._find_best_note_index(score_time, freq_hz)` | Audio-driven note selection: best pitch match among plausible upcoming notes, with a timeline fallback |
| `SessionRegistry` | Open sessions, their last-activity times and the timed-out summaries; `add`, `get`, `touch`, `remove`, `list`, `reap(now)`, `expired_minutes`, `pop_expired`. Injected `clock` (default `time.monotonic`) |
| `Reaper` | Daemon thread: `registry.reap(clock())` every 30 s; injected `sleep` and `stop_event` |
| `idle_minutes_from_env()` | Parse `PITCH_SESSION_IDLE_MINUTES` (default 10, `0` = off, invalid → warning + 10) |
| `load_score(musicxml, part_id, measures=None)` | Create ScoreSession; `_registry.add`; start the reaper on first use; return session_id |
| `start_monitoring(session_id, tempo_bpm, source="server_mic")` | Unknown `source` → `INVALID_PARAMETER`; `_registry.touch`; `session.start(tempo_bpm)` (server mic) or `session.start(tempo_bpm, source=pushed_source())`; touch again. A pushed result adds `source: "pushed"` |
| `push_audio_chunk(session_id, pcm_b64, sample_rate)` | `_registry.touch`; the session's source must be a `PushedChunkSource` (else `INVALID_PARAMETER`); `source.push(...)`; return `session.get_position()` |
| `start_practice(musicxml, part_id, tempo_bpm=None, measures=None)` | `load_score` then `start_monitoring`; their fields merged. If starting fails, `_discard` removes and stops the session, then the error is re-raised |
| `get_position(session_id)` | `_registry.touch`; session.get_position() |
| `stop_monitoring(session_id)` | `_registry.remove` + session.stop() (`timed_out: false`), else the timed-out summary (`timed_out: true`), else `SESSION_NOT_FOUND` |
| `list_sessions()` | `{idle_timeout_minutes, sessions: _registry.list()}` |

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
| `summarize(results)` | Aggregate: measures covered, average cents, histogram, `highlights(results)` |
| `highlights(results, *, threshold=25, min_run=2, limit=3)` | Merge consecutive entries of one note (same measure, beat and `expected` / `expected_note`) into its median cents; runs of ≥ `min_run` notes all flat or all sharp (no_signal or on-pitch ends a run); top `limit` by notes × \|avg cents\| as `{direction, measures, notes, avg_cents, text}` |
| `_hz_to_cents_deviation(sung, expected)` | `1200 * log2(sung / expected)` |
| `_classify(cents, threshold=25)` | `"on_pitch"` / `"sharp"` / `"flat"` |

### `utils.py`

Score parsing, time conversion, and validation.

| Function | Description |
|----------|-------------|
| `extract_part_notes(musicxml, part)` | Parse score; resolve the part (ID, name or voice) by position against stable MusicXML IDs; return `(PartInfo, notes)` |
| `extract_note_sequence(musicxml, part)` | Notes only (`extract_part_notes(...)[1]`) |
| `_build_metronome_map(score)` | List of `(offset_ql, sec_per_ql)` from MetronomeMarks: `number`, else `numberSounding` (a bare `<sound tempo>`, which is how `select_measures` carries the tempo into a cut score), else 120 |
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
analyze_recording(audio_path, musicxml_str, part_id, measures=None)
  │
  ├─ validate audio file exists + is .wav
  │
  ├─ _select(musicxml_str, measures)       ← core select_measures: only bars start..end,
  │                                           with the key/time/clef/tempo in force at start
  │
  ├─ utils.extract_part_notes(musicxml_str, part_id)
  │     ├─ music21.converter.parseData(musicxml)
  │     ├─ resolve_part(part_id, music21_part_infos(score.parts))  never music21's part.id
  │     │     └─ PartSelectionError (INVALID_PARAMETER + choices) if unknown or ambiguous
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
  │     ├─ histogram: count on_pitch, sharp, flat, no_signal
  │     └─ highlights(results): worst ≤ 3 runs of ≥ 2 flat or sharp notes, in plain words
  │
  └─ return {measures_covered, avg_accuracy_cents, note_accuracy: [...], accuracy_histogram, highlights}
```

---

## Phase B: Real-Time Monitoring Architecture

### Session Lifecycle

```
load_score(musicxml, part_id, measures=None)
  → create ScoreSession(musicxml, part_id, measures)
       ├─ session_id = str(uuid4())
       ├─ musicxml = select_measures(musicxml, measures)   ← timeline starts at start
       └─ info, note_sequence = extract_part_notes(musicxml, part_id)
  → _registry.add(session)            ← creation counts as activity
  → _ensure_reaper()                  ← first call starts the Reaper thread (not if timeout = 0)
  → return {session_id, part_id, part_name, measure_count, duration_seconds}

start_monitoring(session_id, tempo_bpm, source="server_mic")
  → session = _registry.touch(session_id)   ← activity
  → session.start(tempo_bpm[, source=pushed_source()])
       ├─ _frames = PitchFrames()
       ├─ source.start(sink=session._feed)
       │    SoundDeviceSource: open sounddevice.InputStream(
       │       samplerate=22050, channels=1, blocksize=512, callback=_audio_callback)
       │       stream.start(); spawn the worker thread (queue → sink)
       │    PushedChunkSource: remember the sink; audio arrives with push_audio_chunk
       └─ session._stream = source        ← only once it started
  → return {status: "started", session_id[, source: "pushed"]}

push_audio_chunk(session_id, pcm_b64, sample_rate)      ← app-only, pushed sessions
  → session = _registry.touch(session_id)   ← activity
  → source = session.audio_source; not a PushedChunkSource → INVALID_PARAMETER
  → source.push(pcm_b64, sample_rate)       ← under the source's lock, on the handler's thread
       ├─ sample_rate in 8000..48000, base64 length ≤ the byte limit, ≤ 25 pushes in the last second
       ├─ base64 → int16 LE → float32 / 32768
       ├─ _LinearResampler → 22050 Hz
       └─ sink(samples) = session._feed → PitchFrames → _process_pitch_frame
  → return session.get_position()           ← already reflects this chunk

start_practice(musicxml, part_id, tempo_bpm, measures)
  → loaded = load_score(musicxml, part_id, measures)
  → started = start_monitoring(loaded.session_id, tempo_bpm)
       on any error: _discard(session_id)  ← _registry.remove + session.stop(); no orphan
  → return {**loaded, **started}

get_current_position(session_id)
  → session = _registry.touch(session_id)   ← activity
  → session._lock.acquire()
  → return copy of session._current_position
  → session._lock.release()

stop_monitoring(session_id)
  → session = _registry.remove(session_id)
  → session.stop()
       ├─ take _stream (the source) under session._lock (safe if the reaper races us)
       ├─ source.stop(); source.close()   ← SoundDeviceSource: stop event, stream stop/close, join worker
       ├─ _frames = PitchFrames()          ← no audio outlives the take
       └─ summarize(history): counts plus highlights (history has one entry per frame)
  → return {session_id, summary, timed_out: false}
  (not open but timed out < 1 h ago → return the stored summary with timed_out: true, once)
```

### Idle Timeout (Registry and Reaper)

```
Reaper thread (daemon, started by the first load_score)
  loop:
    sleep(30 s)                      ← default: stop_event.wait, so stop() wakes it at once
    if stop_event set: exit
    registry.reap(clock())

SessionRegistry.reap(now)
  with registry lock:
    drop _expired entries older than 1 h
    if idle_minutes == 0: return []
    idle = sessions with now − last_active > idle_minutes × 60
    move each from _sessions to _expired[sid] = (now, idle_minutes, session)
  without the lock (streams close slowly; tool calls are not held up):
    result = session.stop()          ← closes the microphone stream, joins the worker
    _expired[sid].result = result    ← the session object itself is dropped
```

- **Activity** is creation, `start_monitoring` and `get_current_position` (`touch`). Loaded but
  never started sessions expire too.
- **After a reap**, `get_current_position` and `start_monitoring` raise `SESSION_NOT_FOUND` with a
  `hint` ("timed out after N minutes idle; call stop_monitoring for the summary …").
  `stop_monitoring` pops the stored summary and adds `timed_out: true`. If it arrives while the
  reap is still closing the stream, it calls `session.stop()` itself; `stop()` is safe to call twice.
- **`PITCH_SESSION_IDLE_MINUTES`** is read once at import. `0` disables reaping and the thread.
- **Testing:** the clock, the sleep and the stop event are injected, so unit tests call
  `reap(now)` and `Reaper.run()` directly with a fake clock and never wait on real time.

### Audio Sources and Pitch Frames (YIN Autocorrelation)

`ScoreSession` depends on the `AudioSource` protocol (proposal §6.4: L and D). Both sources deliver
mono float32 at 22 050 Hz to the same sink, `ScoreSession._feed`:

| Source | Thread that runs the analysis | Why |
|---|---|---|
| `SoundDeviceSource` | its daemon worker (callback → `queue.Queue` → worker → sink) | the PortAudio callback must stay deadline-safe |
| `PushedChunkSource` | the `push_audio_chunk` handler, synchronously | the push's reply already reflects its chunk (one round trip pushes and polls), and no queue can grow behind a slow analysis |

The proposal sketched the pushed source as a queue for the existing worker; feeding synchronously
was chosen instead for the two reasons in the table. Analysis costs about 5 ms per hop, so a
100 ms push (about 4 hops) takes about 20 ms.

```
PitchFrames.feed(chunk):            ← window 2048, hop 512, sample_rate 22050
  samples = pending + chunk
  for each whole hop of 512 samples:
    buffer = np.roll(buffer, -512); buffer[-512:] = hop

    ── YIN autocorrelation (_yin_pitch) ─────────────────
    half = len(buffer) // 2
    d = [sum((buf[:half] - buf[tau:tau+half])**2)
         for tau in range(1, half)]       ← difference function
    cmnd = d[tau] * tau / sum(d[1:tau+1]) ← cumulative mean normalized
    tau = first tau where cmnd[tau] < 0.15
    walk tau down to the dip's local minimum
    ── parabolic interpolation for sub-sample accuracy ──
    freq = sample_rate / tau_est

    yield (freq, confidence, hops * 512 / 22050)
  pending = the samples short of a hop

ScoreSession._feed(chunk):
  for each frame: _process_pitch_frame(freq, confidence, elapsed_sec)
```

Interpolating from the dip's first sample below the threshold rather than its minimum read every
note 30–50 cents flat (fixed with the AudioSource refactor; sine tones E2–A5 now read within
3 cents).

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

**The audio callback is minimal** — it only puts chunks into `SoundDeviceSource`'s queue and returns immediately. All computation happens in the worker thread, keeping the PortAudio callback deadline-safe.

**Pushed audio limits** (proposal §7): `sample_rate` 8 000–48 000 Hz; a chunk at most
`int(sample_rate × 1.25) × 2` bytes, checked on the base64 length before decoding; at most 25
accepted pushes per second per session (sliding one-second window on an injected clock; refused
pushes do not count). Violations are `INVALID_PARAMETER` with the limit in the `hint`; undecodable
or odd-length PCM is `INVALID_INPUT`. Nothing is written to disk; the source keeps only the
resampler's last sample and phase, and the session only the 2048-sample window, cleared at stop.

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

Simple YIN with parabolic interpolation at the dip's minimum. Runs in the server-mic worker thread, or in the `push_audio_chunk` handler for pushed audio, with no external library dependencies.

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
_registry: SessionRegistry             ← module-level
  _sessions: dict[str, ScoreSession]
  _last_active: dict[str, float]       (clock() of the last activity)
  _expired: dict[str, _Expired]        (timed-out summaries, kept 1 h)
  _lock: threading.Lock                (guards the three maps; held only for dict operations)
_reaper: Reaper | None                 ← daemon thread, started lazily

ScoreSession:
  session_id: str                  (UUID4)
  note_sequence: list[dict]        (immutable after load)
  _stream: AudioSource | None      (the started source; SoundDeviceSource owns stream, queue, worker)
  _frames: PitchFrames             (rolling YIN window; replaced at start and stop)
  _current_position: dict          (latest position, mutated by the sink)
  _lock: threading.Lock            (guards _current_position/_history)
  _history: list[dict]             (every processed frame's position; feeds stop()'s summary)
  _note_idx: int                   (causal position pointer; never moves backward)
  _nominal_bpm: float              (score's own tempo, from its first MetronomeMark)
  _tempo_bpm: int | None           (start()'s override; scales elapsed time into score-time)
```

`_current_position` is written only by the sink (the server-mic worker, or the push handler under the source's lock) and read by `get_position()` (called from the MCP handler). Access is guarded by `_lock` to prevent torn reads.

Neither the registry lock nor `session._lock` is ever taken in the audio callback, which only
queues chunks. The reaper takes the registry lock briefly and stops sessions outside it.

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
| Session closed by the idle timeout (position / start) | `SESSION_NOT_FOUND` with a `hint` naming the timeout and `stop_monitoring` |
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
| `sheet-music-mcp-core` | Shared error envelope, `ProcessingError` and handler wiring (input validation, error results); see [docs/conventions.md](../../docs/conventions.md#shared-core-library) |

`crepe` (optional): CNN pitch detection. Manual install only. Requires TensorFlow.

---

## File Layout

```
pitch-mcp/
├── pyproject.toml
├── src/
│   └── pitch_mcp/
│       ├── __init__.py
│       ├── server.py          ← MCP layer (tool registration, dispatch, UI resource)
│       ├── presenter.py       ← content + structuredContent, output schemas
│       ├── ui/assets/         ← practice-coach.html, built by ui/ (gitignored, packaged)
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
