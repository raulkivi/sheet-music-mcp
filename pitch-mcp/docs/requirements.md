# pitch-mcp Requirements

## Purpose

Detect a singer's pitch from microphone audio and compare it against a reference MusicXML score. Report the singer's current position in the score and their pitch accuracy in real time.

Covers **Goal 4** (show current score position while singing), **Goal 5** (show pitch accuracy), and **Goal 6** (identify position from hummed/sung melody).

---

## Functional Requirements

### FR-1 — Offline recording analysis

The server MUST accept a pre-recorded WAV file and a reference MusicXML score, and return a note-by-note analysis of the singer's pitch accuracy.

The response MUST include:

- Total measures covered
- Average pitch deviation in cents
- Per-note breakdown: measure number, beat position, expected note name, detected frequency in Hz, deviation in cents, status
- Accuracy histogram: counts of on-pitch, sharp, flat, and no-signal notes

### FR-2 — Score loading

The server MUST accept a MusicXML document and a part (ID, name or voice), parse the reference note sequence, and return a session ID.

The session MUST persist in server memory until it is explicitly stopped, it has been idle longer
than the idle timeout (FR-7), or the server restarts.

### FR-3 — Real-time monitoring start

The server MUST open the system microphone and begin pitch detection for the given session.

If no microphone is available or access is denied, the server MUST return a clear error.

### FR-4 — Real-time position polling

While monitoring is active, the server MUST return the current score position and pitch accuracy in response to poll requests.

Each response MUST include:

- Session ID
- Current measure number and beat position
- Expected note name at that position
- Detected pitch in Hz
- Deviation in cents from expected pitch
- Status: `on_pitch`, `sharp`, `flat`, or `no_signal`

### FR-5 — Real-time monitoring stop

The server MUST stop the microphone stream, clean up the session, and return a summary when requested.

The summary MUST include total measures sung, average accuracy in cents, and an accuracy histogram.

### FR-6 — Capability reporting

The server MUST expose a tool that returns:

- Server name and version
- Supported input formats
- Active pitch detection backend and version
- Microphone availability flag
- List of available tools

### FR-7 — Idle session timeout

A session that sees no activity for `PITCH_SESSION_IDLE_MINUTES` (IR-8, default 10) MUST be
closed: its microphone stream stopped and its memory freed. Activity is `load_score` (creation),
`start_monitoring` and `get_current_position`. Sessions that were loaded but never started expire
too. `0` disables the timeout.

The summary of a timed-out session MUST stay available to `stop_monitoring` for 1 hour (IR-6), and
`get_current_position` / `start_monitoring` on it MUST say that it timed out (IR-9).

### FR-8 — Session listing

The server MUST list the open sessions with their part, state and idle time (IR-6a), so a client
that lost a `session_id` can find it and stop it.

---

## Non-Functional Requirements

### NFR-1 — Pitch detection accuracy

The pitch detector MUST return the correct note name (within ±25 cents) for a clearly sung note at typical choir singing levels. This threshold defines the `on_pitch` boundary.

### NFR-2 — Latency

In real-time mode, the lag between a singer producing a note and the server reporting the detected pitch via `get_current_position` MUST be under 500 milliseconds.

### NFR-3 — Audio format

The offline analysis tool (`analyze_recording`) MUST accept 16-bit PCM WAV files. MP3 and FLAC MUST be rejected with a clear `UNSUPPORTED_FORMAT` error.

### NFR-4 — Session isolation

Multiple concurrent sessions MUST be supported. Each session MUST maintain independent state (loaded score, audio buffer, current position).

### NFR-5 — Offline analysis independence

`analyze_recording` MUST work without a microphone or PortAudio. It MUST NOT fail or skip due to missing audio hardware.

### NFR-6 — Transport

The server MUST communicate via MCP stdio transport.

---

## Interface Requirements

### IR-1 — MCP protocol

The server MUST implement MCP using `mcp.server.stdio.stdio_server()`.

### IR-1a — Tool metadata and server instructions

