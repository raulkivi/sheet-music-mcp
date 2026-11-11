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

The server MUST accept a MusicXML document (inline, or as a file path: FR-8) and a part (ID, name or voice), parse the reference note sequence, and return a session ID.

The session MUST persist in server memory until it is explicitly stopped, it has been idle longer
than the idle timeout (FR-7), or the server restarts.

### FR-3 — Real-time monitoring start

The server MUST open the system microphone and begin pitch detection for the given session.

If no microphone is available or access is denied, the server MUST return a clear error.

With `source: "pushed"` the server MUST NOT open its microphone; the session instead analyses the
audio the Practice Coach pushes from the browser (FR-12).

### FR-12 — Browser microphone (MCP Apps option B, decision D2 Phase 3)

A pushed session MUST accept chunks of 16-bit little-endian mono PCM (base64) at any stated rate
from 8 000 to 48 000 Hz, resample them to the tracker's 22 050 Hz and feed the same pitch tracker
as the server microphone. Each push MUST return the position snapshot that chunk leads to (FR-4
shape). The server MUST refuse, with `INVALID_PARAMETER` and the limit in the `hint`, a chunk over
1.25 s of audio at its stated rate and more than 25 pushes per second per session. Pushed audio
MUST NOT be written anywhere, and MUST be dropped once analysed (only the ~93 ms analysis window is
held, and it is cleared when the take stops). A push counts as session activity (FR-7).

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

### FR-8 — Score references (UX Wave 2)