Every tool sets a human-readable `title` and an annotation preset from `sheet-music-mcp-core`
(see [conventions: Tool Annotations and Titles](../../docs/conventions.md#tool-annotations-and-titles)).
The per-tool table of titles and presets is `tests/test_tool_metadata.py`. The server sends
`instructions` at initialize ([conventions: Server Instructions](../../docs/conventions.md#server-instructions)).

`load_score`, `start_monitoring` and `stop_monitoring` use the `SESSION_STATE` preset, never
`READ_ONLY`, so hosts that auto-approve read-only tools still ask before the microphone opens.
`list_sessions` only reads the registry and is `READ_ONLY`. The instructions mention that idle
sessions close after `PITCH_SESSION_IDLE_MINUTES` (default 10).

### IR-2 — Tool: `analyze_recording`

```
Input:
  audio_path  string  required  absolute path to a 16-bit PCM WAV file
  musicxml    string  required  MusicXML document as a string
  part        string  required  part to compare against: ID, name or voice (e.g. "P1", "Soprano", "S")
  part_id     string            deprecated alias of `part` (removed next minor); one of the two is required

Output:
  part_id             string   MusicXML score-part id of the analysed part (e.g. "P1")
  part_name           string   its name, or the ID when the part is unnamed
  measures_covered    integer
  avg_accuracy_cents  float
  note_accuracy       list[object]
    measure          integer
    beat             float
    expected         string   note name, e.g. "G4"
    sung_hz          float
    accuracy_cents   float
    status           string   "on_pitch" | "sharp" | "flat" | "no_signal"
  accuracy_histogram  object
    on_pitch   integer
    sharp      integer
    flat       integer
    no_signal  integer
```

### IR-3 — Tool: `load_score`

```
Input:
  musicxml   string  required  MusicXML document as a string
  part       string  required  part to monitor: ID, name or voice (e.g. "P1", "Soprano", "S")
  part_id    string            deprecated alias of `part` (removed next minor); one of the two is required

Output:
  session_id       string
  part_id          string   MusicXML score-part id (e.g. "P1")
  part_name        string   the part's name, or its ID when unnamed
  measure_count    integer
  duration_seconds float
```

### IR-4 — Tool: `start_monitoring`

```
Input:
  session_id  string   required
  tempo_bpm   integer  optional  override score tempo; default: score tempo

Output:
  status      string  "started"
  session_id  string
```

### IR-5 — Tool: `get_current_position`

```
Input:
  session_id  string  required

Output:
  session_id      string
  measure         integer
  beat            float
  expected_note   string   e.g. "E4"
  sung_pitch_hz   float
  accuracy_cents  float
  status          string   "on_pitch" | "sharp" | "flat" | "no_signal"
```

Status thresholds:
- `on_pitch`: deviation within ±25 cents
- `sharp`: deviation > +25 cents
- `flat`: deviation < −25 cents
- `no_signal`: no detectable pitch in the audio window

### IR-6 — Tool: `stop_monitoring`

```
Input:
  session_id  string  required

Output:
  session_id  string
  summary     object
    measures_covered     integer
    avg_accuracy_cents   float
    accuracy_histogram   object (same structure as analyze_recording)
  timed_out   boolean  true when the idle timeout had already closed the session (FR-7)
```

If the idle timeout closed the session less than 1 hour ago, `stop_monitoring` returns the summary
taken at that moment with `timed_out: true`. Like a normal stop, it does so once; a second call,
or a call after the hour, gives `SESSION_NOT_FOUND`.

### IR-6a — Tool: `list_sessions`

```
Input: none

Output:
  idle_timeout_minutes  integer   the PITCH_SESSION_IDLE_MINUTES in force; 0 = no timeout
  sessions              list[object]   open sessions, in load order (timed-out ones are not listed)
    session_id    string
    part_id       string   MusicXML score-part id
    part_name     string
    state         string   "loaded" (no microphone) | "monitoring" (microphone open)
    idle_seconds  float    seconds since the last activity, one decimal
```

### IR-7 — Tool: `list_capabilities`

```
Output:
  server                  string
  version                 string
  input_formats           list[string]   ["musicxml", "wav"]
  output_formats          list[string]   ["json"]
  tools                   list[string]
  pitch_backend           string         "librosa"
  pitch_backend_version   string
  microphone_available    boolean
```

### IR-8 — Environment variable

| Variable | Default | Description |
|----------|---------|-------------|
| `PITCH_BACKEND` | `librosa` | Pitch detection backend: `librosa` or `crepe` |
| `PITCH_SESSION_IDLE_MINUTES` | `10` | Close sessions idle this many minutes (whole number); `0` disables the timeout. An invalid value logs a warning and uses 10. |

`crepe` requires a manual TensorFlow install and is not tested in CI.

### IR-9 — Error response format

```json
{"error": "<human-readable message>", "error_code": "<CODE>"}
```

| Code | Condition |
|------|-----------|
| `FILE_NOT_FOUND` | Audio file path does not exist |
| `UNSUPPORTED_FORMAT` | Audio file is not 16-bit PCM WAV |
| `INVALID_INPUT` | MusicXML cannot be parsed |
| `INVALID_PARAMETER` | Part name not found in score |
| `SESSION_NOT_FOUND` | session_id is unknown; call `load_score` first. If the idle timeout closed it, the error adds a `hint`: "The session timed out after N minutes idle; call stop_monitoring for the summary, then load_score to start again." |
| `PROCESSING_FAILED` | Microphone unavailable; no pitch detected; audio hardware error |

---

## Constraints

- Language: Python 3.12+
- Package manager: uv
- Score parsing: music21
- Primary pitch detection backend: librosa pYIN (`librosa.pyin`) — pure Python, no system deps
- Real-time audio: sounddevice — installs without a build step; requires `libportaudio2` at runtime
- Real-time pitch detection in the audio callback thread uses YIN autocorrelation — no heavy libraries in the audio thread
- Score alignment: DTW via dtaidistance
- `aubio` is excluded: no Python 3.13 wheel
- `crepe` is excluded from default install: build failure in uv due to missing `pkg_resources`
- Audio callback MUST NOT perform I/O, locking, or heavy computation — keep it minimal

---

## Testing Requirements

### TR-1 — Unit tests

Unit tests MUST cover:

- Hz-to-note conversion including cents deviation
- Note sequence extraction from a SATB MusicXML fixture
- Session lifecycle: create, start, poll, stop, verify cleanup
- `FILE_NOT_FOUND` error for missing audio file
- `UNSUPPORTED_FORMAT` error for non-WAV input
- Unknown part error with `choices`; selection by ID, name and voice, same-named and unnamed parts (`tests/test_part_selection.py`)
- Unknown session ID error
- Idle timeout with a fake clock (`tests/test_session_timeout.py`): no reap before the timeout,
  reap closes the stream and keeps the summary, `stop_monitoring` / `get_current_position` after a
  reap, activity resets idle time, `0` disables, env parsing, the `Reaper` loop with an injected
  sleep, summaries dropped after 1 hour, `list_sessions` shape and states. No test waits on real time.
- `list_capabilities` response schema

Unit tests MUST mock sounddevice (no real audio hardware in CI). `dtaidistance` is pure-Python-
compatible and deterministic, so alignment unit tests run it directly rather than mocking it —
that's what actually exercises the DTW correctness this module depends on.

### TR-2 — Integration tests

Integration tests MUST:

- Be marked `@pytest.mark.integration`
- Run `analyze_recording` on a committed fixture WAV with a matching MXL
- Assert the response contains `note_accuracy` with at least one entry
- Assert `avg_accuracy_cents` is a finite number
- Run without a microphone (offline analysis only)

### TR-3 — Manual tests

Real-microphone tests MUST:

- Be marked `@pytest.mark.manual`
- Be excluded from CI runs
- Test the full `load_score` → `start_monitoring` → `get_current_position` → `stop_monitoring` lifecycle

### TR-4 — Test fixtures

A short (~10–20 second) soprano vocal WAV file and a matching reference MusicXML MUST be committed to `tests/fixtures/` for integration tests.