`analyze_recording` and `load_score` MUST accept the score as inline text (`musicxml`) or as a
file path (`musicxml_path`, `.musicxml`, `.xml` or `.mxl`), exactly one of the two
([conventions: Score References](../../docs/conventions.md#score-references)). A path is read
through `sheet_music_mcp_core.references.load_score()`, which confines it to the read roots
(`SHEET_MUSIC_OUTPUT_ROOT`, the client's MCP roots, `SHEET_MUSIC_INPUT_ROOTS`) and never echoes
file contents in an error. A score loaded by path then gets the same checks and gives the same
result as the same score inline: `load_score` creates the same session (part, notes, tempo).

`audio_path` is not confined in this wave (plan decision W2-3): it is read as before.

The server MUST expose the shared `describe_score` tool (title, composer, key, time, tempo,
parts with IDs, names, clefs and ranges, measures, lyrics, duration) so a client can learn the
part IDs without loading the score into a session.

### FR-9 — Measure ranges (UX Wave 3, B2)

`analyze_recording`, `load_score` and `start_practice` MUST accept an optional
`measures: [start, end]` of printed, inclusive bar numbers
([conventions: Measure Ranges](../../docs/conventions.md#measure-ranges)). The engine cuts the score
with `sheet_music_mcp_core.measures.select_measures()` before extracting the part's notes, so a
session's timeline starts at `start` (at the tempo in force there) and every reported `measure`
keeps its printed number. `measure_count` counts bars from `start` (bar 1 without `measures`) to
the last note. A range outside the score, reversed or malformed is `INVALID_PARAMETER` with a
`hint` naming the score's first and last bars. Without `measures` the whole score is used, as
before.

### FR-10 — One-call practice start (UX Wave 3, C19)

`start_practice` MUST do `load_score` then `start_monitoring` in one call and return both results'
fields (`session_id` once). If the microphone fails to open, the session it just loaded MUST be
removed before the error is returned, so `list_sessions` shows no orphan.

### FR-11 — Highlights (UX Wave 3, C22)

`analyze_recording` and the `stop_monitoring` summary MUST carry `highlights`: up to 3 runs of at
least 2 consecutive notes that are all flat (< −25 cents) or all sharp (> +25 cents), ranked by
notes × |average cents|, each with a plain-words `text` such as
`"flat on E5 in m.12–14 (-35 cents avg)"` (one pitch) or
`"flat in m.12–14 (-35 cents avg over 4 notes)"`; sharp averages carry a `+`. Consecutive
entries for the same note (measure, beat, expected pitch) count as one note with their median
cents, so the per-frame live history and the per-note offline results give the same highlights.
A `no_signal` or on-pitch note ends a run. A summary with no data has `highlights: []`.

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

`load_score`, `start_practice`, `start_monitoring` and `stop_monitoring` use the `SESSION_STATE` preset, never
`READ_ONLY`, so hosts that auto-approve read-only tools still ask before the microphone opens.
`list_sessions` and `describe_score` only read and are `READ_ONLY`. The instructions mention that idle
sessions close after `PITCH_SESSION_IDLE_MINUTES` (default 10).

### IR-2 — Tool: `analyze_recording`

```
Input:
  audio_path     string  required  absolute path to a 16-bit PCM WAV file (not confined, W2-3)
  musicxml       string            MusicXML text of the reference score
  musicxml_path  string            path to the score (.musicxml, .xml, .mxl) inside the read roots;
                                   exactly one of musicxml / musicxml_path (schema oneOf)
  part        string  required  part to compare against: ID, name or voice (e.g. "P1", "Soprano", "S")
  part_id     string            deprecated alias of `part` (removed next minor); one of the two is required
  measures    [int, int]        optional printed bar range [start, end]; the recording covers those bars (FR-9)

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
  highlights          list[object]   up to 3 worst flat/sharp runs (FR-11)
    direction  string        "flat" | "sharp"
    measures   [int, int]    first and last measure of the run
    notes      integer
    avg_cents  integer       signed mean of the notes' cents
    text       string        e.g. "flat on E5 in m.12–14 (-35 cents avg)"
```

### IR-3 — Tool: `load_score`

```
Input:
  musicxml       string            MusicXML text of the score to practise
  musicxml_path  string            path to the score (.musicxml, .xml, .mxl) inside the read roots;
                                   exactly one of musicxml / musicxml_path (schema oneOf)
  part           string  required  part to monitor: ID, name or voice (e.g. "P1", "Soprano", "S")
  part_id        string            deprecated alias of `part` (removed next minor); one of the two is required
  measures       [int, int]        optional printed bar range [start, end] to practise (FR-9)

Output:
  session_id       string
  part_id          string   MusicXML score-part id (e.g. "P1")
  part_name        string   the part's name, or its ID when unnamed
  measure_count    integer  bars from the first practised bar to the last note
  duration_seconds float
```

### IR-3a — Tool: `start_practice`

`load_score` + `start_monitoring` in one call (FR-10), `SESSION_STATE`, title "Start practice".

```
Input:
  musicxml       string            MusicXML text of the score to practise
  musicxml_path  string            path to the score; exactly one of musicxml / musicxml_path
  part           string  required  part to sing: ID, name or voice (no deprecated `part_id`)
  tempo_bpm      integer optional  override score tempo; default: score tempo
  measures       [int, int]        optional printed bar range [start, end] (FR-9)

Output: load_score's fields plus start_monitoring's
  session_id, part_id, part_name, measure_count, duration_seconds, status ("started")
```

### IR-4 — Tool: `start_monitoring`

```
Input:
  session_id  string   required
  tempo_bpm   integer  optional  override score tempo; default: score tempo
  source      string   optional  "server_mic" (default) | "pushed"

Output:
  status      string  "started"
  session_id  string
  source      string  "pushed"   only for a pushed session; the server-mic output is unchanged
```

An unknown `source` is `INVALID_PARAMETER` (with `choices`). Errors set `isError: true`; so do
`stop_monitoring` and `list_sessions` errors (content unchanged).

### IR-4a — Tool: `push_audio_chunk` (app-only)

```
Input (additionalProperties: false):
  session_id   string   required
  pcm_b64      string   required  16-bit little-endian mono PCM, base64 (empty = just poll)
  sample_rate  integer  required  8000..48000

Output: structuredContent = the get_current_position snapshot (POSITION_OUTPUT_SCHEMA);
        content = one line, e.g. "Measure 1, beat 1: A3 expected, on pitch (+0 cents)."
```

`_meta.ui.visibility: ["app"]`, hidden from clients without MCP Apps. Errors (`isError: true`):

| Case | Code |
|---|---|
| Unknown, stopped or timed-out session | `SESSION_NOT_FOUND` |
| Session on the server microphone, or loaded but not started | `INVALID_PARAMETER` (hint: start with `source: "pushed"`) |
| `sample_rate` outside 8000..48000 | `INVALID_PARAMETER` (hint names the range) |
| Chunk over `int(sample_rate * 1.25) * 2` bytes | `INVALID_PARAMETER` (hint names the byte limit) |
| More than 25 pushes in one second for the session | `INVALID_PARAMETER` (hint names the limit) |
| Not base64, or an odd byte count | `INVALID_INPUT` |
| Empty `session_id` | `INVALID_INPUT` |

A refused push feeds nothing. The Practice Coach resource does not yet declare
`_meta.ui.permissions.microphone`: the shared `UiResource` cannot express resource permissions yet.

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

Before the first detected pitch, `measure`, `beat` and `expected_note` are those of the
session's first note (with `measures`, a note in the first selected bar or later).

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
    highlights           list[object] (same structure as analyze_recording; [] with no data)
  timed_out   boolean  true when the idle timeout had already closed the session (FR-7)
```

If the idle timeout closed the session less than 1 hour ago, `stop_monitoring` returns the summary
taken at that moment with `timed_out: true`. Like a normal stop, it does so once; a second call,
or a call after the hour, gives `SESSION_NOT_FOUND`.

### IR-5a — MCP Apps: Practice Coach (`structuredContent`)

`load_score`, `start_practice`, `get_current_position` and `analyze_recording` declare an
`output_schema` and return `structuredContent` next to the unchanged `content` text
(`tests/test_content_golden.py` pins `content`). Errors keep the `{error, error_code}` content, set
`isError: true` and carry no `structuredContent`. Shapes (`presenter.py`):

```
load_score, start_practice (SESSION_OUTPUT_SCHEMA):
  session_id, part_id, part_name, measure_count, duration_seconds, tempo_bpm
  tempo_bpm is a number: the score's tempo, or the start_practice override. It is not in
  `content` (kept byte-identical); `status` from start_practice is not in structuredContent.
get_current_position: the snapshot `content` already carries
  session_id, measure, beat, expected_note, sung_pitch_hz|null, accuracy_cents|null, status
analyze_recording: the result `content` already carries, every note included
  part_id, part_name, measures_covered, avg_accuracy_cents, note_accuracy[], accuracy_histogram, highlights[]
```

`load_score`, `start_practice` and `analyze_recording` link `ui://pitch/practice-coach`
(`_meta.ui.resourceUri`) only while `src/pitch_mcp/ui/assets/practice-coach.html` is packaged;
otherwise they carry no `_meta.ui` and the resource is not listed (AC-P1, AC-P2). The app can
either poll a server-microphone session or capture in the browser and push audio (IR-4a, option B).

**`get_score_for_session`** (app-only, `_meta.ui.visibility: ["app"]`, listed only to clients that
support MCP Apps; `tools/call` still finds it). Input `{session_id}` and nothing else (no paths,
`additionalProperties: false`); output `{session_id, musicxml}`, the session's score cut to its
`measures`. Unknown or timed-out session: `SESSION_NOT_FOUND`. `content` is a one-line note, not
the document.

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

### IR-6b — Tool: `describe_score`

The shared tool from `sheet-music-mcp-core` (`references.DESCRIBE_SCORE_TOOL`), `READ_ONLY`.

```
Input:
  musicxml       string  MusicXML text
  musicxml_path  string  path to the score; exactly one of the two

Output:
  title, composer, key, time, tempo_bpm, measures, has_lyrics, duration_quarters, duration_seconds
  parts  list[object]   id ("P1" …, the IDs `part` accepts), name, abbreviation, clef, range {low, high}
```

### IR-7 — Tool: `list_capabilities`

```
Output:
  server                  string
  version                 string
  input_formats           list[string]   ["musicxml", "mxl", "wav"]
  input_parameters        list[string]   ["musicxml", "musicxml_path"]  (the score parameter pair)
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

Score paths follow the shared variables ([conventions: Score References](../../docs/conventions.md#score-references)):
`SHEET_MUSIC_OUTPUT_ROOT` (default: the working directory), `SHEET_MUSIC_INPUT_ROOTS` (extra read
folders, `os.pathsep`-separated) and `SHEET_MUSIC_MAX_SCORE_BYTES` (default 16 MiB).

`crepe` requires a manual TensorFlow install and is not tested in CI.

### IR-9 — Error response format

```json
{"error": "<human-readable message>", "error_code": "<CODE>"}
```

| Code | Condition |
|------|-----------|
| `FILE_NOT_FOUND` | Audio file path does not exist; `musicxml_path` inside the read roots does not exist |
| `FILE_TOO_LARGE` | `musicxml_path` (or an `.mxl` member) is larger than `SHEET_MUSIC_MAX_SCORE_BYTES` |
| `UNSUPPORTED_FORMAT` | Audio file is not 16-bit PCM WAV |
| `INVALID_INPUT` | MusicXML cannot be parsed (inline or from `musicxml_path`) |
| `INVALID_PARAMETER` | Part name not found in score; both or neither of `musicxml` / `musicxml_path`; `musicxml_path` outside the read roots or with a wrong suffix; `measures` reversed, malformed or outside the score (with a `hint` naming its first and last bars) |
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
- `ScoreSession` depends on the `AudioSource` protocol (`start(sink)`, `stop()`, `close()`), never on
  sounddevice directly; `SoundDeviceSource` and `PushedChunkSource` implement it

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
- Score references (`tests/test_score_references.py`): a path gives the same result as inline
  text (same session for `load_score`), `.mxl` paths, both or neither parameter, paths outside
  the read roots (absolute, `/etc/passwd`, `..`, symlink) without echoing the file, `describe_score`
- Practice (`tests/test_practice.py`): `measures` on `load_score` / `analyze_recording` (measure
  count, printed numbers, timeline and carried tempo, range errors with hint), `start_practice`
  fields, tempo and orphan-free mic failures with a fake `sounddevice` module, `<sound tempo>`-only
  scores
- Practice Coach (`tests/test_practice_coach.py`, `tests/test_content_golden.py`): tool linking with
  and without a packaged page (`InMemoryAssetSource`), resource list/read, `structuredContent`
  shapes against their schemas, `get_score_for_session` (app-only, no paths, unknown session), errors
  as `isError` without `structuredContent`, `content` identical to the pre-Apps golden file
- Highlights (`tests/test_highlights.py`): runs, splitting, ranking, text, frame-level history
- Audio sources (`tests/test_audio_source.py`): an injected source feeds the session, stop then
  close, the module default factory, a failing source leaves the session loaded,
  `SoundDeviceSource` stream settings and worker hand-off, `PitchFrames` hop framing and YIN
  accuracy (within 3 cents, E2 to A5)
- Browser microphone (`tests/test_pushed_audio.py`): AC-P4 (1 s of 220 Hz in 100 ms chunks on an A3
  is `on_pitch`), other rates, silence, sharp and flat, size / rate / sample-rate refusals,
  malformed PCM, session errors, activity, no file I/O, the tool's schema, visibility and protocol
  round trip

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
