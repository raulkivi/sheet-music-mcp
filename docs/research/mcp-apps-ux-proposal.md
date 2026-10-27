# MCP Apps for sheet-music-mcp: tool use cases and proposed UIs

**Status:** Research / proposal. No code has been written.
**Date:** 2026-10-27
**Scope:** All 34 tools across the six servers (`omr-mcp`, `render-mcp`, `synth-mcp`,
`musicxml-abc-mcp`, `pitch-mcp`, `comparer-mcp`).
**Question:** Where would an [MCP App](#references) (an interactive UI that the server ships and
the host renders inline in the conversation) improve UX over today's text-and-file-path results?
Which apps are worth building first?

---

## Table of contents

1. [Summary](#1-summary)
2. [What MCP Apps are](#2-what-mcp-apps-are)
3. [Pain points in today's UX](#3-pain-points-in-todays-ux)
4. [Tool inventory and UI verdicts](#4-tool-inventory-and-ui-verdicts)
5. [Proposed apps, one server at a time](#5-proposed-apps-one-server-at-a-time)
   - 5.1 [pitch-mcp: Live Practice Coach](#51-pitch-mcp-live-practice-coach)
   - 5.2 [synth-mcp: Practice Player and Voice Mixer](#52-synth-mcp-practice-player-and-voice-mixer)
   - 5.3 [render-mcp: Score Viewer](#53-render-mcp-score-viewer)
   - 5.4 [comparer-mcp: Diff Viewer](#54-comparer-mcp-diff-viewer)
   - 5.5 [omr-mcp: Recognition Review](#55-omr-mcp-recognition-review)
   - 5.6 [musicxml-abc-mcp: ABC Workbench](#56-musicxml-abc-mcp-abc-workbench)
   - 5.7 [All servers: Setup Doctor](#57-all-servers-setup-doctor)
6. [Shared architecture](#6-shared-architecture)
7. [Security](#7-security)
8. [Testing strategy (TDD)](#8-testing-strategy-tdd)
9. [Roadmap](#9-roadmap)
10. [Open questions](#10-open-questions)
11. [References](#references)

---

## 1. Summary

The six servers return JSON text and paths to files on disk. That suits an LLM pipeline but makes
users do the work: open a PDF, find the WAV, read a list of note diffs, or keep asking the model
to poll a microphone. MCP Apps let each server ship an HTML UI that the host renders next to the
tool result. The UI can call the server's tools directly, without a model turn.

| Priority | App | Server | Why it matters |
|---|---|---|---|
| **P0** | Live Practice Coach | pitch-mcp | Real-time feedback is not possible today. Following the singer means the model calling `get_current_position` again and again, one turn per poll. An app can poll 10 times a second and draw a moving cursor and a pitch meter. |
| **P0** | Practice Player and Voice Mixer | synth-mcp | Every tempo or voice change takes another prompt and produces another WAV file to open. An app gives the singer play, solo/mute, a tempo slider and loop controls on one screen. |
| **P1** | Score Viewer (shared component) | render-mcp | Pages appear inline instead of as a `pdf_path`. The other apps reuse the same component. |
| **P1** | Diff Viewer | comparer-mcp | Annotated scores side by side, with a change list you can filter and click. Replaces long JSON diffs. |
| **P1** | Recognition Review | omr-mcp | Shows the photo next to the recognised score so OMR errors are visible. Re-running with Audiveris is one click. |
| **P2** | ABC Workbench | musicxml-abc-mcp | Before and after view of the model's edits, live validation, and accept or reject. |
| **P3** | Setup Doctor | all | A visual `health_check` with fix-it hints for non-developers. |

**Keep as text only:** `list_capabilities`, `list_supported_formats`, and the file-oriented
variants (`recognize_sheet_to_file`, `compare_musicxml_files`) when used in scripted pipelines.

**Main architecture choices** (detail in [§6](#6-shared-architecture)):

1. **One shared UI kit, bundled per server.** A TypeScript workspace builds one self-contained
   HTML file per app. Each Python package ships its own copy as package data, so the servers stay
   independently deployable.
2. **Render notation in the iframe with Verovio (WASM).** Apps cannot call tools on another server,
   so `comparer-mcp` cannot reach `render-mcp`. Client-side Verovio removes that dependency and
   gives a timemap that drives playback and singing cursors.
3. **Opaque handles, not file paths.** App-only tools fetch WAV and image bytes by a server-issued
   ID. A tool that reads any file by path would let a page read arbitrary files.
4. **Progressive enhancement.** Every tool keeps returning today's `content`, so hosts without MCP
   Apps (Claude Code CLI, Cursor, older clients) are unaffected and the existing tests keep passing.

---

## 2. What MCP Apps are

MCP Apps (SEP-1865, extension id `io.modelcontextprotocol/ui`, stable spec dated 2026-01-26) is an
optional MCP extension for interactive UIs. The parts this proposal uses:

| Concept | Mechanism |
|---|---|
| UI resource | An HTML5 document served through `resources/read` at a `ui://` URI, MIME type `text/html;profile=mcp-app`. |
| Tool to UI link | The tool's `_meta.ui.resourceUri` points at the `ui://` resource. The host renders it in a sandboxed iframe when the tool is called. |
| Tool visibility | `_meta.ui.visibility`: `["model"]`, `["app"]` or both (default). App-only tools are hidden from the model but callable by the UI. A UI can call only tools on its own server. |
| Data to the UI | Host notifications: `ui/notifications/tool-input` (arguments), `tool-input-partial` (streamed), `tool-result`, `tool-cancelled`, `host-context-changed`. |
| `content` vs `structuredContent` | `content` goes to the model and to text-only hosts. `structuredContent` is for the UI and is **not added to model context**, so large SVG or diff payloads cost no tokens. |
| UI to host | `tools/call`, `resources/read`, `ui/message` (post a chat message), `ui/update-model-context` (tell the model about UI state), `ui/open-link`, `ui/request-display-mode`, `ui/notifications/size-changed`. |
| Display modes | `inline`, `fullscreen`, `pip` (picture-in-picture). |
| Host context | `theme`, `styles`, `displayMode`, `containerDimensions`, `locale`, `platform` (`web`/`desktop`/`mobile`), `deviceCapabilities` (`touch`, `hover`), `safeAreaInsets`. |
| Sandbox | `_meta.ui.csp` (`connectDomains`, `resourceDomains`, `frameDomains`, `baseUriDomains`). Without it, the host applies a restrictive default. |
| Device permissions | `_meta.ui.permissions`: `camera`, `microphone`, `geolocation`, `clipboardWrite`. The host may grant or refuse each one, so the app must check what it actually got. |
| Negotiation | Clients advertise support in `capabilities.extensions["io.modelcontextprotocol/ui"]`. Tools must always return useful `content` as a fallback. |

**SDK readiness in this repo (checked against the installed `mcp` 2.x in `render-mcp/.venv`):**
`mcp.types.Tool` has a `meta` field (serialised as `_meta`) and `CallToolResult` has
`structured_content`. `Server(...)` accepts `on_list_resources` and `on_read_resource`, and
`ClientCapabilities` has `extensions`. No SDK upgrade is needed. Each server needs two resource
handlers plus `meta` and `structured_content` on the relevant tools.

---

## 3. Pain points in today's UX

| # | Pain point | Where | Consequence |
|---|---|---|---|
| P1 | **Outputs are file paths.** `pdf_path`, `image_path`, `audio_path`. | render, synth, omr (`_to_file`) | The user leaves the chat to open a file. On a phone or a remote host the file may not be reachable at all. |
| P2 | **Real-time loop through the model.** `get_current_position` has to be polled by the LLM. | pitch | Each poll is a model turn of 1–5 s. The singer cannot see a cursor follow them, which is the server's main goal (README goals 4–6). |
| P3 | **Iterating means re-prompting.** "Slower", "only alto", "page 3", "now with tenor" each take a new message. | synth, render | Slow, costs tokens, and a new file appears every time. |
| P4 | **Results you have to see are returned as JSON.** Note diffs, per-note accuracy, OMR metadata. | comparer, pitch, omr | Hard to read. The model summarises the JSON, which loses detail or gets it wrong. |
| P5 | **No way to check OMR output.** The model gets MusicXML but nobody compares it with the photo. | omr | Recognition errors are found later, while singing. The known oemer SATB flattening is easy to miss. |
| P6 | **Unreviewed edits by the model.** ABC changes go straight back to MusicXML. | musicxml-abc | No diff and no accept/reject. Hard to trust for choir parts. |
| P7 | **Large payloads in context.** Full MusicXML or annotated MusicXML returned as `content`. | omr, abc, comparer | Burns context. `structuredContent` would carry the same data to a UI for free. |
| P8 | **Setup diagnostics as plain text.** | all `health_check` | Non-developers (the SETUP UX target audience) struggle with environment variables and paths. |

---

## 4. Tool inventory and UI verdicts

Verdict key:

- **App**: the tool links to a UI (`_meta.ui.resourceUri`).
- **App-callable**: stays visible to the model and is also called by a UI.
- **Text only**: no UI value.
- **New app-only**: a proposed helper tool with `visibility: ["app"]`.

### omr-mcp (6 tools)

| Tool | Use case | Output today | Verdict |
|---|---|---|---|
| `recognize_sheet` | Photo or scan of one page to MusicXML | `{musicxml, metadata{staves_detected, measures, processing_time_ms, engine}}` | **App**: Recognition Review |
| `recognize_sheet_to_file` | The same, saved to disk for later steps | `{output_path, …}` | **App** (same UI). Text only in scripted use. |
| `recognize_sheets` | Several pages merged into one score | merged `musicxml`, `page_count` | **App**: Recognition Review, multi-page mode |
| `list_capabilities` | The model finds out about engines and formats | JSON | Text only |
| `list_supported_formats` | Deprecated alias | JSON | Text only |
| `health_check` | Check oemer, Audiveris, model cache | text | **App**: Setup Doctor (P3) |

### render-mcp (4 tools)

| Tool | Use case | Output today | Verdict |
|---|---|---|---|
| `render_to_pdf` | Print or share the score | `{pdf_path, page_count, backend}` | **App**: Score Viewer with a download action |
| `render_to_image` | Show one page | `{image_path, format, width_px, …}` | **App**: Score Viewer. App-callable for paging. |
| `list_capabilities` | Backend discovery | JSON | Text only |
| `health_check` | Check Verovio, cairo, MuseScore | text | **App**: Setup Doctor |

### synth-mcp (4 tools)

| Tool | Use case | Output today | Verdict |
|---|---|---|---|
| `get_parts` | Which voices exist? | `{parts:[{id,name,…}]}` | App-callable (fills the mixer) |
| `synthesize` | Practice track: chosen voices at a chosen tempo | `{audio_path, duration_seconds, parts_included, tempo_factor}` | **App**: Practice Player and Voice Mixer |
| `list_capabilities` | Soundfont and backend discovery | JSON | Text only |
| `health_check` | Check soundfont and FluidSynth | text | **App**: Setup Doctor (soundfont is the top setup failure) |

### musicxml-abc-mcp (5 tools)

| Tool | Use case | Output today | Verdict |
|---|---|---|---|
| `musicxml_to_abc` | Let the model read or edit a score as text | `{abc, parts_included, warnings}` | **App**: ABC Workbench, "original" pane |
| `abc_to_musicxml` | Return the model's edit to MusicXML | `{musicxml, warnings}` | **App**: ABC Workbench, before/after review |
| `validate_abc` | Syntax check | `{valid, errors, warnings}` | App-callable (live validation while typing) |
| `list_capabilities` | Discovery | JSON | Text only |
| `health_check` | Round-trip smoke test | JSON | **App**: Setup Doctor |

### pitch-mcp (7 tools)

| Tool | Use case | Output today | Verdict |
|---|---|---|---|
| `analyze_recording` | Score a recorded take against a part | `{measures_covered, avg_accuracy_cents, note_accuracy[], accuracy_histogram}` | **App**: Practice Coach, Report mode |
| `load_score` | Prepare a live session | `{session_id, part_name, measure_count, duration_seconds}` | **App**: Practice Coach, Live mode (opens the UI) |
| `start_monitoring` | Open the mic | `{status, session_id}` | App-callable (Start button) |
| `get_current_position` | Where is the singer, and are they in tune? | `{measure, beat, expected_note, sung_pitch_hz, accuracy_cents, status}` | App-callable, polled by the UI at 5–10 Hz. The model rarely needs it. |
| `stop_monitoring` | End the session and get a summary | `{summary}` | App-callable (Stop button). The summary goes to model context. |
| `list_capabilities` | Discovery | JSON | Text only |
| `health_check` | Check librosa and PortAudio | JSON | **App**: Setup Doctor |

### comparer-mcp (8 tools)

| Tool | Use case | Output today | Verdict |
|---|---|---|---|
| `compare_musicxml` | Full diff of two editions | `ComparisonResult` (large) | **App**: Diff Viewer |
| `compare_musicxml_files` | The same, from disk | `ComparisonResult` | **App**: Diff Viewer. Text only in scripted use. |
| `quick_similarity` | "How close are these?" | `{similarity, summary}` | Text only. A small gauge is optional. |
| `list_changes` | "What changed in the alto, measures 17–24?" | filtered `NoteDiff[]` | App-callable (Diff Viewer filters) |
| `generate_comparison_report` | Readable report | text | **App**: Diff Viewer, Report tab |
| `export_annotated_musicxml` | Coloured diff scores | two annotated MusicXML docs | **App**: Diff Viewer, Annotated scores tab (today the model has to chain `render-mcp` by hand) |
| `list_capabilities` | Discovery | JSON | Text only |
| `health_check` | Self-compare smoke test | JSON | **App**: Setup Doctor |

**Totals:** 14 tools link to a feature app, the 6 `health_check` tools share the Setup Doctor, 6
become app-callable building blocks, and 8 stay text only (14 + 6 + 6 + 8 = 34).

---

## 5. Proposed apps, one server at a time

Each subsection follows the same template:

- **Use cases**: user stories.
- **Today**: the current flow.
- **Proposed UI**: a wireframe, then the interactions.
- **Contract**: linked tools, new app-only tools, `structuredContent`, model-context sync, display
  modes, permissions and CSP.
- **Fallback**: behaviour in hosts without MCP Apps.
- **Acceptance criteria**: Given/When/Then, written so they can become failing tests first
  ([§8](#8-testing-strategy-tdd)).

Wireframes are ASCII sketches of layout and controls, not visual design.

---

### 5.1 pitch-mcp: Live Practice Coach

**Use cases**

- U1. *As a tenor*, I sing my part and see a cursor follow me through the score, so I don't lose
  my place.
- U2. *As a singer*, I see straight away whether I am sharp, flat or on pitch on each note.
- U3. *As a singer*, after a take I see which measures I sang badly and can loop them.
- U4. *As a choir director*, I upload a recorded take and get a per-note accuracy report on the
  score.
- U5. *As a singer on a phone* (Phase 3 target), I can practise when the MCP server is not running
  on the device that has the microphone.

**Today**

`load_score` → `start_monitoring` → the model calls `get_current_position` again and again → `stop_monitoring`.
Every poll is a full model turn, so the "real-time" view refreshes every few seconds at best and
fills the context with position snapshots (pain points P2, P4).

**Proposed UI: Live mode** (`ui://pitch/practice-coach`)

```
+-----------------------------------------------------------------------+
| Ave verum corpus - Tenor                        [ inline | PiP | [ ] ]|
+-----------------------------------------------------------------------+
|  m.17      m.18            m.19           m.20                        |
|  ==|====o==|==o====o====|==#o=====o==|=====o====|                    |
|              ^ cursor (measure 18, beat 2.5)                          |
|        green/blue/red noteheads = on pitch / flat / sharp so far      |
+-----------------------------------------------------------------------+
|  Expected: A3         Sung: 218.4 Hz (A3 -14c)                        |
|  flat  |-----------------[####|####]-----------------|  sharp        |
|       -50c                    0                     +50c              |
|                         ON PITCH                                      |
+-----------------------------------------------------------------------+
|  [> Start]  [|| Pause]  [[] Stop]   Tempo: score (72 bpm) [ - ][ + ]  |
|  Mic: (o) This device's browser   ( ) Server microphone               |
+-----------------------------------------------------------------------+
```

**Report mode** (after `stop_monitoring` or from `analyze_recording`):

```
+-----------------------------------------------------------------------+
| Take summary - Tenor, m.1-32           Avg deviation: 18 cents        |
+-----------------------------------------------------------------------+
|  Accuracy by measure (heat strip; click a cell to jump):              |
|  m1 ##  m2 ##  m3 ##  m4 ..  m5 !!  m6 !!  m7 ##  ...                 |
|  ## on pitch   .. no signal   !! mostly sharp/flat                    |
+-----------------------------------------------------------------------+
|  Histogram:  flat  ###         on  ##############   sharp  #####      |
+-----------------------------------------------------------------------+
|  Pitch curve vs expected (piano roll, m.5-6):                         |
|     A3 ----____----                                                   |
|     G3         ~~~~~~^^^   <- sung pitch drifts sharp                 |
+-----------------------------------------------------------------------+
|  [Loop m.5-6]   [Practise again]   [Ask Claude for tips]              |
+-----------------------------------------------------------------------+
```

**Interactions**

- **Start, Pause, Stop** call `start_monitoring` and `stop_monitoring` directly (`tools/call`). No
  model turn is involved.
- **Polling:** `get_current_position` every 100–200 ms while running. The cursor and meter animate
  between samples (`requestAnimationFrame`).
- **Picture-in-picture:** `ui/request-display-mode {mode:"pip"}` keeps the meter visible while
  the user chats or scrolls. On `platform: "mobile"` the app starts in fullscreen.
- **Ask Claude for tips** sends `ui/message` with a short summary ("Tenor m.5–6 consistently
  +30 c sharp on G3–A3"), which the model answers.
- **On Stop**, `ui/update-model-context` sets the session summary, so later questions ("how did I
  do?") can be answered without re-running anything.

**Choosing the microphone (the main design decision for this app)**

| Option | How | Pros | Cons |
|---|---|---|---|
| A. Server mic (as today) | The UI only polls. `sounddevice` captures on the server host. | No engine change. Works now. | Only works when the server and singer share a machine. Needs PortAudio. |
| B. Browser mic (new) | `_meta.ui.permissions.microphone`. The UI captures 16 kHz mono PCM (`AudioWorklet`) and pushes ~100 ms chunks with an app-only `push_audio_chunk`. Each push returns the latest position, so one round trip both pushes audio and polls. | Works on phones and remote hosts. No PortAudio. Matches the Phase 3 Android goal. | Engine refactor needed. About 10 tool calls/s (~4.3 KB base64 each). The host may refuse the permission. |

**Recommendation:** ship A first (no engine change), then B behind feature detection. B needs a
small refactor that applies dependency inversion: `ScoreSession` should depend on an
`AudioSource` protocol with two implementations, `SoundDeviceSource` (today's code) and
`PushedChunkSource` (a queue fed by the tool handler). The existing `queue.Queue` and
worker-thread design stays, and the rule against I/O in the callback is unaffected.

**Contract**

| Item | Value |
|---|---|
| UI resource | `ui://pitch/practice-coach` |
| Linked tools | `load_score` (Live mode), `analyze_recording` (Report mode) |
| App-callable | `start_monitoring`, `get_current_position`, `stop_monitoring` |
| New app-only | `push_audio_chunk(session_id, pcm_b64, sample_rate)` → position snapshot (option B). `get_score_for_session(session_id)` → MusicXML for the viewer, so the UI need not keep the tool input. `analyze_recording_data(pcm_b64, musicxml, part_id)` records in the browser, so no WAV path is needed. |
| `structuredContent` | `load_score`: `{session_id, part_id, part_name, measure_count, duration_seconds, tempo_bpm}`. `analyze_recording`: the full `note_accuracy[]` (kept **out of** model `content`, which gets only the summary; see P7). |
| Model context | Session summary on stop; current measure on pause. |
| Display modes | `inline`, `pip`, `fullscreen` |
| Permissions | `microphone` (option B only) |
| CSP | None. Everything is inlined. |

**Fallback:** unchanged. The model can still drive the tools as text.

**Acceptance criteria**

- AC-P1. Given a host advertising `io.modelcontextprotocol/ui`, when tools are listed, then
  `load_score._meta.ui.resourceUri == "ui://pitch/practice-coach"`.
- AC-P2. Given `resources/read ui://pitch/practice-coach`, then exactly one content item is
  returned with `mimeType == "text/html;profile=mcp-app"` and a non-empty HTML5 document.
- AC-P3. Given `analyze_recording` succeeds, then `structuredContent.note_accuracy` holds every
  note and `content[0].text` holds the summary fields only.
- AC-P4. Given a `PushedChunkSource` session, when 1 s of synthetic 220 Hz PCM is pushed against a
  score whose first note is A3, then the returned position has `status == "on_pitch"`
  (|cents| ≤ 25).
- AC-P5 (UI). Given a mock host replaying 20 position snapshots, then the cursor visits the same
  measures in order and the meter shows the colour for each snapshot's status.

---

### 5.2 synth-mcp: Practice Player and Voice Mixer

**Use cases**

- U1. *As an alto*, I play only my line at 75 % tempo and speed up as I learn it.
- U2. *As an alto*, I play all four voices with mine **louder** (a "learning track"), so I hear
  my line inside the harmony.
- U3. *As any singer*, I loop measures 17–24 until I have them.
- U4. *As any singer*, I follow a cursor in the score while the track plays.
- U5. *As any singer*, I mute my own part and sing it against the others (karaoke mode).

**Today**

Each change ("slower", "add tenor", "mute alto") is a new prompt and a new `synthesize` call. The
result is an `audio_path` that the user has to find and open (P1, P3). U2 cannot be done: there is
no per-part gain.

**Proposed UI** (`ui://synth/practice-player`)

```
+-----------------------------------------------------------------------+
| Practice Player - "Ave verum corpus"                     0:42 / 2:58  |
+-----------------------------------------------------------------------+
|  [score strip with moving playback cursor - shared ScoreView]         |
|  ==|====o==|==o====o====|==#o==|====o====|                           |
|           ^                                                           |
+-----------------------------------------------------------------------+
|  Waveform  |||||||||||||||||||[=====loop m.17-24=====]|||||||||||     |
+-----------------------------------------------------------------------+
|  Voice      Solo  Mute   Volume                                       |
|  Soprano    [ ]   [ ]    |------o---|                                 |
|  Alto       [S]   [ ]    |---------o|   <- my part                    |
|  Tenor      [ ]   [ ]    |---o------|                                 |
|  Bass       [ ]   [M]    |o---------|                                 |
+-----------------------------------------------------------------------+
|  Tempo  25% |--------o-------------| 400%   [ 75% ]                   |
|  [|<] [> Play] [||] [Loop A-B]  Count-in: [1 bar]   [Re-render *]     |
|  * shown when tempo or voices changed; renders in about 1-3 s         |
+-----------------------------------------------------------------------+
```

**Interactions**

- The app opens on the `synthesize` result: it plays the returned audio and fills the voice list
  from `structuredContent.parts` (all parts, from `get_parts`).
- Solo, mute, volume and tempo are **local first**. Tempo uses `HTMLAudioElement.playbackRate`
  with `preservesPitch = true` for instant feedback. A changed voice selection, or an exact
  re-render for best quality, calls `synthesize` with an app-only `return: "handle"` flag.
- **Loop A–B** is client-side on the audio element. Measure boundaries come from Verovio's
  timemap ([§6.2](#62-notation-rendering-verovio-in-the-iframe)), scaled by `tempo_factor`.
- **Score cursor:** the same timemap maps playback time to a notehead.
- **Model context:** on each re-render, `ui/update-model-context` records the state ("Alto solo,
  75 %, loop 17–24"), so "make it a bit faster" works in chat.

**Engine changes (small, test first)**

- Optional `part_gains: {part_id: 0.0–2.0}` on `synthesize` for U2 and U5. In `extract_midi`, map
  each gain to MIDI channel volume (CC7). This is additive and backward compatible.
- An optional `count_in_bars` integer for metronome clicks (later).

**Delivering the audio (the iframe cannot read `audio_path`)**

A 3-minute 44.1 kHz stereo 16-bit WAV is about 32 MB, or about 42 MB in base64. That is too large
for one tool result.

- `synthesize` (when the UI is active) stores the file and returns an opaque `audio_id` in
  `structuredContent`.
- An app-only `read_audio_chunk(audio_id, offset, length)` returns at most 1 MB base64 per call.
  The UI assembles a `Blob` and `URL.createObjectURL`.
- Later optimisation: a `quality: "preview"` option renders mono at 22.05 kHz (about 8 MB for
  3 minutes) for the interactive loop.

**Contract**

| Item | Value |
|---|---|
| UI resource | `ui://synth/practice-player` |
| Linked tools | `synthesize` |
| App-callable | `get_parts`, `synthesize` |
| New app-only | `read_audio_chunk(audio_id, offset, length)`, `get_score_xml(audio_id)` (MusicXML for the viewer) |
| `structuredContent` | `{audio_id, duration_seconds, sample_rate, channels, byte_length, parts:[{id,name,included,gain}], tempo_factor}` |
| Model context | Current mix state |
| Display modes | `inline`, `pip` (keep playing while chatting), `fullscreen` |
| Permissions / CSP | None |

**Fallback:** unchanged (`audio_path` in `content`).

**Acceptance criteria**

- AC-S1. `synthesize` with `part_gains={"P1": 0}` produces audio whose RMS for P1's channel range
  is 0 (engine unit test on MIDI CC7).
- AC-S2. `read_audio_chunk` with an unknown `audio_id` returns `{"error_code": "INVALID_PARAMETER"}`.
  It never takes a path.
- AC-S3. Chunks concatenated over `[0, byte_length)` are byte-identical to the WAV on disk.
- AC-S4. Text `content` of `synthesize` is unchanged (regression on today's 64 unit tests).
- AC-S5 (UI). Given a timemap and `tempo_factor = 0.5`, then the loop for m.17–24 starts at twice
  the score time of m.17.

---

### 5.3 render-mcp: Score Viewer

**Use cases**

- U1. See the score inline after any pipeline step (OMR, ABC edit) without opening a file.
- U2. Page through, zoom, and switch between fitting the page width and showing one system per row on a phone.
- U3. Download or print a PDF.
- U4. Highlight one voice part (dim the others) while reading.

**Today:** `render_to_image` gives one PNG path per call and `render_to_pdf` a PDF path. Paging
means another prompt per page (P1, P3).

**Proposed UI** (`ui://render/score-viewer`)

```
+-----------------------------------------------------------------------+
| Score Viewer                 [< Prev] Page 2 / 5 [Next >]  [- 100% +] |
|                              Highlight: [All v]  [Download PDF]       |
+-----------------------------------------------------------------------+
|                                                                       |
|        (Verovio SVG of page 2, responsive, re-flows on resize)        |
|                                                                       |
+-----------------------------------------------------------------------+
|  Page thumbnails:  [1] [2*] [3] [4] [5]                               |
+-----------------------------------------------------------------------+
```

**Interactions**

- Rendered client-side with Verovio WASM from the MusicXML in `tool-input`. Paging, zoom and
  re-flow on `containerDimensions` changes need no tool calls.
- **Download PDF:** an app-only `get_pdf(pdf_id)` returns base64. The UI builds a Blob download.
  If the sandbox blocks downloads, it falls back to `ui/open-link` (see [Open questions](#10-open-questions)).
- **Highlight voice:** client-side CSS on Verovio's per-staff SVG groups.
- `render_to_image` keeps returning the PNG and also adds it as an `ImageContent` block, so
  text-only hosts that show images get a preview as well.

**Contract**

| Item | Value |
|---|---|
| UI resource | `ui://render/score-viewer` |
| Linked tools | `render_to_pdf`, `render_to_image` |
| New app-only | `get_pdf(pdf_id)` |
| `structuredContent` | `{page_count, pdf_id?, backend}` |
| Model context | Current page and highlighted part ("user is looking at page 2, Alto") |
| Display modes | `inline`, `fullscreen` |

**Fallback:** unchanged paths.

**Acceptance criteria**

- AC-R1. The resource HTML is self-contained: it has no `<script src=` or `<link href=` pointing
  off-origin (so no CSP entries are needed).
- AC-R2. `render_to_pdf` returns `structuredContent.pdf_id`, and `get_pdf(pdf_id)` returns bytes
  that start with `%PDF`.
- AC-R3 (UI). Given a 5-page fixture, then Next and Prev move through pages 1–5 and stop at the
  ends.

---

### 5.4 comparer-mcp: Diff Viewer

**Use cases**

- U1. *As a director*, I see where the new edition differs from ours, highlighted on the score.
- U2. I filter changes by voice, measure range and kind (pitch, rhythm, inserted, deleted).
- U3. I click a change and both scores scroll to it.
- U4. I judge OMR quality: compare OMR output with a reference and see the error hotspots.
- U5. I ask the model to explain a specific change.

**Today:** `compare_musicxml` returns a large JSON document and `generate_comparison_report`
returns text. To *see* the diff, the model must call `export_annotated_musicxml` and then chain
`render-mcp` twice (P4, P7).

**Proposed UI** (`ui://comparer/diff-viewer`)

```
+-----------------------------------------------------------------------+
| Compare: Edition A (reference) vs Edition B         Similarity 0.87  |
| [Annotated scores] [Changes (42)] [Report]          ########__        |
+-----------------------------------------------------------------------+
| Filters: Part [Alto v]  Measures [17]-[24]  Kind [x]pitch [x]rhythm   |
|          [x]inserted [x]deleted [ ]articulation                       |
+---------------------------------+-------------------------------------+
| REFERENCE (deletions, old vals) | TARGET (insertions, new values)     |
|  m.17 ==o==(red)o==|==          |  m.17 ==o==(green)o==|==            |
|  m.18 ==o====o=====|==          |  m.18 ==o====o=====|==              |
|      <- scroll-synced by measure ->                                    |
+---------------------------------+-------------------------------------+
| Changes                                                               |
|  > Alto m.17-24   transposed +3 semitones (8 notes)        [Explain]  |
|    Alto m.19 b.2  D5 -> D#5 (pitch)                        [Explain]  |
|    Tenor m.20     measure missing in target                [Explain]  |
+-----------------------------------------------------------------------+
```

**Interactions**

- The app opens on `compare_musicxml` (or the `_files` variant). Summary and grouped changes come
  from `structuredContent`.
- **Annotated scores:** the UI calls `export_annotated_musicxml` (app-callable) and renders both
  documents with Verovio in the iframe. This works because the UI cannot reach `render-mcp`
  anyway.
- **Filters** call `list_changes` with `part` and `measure_range`, or filter the full result
  locally (it is already in `structuredContent`).
- **Click a change:** both panes scroll to `measure_number` and flash the notehead using Verovio
  element IDs.
- **Explain** sends `ui/message`: "Explain change: Alto m.19 b.2 D5 → D#5 (edition B)".
- **Report** tab shows `generate_comparison_report` text.

**Contract**

| Item | Value |
|---|---|
| UI resource | `ui://comparer/diff-viewer` |
| Linked tools | `compare_musicxml`, `compare_musicxml_files`, `generate_comparison_report` |
| App-callable | `list_changes`, `export_annotated_musicxml` |
| `structuredContent` | Full `ComparisonResult` (the model gets the summary and top-N grouped changes in `content`, P7) |
| Model context | Active filters and the selected change |
| Display modes | `inline`, `fullscreen` (two panes need width; on `mobile`, stack the panes vertically) |

**To verify:** that Verovio applies MusicXML `color` attributes on `<note>` and `<notehead>` from
the annotator. If it does not, map the colours to CSS on Verovio element IDs instead (the
annotator already knows the note IDs).

**Acceptance criteria**

- AC-C1. `compare_musicxml.structuredContent` validates against a JSON Schema generated from
  `models.ComparisonResult`, also published as the tool's `output_schema`.
- AC-C2. `content[0].text` for a 500-change diff is under a fixed size budget (for example 8 KB)
  and still contains `similarity` and `summary`.
- AC-C3 (UI). Clicking a change for m.19 scrolls both panes so that m.19 is visible.

---

### 5.5 omr-mcp: Recognition Review

**Use cases**

- U1. After photographing a page, I compare the photo with what was recognised.
- U2. I am warned when a choir (SATB) score was flattened by oemer, and I can re-run with
  Audiveris in one click.
- U3. For several pages I reorder or remove pages before merging.
- U4. While recognition runs (often minutes), I see that it is still working and for how long.
- U5. I hand the result to the next step: render, play, or edit.

**Today:** `recognize_sheet` returns MusicXML and metadata as text. Nobody looks at it next to the
image (P5). The SATB limitation is documented but easy to miss.

**Proposed UI** (`ui://omr/recognition-review`)

```
+-----------------------------------------------------------------------+
| Recognition Review    engine: oemer   staves: 1   measures: 24   38s  |
+-----------------------------------------------------------------------+
| ! This looks like a 4-staff choir score but 1 part was recognised.    |
|   oemer merges SATB staves.   [Re-run with Audiveris (needs 300 DPI)] |
+-----------------------------------+-----------------------------------+
| ORIGINAL PHOTO                    | RECOGNISED                        |
| (zoom/pan; click a measure to     | (Verovio render; measure under    |
|  highlight it on the right)       |  pointer is outlined on the left) |
+-----------------------------------+-----------------------------------+
| Pages: [1][2][3]  (drag to reorder, x to drop)     [Merge pages]      |
| Next:  [Show score] [Play it] [Edit as ABC]        -> posts ui/message|
+-----------------------------------------------------------------------+
```

While running:

```
+--------------------------------------------+
| Recognising page 1 of 3 with oemer...      |
| [=============>            ]  1m 12s       |
| First run downloads ~100 MB of models.     |
+--------------------------------------------+
```

**Interactions**

- The app receives `tool-input` before the result arrives, so it can show the photo and a running
  timer at once (U4). The existing heartbeat progress notifications stay for text hosts.
- **Flattening heuristic:** the warning shows when `engine == "oemer"` and `staves_detected` is
  much lower than the staff count expected from the image. The server can work out that count from
  a cheap staff-line count, exposed as `metadata.staff_systems_estimate`. That needs new engine
  code, so add it test first.
- **Re-run with Audiveris** calls `recognize_sheet` with `engine: "audiveris"`.
- **Next steps** use `ui/message` ("Render the recognised score", "Play the alto part"). The app
  cannot call render or synth itself. It asks the model, which then chains the servers. This is the
  intended pattern for cross-server flows.
- **Preview image:** if the input was a path, an app-only `get_source_preview(job_id)` returns a
  downscaled JPEG (≤ 1600 px) by handle.
- **Measure linking** (photo ↔ score) needs bounding boxes. Audiveris `.omr` output has them;
  oemer does not expose them. Treat this as a stretch goal and support it only with Audiveris.

**Contract**

| Item | Value |
|---|---|
| UI resource | `ui://omr/recognition-review` |
| Linked tools | `recognize_sheet`, `recognize_sheets`, `recognize_sheet_to_file` |
| New app-only | `get_source_preview(job_id, page)` |
| `structuredContent` | `{job_id, musicxml, metadata, pages:[{index, staves_detected, measures}]}` |
| Model context | The user's reorder or drop decisions, and the engine chosen |
| Display modes | `inline`, `fullscreen` |
| Permissions | `camera` (optional, later): photograph a page from inside the app on mobile |

**Fallback:** unchanged.

**Acceptance criteria**

- AC-O1. `recognize_sheet` returns `structuredContent.job_id`, and `get_source_preview(job_id)`
  returns a JPEG no larger than 1600 px on its longest side.
- AC-O2. `get_source_preview` with any string that is not a known `job_id` returns
  `INVALID_PARAMETER`. It never reads a path.
- AC-O3 (UI). Given metadata `{engine: "oemer", staves_detected: 1, staff_systems_estimate: 4}`,
  then the SATB warning and the Audiveris button are shown.

---

### 5.6 musicxml-abc-mcp: ABC Workbench

**Use cases**

- U1. *As a singer*, I ask the model to "fix the typo in bar 12" and review exactly what it
  changed before accepting.
- U2. *As an arranger*, I edit ABC by hand with live notation preview and live error marks.
- U3. I accept or reject the model's change hunk by hunk.

**Today:** `musicxml_to_abc` → the model edits → `abc_to_musicxml`. The user never sees a diff
(P6). Warnings about dropped dynamics and articulations are buried in JSON.

**Proposed UI** (`ui://abc/workbench`)

```
+-----------------------------------------------------------------------+
| ABC Workbench        [Diff] [Edit] [Preview]          valid  0 errors |
+-----------------------------------+-----------------------------------+
| ORIGINAL (from MusicXML)          | PROPOSED (model edit)             |
| X:1                               | X:1                               |
| K:G                               | K:G                               |
| |: G2 AB c2 BA |                  | |: G2 AB c2 BA |                  |
| - d2 ed c2 BA |              [x]  | + d2 ed B2 AG |              [x]  |
+-----------------------------------+-----------------------------------+
| Preview (abcjs or Verovio, changed notes highlighted)                 |
|  ==|==o==o==|==o=(o)=o==|                                            |
+-----------------------------------------------------------------------+
| ! Round-trip drops dynamics and complex articulations (2 warnings)    |
| [Accept selected -> MusicXML]   [Reject all]   [Ask Claude to revise] |
+-----------------------------------------------------------------------+
```

**Interactions**

- The app opens on `abc_to_musicxml`. The "proposed" side is the tool input. The "original" side
  is the last `musicxml_to_abc` result in the session, which the server keeps by handle
  (`abc_id`).
- **Edit** mode debounces `validate_abc` (300 ms, app-callable) and puts errors in the gutter.
- **Accept selected** merges the chosen hunks client-side, calls `abc_to_musicxml`, then
  `ui/update-model-context` with "User accepted hunks 1, 3; result is the current score".
- **Ask Claude to revise** sends `ui/message` with the rejected hunks.

**Preview renderer:** abcjs (MIT, a few hundred KB) renders ABC directly and highlights well.
Verovio also reads ABC, so the app could reuse the shared kit. **Recommendation:** use Verovio for
one renderer across all apps. Use abcjs only if Verovio's ABC import proves too strict for the
output of the custom serializer.

**Contract**

| Item | Value |
|---|---|
| UI resource | `ui://abc/workbench` |
| Linked tools | `abc_to_musicxml`, `musicxml_to_abc` |
| App-callable | `validate_abc`, `abc_to_musicxml` |
| `structuredContent` | `musicxml_to_abc`: `{abc_id, abc, parts_included, warnings}`. `abc_to_musicxml`: `{musicxml, warnings}` |
| Model context | Accept or reject decisions |
| Display modes | `inline`, `fullscreen` |

**Acceptance criteria**

- AC-A1. Hunk merge (a pure TS function): accepting all hunks equals the proposed text, and
  accepting none equals the original.
- AC-A2. Every `musicxml_to_abc` call returns a new `abc_id`, even for identical input. Ids are
  never reused.
- AC-A3 (UI). An invalid ABC edit shows an error marker on the reported line within 500 ms of the
  last keystroke (mock host).

---

### 5.7 All servers: Setup Doctor

**Use case:** a non-developer installs a server, and the model runs `health_check`. Instead of a
wall of text, they get a checklist with one fix per failing item.

```
+-----------------------------------------------------------------------+
| synth-mcp setup                                          NOT READY    |
+-----------------------------------------------------------------------+
|  x  Soundfont      SYNTH_SOUNDFONT_PATH is not set                    |
|     Fix: download TimGM6mb.sf2, then add to your client config:       |
|     "env": {"SYNTH_SOUNDFONT_PATH": "/path/to/TimGM6mb.sf2"}  [Copy]  |
|  v  FluidSynth     OK                                                 |
|  v  music21        OK                                                 |
+-----------------------------------------------------------------------+
|  [Re-check]   [Open SETUP.md]   [Open TROUBLESHOOTING.md]             |
+-----------------------------------------------------------------------+
```

- One shared component. Each server returns a uniform `structuredContent`:
  `{status, checks:[{name, status, version?, hint?, fix_snippet?, doc_url?}]}`.
  omr-mcp already returns nearly this shape internally.
- [Copy] uses `clipboardWrite`. Links use `ui/open-link` to the repo docs.
- **Low priority.** The text output is already good. The main value is standardising
  `health_check` into structured data, which also helps a Phase 2 web PoC.

---

## 6. Shared architecture

### 6.1 Repository layout

```
ui/                                   # NEW - TypeScript workspace (pnpm or npm)
  packages/
    kit/                              # shared: host bridge, theming, ScoreView, Waveform,
                                      #   Meter, DiffList, HealthList
    apps/
      practice-coach/  practice-player/  score-viewer/
      diff-viewer/     recognition-review/  abc-workbench/  setup-doctor/
  vite.config.ts                      # vite-plugin-singlefile -> one HTML per app

<server>/src/<pkg>/ui/
  __init__.py                         # UiRegistry (see 6.4)
  assets/<app>.html                   # built artifact, committed or built in CI
```

- Each app builds to **one self-contained HTML file** with JS, CSS and the Verovio WASM inlined
  (base64). It is copied into each server's package as `package-data`. **Servers stay independent:**
  no server imports another, and each wheel carries its own UI.
- `ext-apps` SDK: use `@modelcontextprotocol/ext-apps` (`App` class) for the handshake
  (`ui/initialize`), notifications, `callServerTool`, `updateModelContext` and display modes.
- Theming: map host `styles.variables` and `theme` to CSS custom properties, with light and dark
  fallbacks.
- The kit is reusable by the **Phase 2 web PoC**. The same components can run with a different
  `HostBridge` implementation that talks HTTP to the servers. That is a strong reason to build the
  kit now rather than one-off pages.

### 6.2 Notation rendering: Verovio in the iframe

| Option | Pros | Cons |
|---|---|---|
| **A. Verovio WASM in the iframe (recommended)** | No cross-server calls. Re-flows instantly on resize or zoom. Gives SVG element IDs for highlighting and a **timemap** for playback and singing cursors. Same engine as `render-mcp` (`verovio>=3`), so output matches the PDFs. | The bundle is several MB, though hosts may cache the resource. Larger memory use on low-end phones. |
| B. Server-side SVG through an app-only tool on each server | A small UI. | `comparer-mcp`, `synth-mcp`, `pitch-mcp`, `omr-mcp` and `musicxml-abc-mcp` would each need Verovio as a Python dependency, duplicating `render-mcp`. A round trip per page or zoom. No timemap without more tools. |
| C. Load Verovio from a CDN (`resourceDomains`) | A small HTML file. | Needs network access and a CSP allowance. Hosts may reject or tighten it. Fails offline, but rehearsal rooms often have poor Wi-Fi. |

### 6.3 Data transport rules

1. **`content` stays exactly as today**, so existing clients and the current test suites (about 580
   tests across the six servers) are not affected. Over time, trim large payloads from `content` *only* when the
   client advertises the UI extension (P7).
2. **`structuredContent` carries the UI's data.** Each linked tool gains an `output_schema`, so
   the contract is explicit and testable.
3. **Opaque handles for binary data.** Ids map to files under `SHEET_MUSIC_OUTPUT_ROOT`, kept in a
   per-process `ArtifactStore` with a TTL. Chunk reads are limited to 1 MB.
4. **The MusicXML for a viewer** comes from `tool-input` (it is already a tool argument) or from an
   app-only getter by handle. Do not re-send it in results.
5. **Cross-server flows go through the model** (`ui/message`), never through direct calls. This
   follows the spec and keeps servers decoupled.

### 6.4 Python side: SOLID structure

A sketch of the module design (not implementation):

```python
# <pkg>/ui/__init__.py  - no engine imports; engine.py still never imports mcp
UI_MIME = "text/html;profile=mcp-app"
UI_EXTENSION = "io.modelcontextprotocol/ui"

@dataclass(frozen=True)
class UiResource:                      # S: describes one resource, nothing else
    uri: str                           # "ui://synth/practice-player"
    asset: str                         # "practice-player.html"
    permissions: dict = field(default_factory=dict)
    csp: dict | None = None

    def tool_meta(self, *, app_only: bool = False) -> dict:
        ui = {"resourceUri": self.uri}
        if app_only:
            ui["visibility"] = ["app"]
        return {"ui": ui}

class UiRegistry:                      # O: add apps by registering; handlers unchanged
    def list_resources(self) -> ListResourcesResult: ...
    def read(self, uri: str) -> ReadResourceResult: ...   # importlib.resources

class ArtifactStore(Protocol):         # D: tools depend on this, not on the filesystem
    def put(self, path: Path, kind: str) -> str: ...
    def read_chunk(self, artifact_id: str, offset: int, length: int) -> bytes: ...
```

- **S (single responsibility):** `engine.py` (music logic), `presenter.py` (engine result →
  `content` + `structuredContent`), `ui/` (resources) and `server.py` (wiring) each do one thing.
- **O (open/closed):** a tool gains a UI by adding `meta=RESOURCE.tool_meta()` to its `Tool(...)`.
  Handler logic does not change.
- **L (Liskov substitution):** `SoundDeviceSource` and `PushedChunkSource` both satisfy
  `AudioSource` (pitch). Any `ArtifactStore` (in-memory for tests, filesystem in production) can
  be swapped in.
- **I (interface segregation):** app-only tools are small, single-purpose endpoints
  (`read_audio_chunk`, `get_pdf`), not one general "fetch anything" tool.
- **D (dependency inversion):** handlers receive the store and source by injection (module-level
  default, overridable in tests).

Wiring in `server.py` follows the pattern in `CLAUDE.md`:
`Server(name, on_list_tools=..., on_call_tool=..., on_list_resources=_on_list_resources, on_read_resource=_on_read_resource)`.

### 6.5 Capability negotiation

- Read `capabilities.extensions["io.modelcontextprotocol/ui"]` from the client's `initialize`.
- If it is absent, **still** attach `meta` (hosts ignore it) and still return `structuredContent`
  (harmless). Trim `content` only when the extension is present. One code path, one behaviour
  switch.
- Hide app-only tools from model-facing listings in hosts without the extension. The spec only
  obliges supporting hosts to honour `visibility`. Filtering them out of `tools/list` for other
  clients keeps the model's tool list unchanged for Cursor and the Claude Code CLI.

---

## 7. Security

| Risk | Mitigation |
|---|---|
| An app-only tool becomes an **arbitrary file read** (for example `read_audio(path)`). | Never accept paths in app-only tools. Use opaque ids from `ArtifactStore`, resolve only inside `SHEET_MUSIC_OUTPUT_ROOT`, and apply the existing rules about not following symlinks or reusing pre-created directories. Write tests for traversal attempts. |
| Memory exhaustion through large chunk reads or push floods | Cap chunks at 1 MB, cap pushes per second per session, and evict with a TTL. |
| UI resource tampering or supply chain | The built HTML is generated in CI from a locked `package-lock.json`. Dependabot covers `ui/`. Actions stay SHA-pinned. Add `unicode-smuggling-guard` to the `ui/` sources. |
| External script injection | Inline everything. Declare no `csp` (most restrictive default). Test AC-R1 asserts there are no off-origin `src` or `href`. |
| Microphone privacy | Ask for `microphone` only on the pitch app, and only for option B. Start capture only after the user presses Start. Show a recording indicator. Never persist pushed audio. |
| Prompt injection through `ui/message` or `updateModelContext` | Only fixed templates with values from structured data. Never forward free text from MusicXML metadata (titles, lyrics) as instructions. Quote it. |

---

## 8. Testing strategy (TDD)

Write the tests first for each app, in this order:

1. **Server contract (pytest, unit, default run):**
   - `list_tools()` → the expected `meta.ui.resourceUri` and visibility (AC-P1 and similar).
   - `UiRegistry.read(uri)` → MIME type, non-empty HTML, no off-origin assets (AC-R1).
   - `structured_content` validates against the tool's `output_schema` (AC-C1).
   - Regression: `content` is byte-identical to today's for the existing fixtures.
   - App-only tool guards: unknown handle, traversal strings, oversize chunk.
2. **Engine changes (pytest, unit):** `part_gains` (AC-S1), `PushedChunkSource` (AC-P4),
   `staff_systems_estimate` (AC-O3), each written before the code.
3. **UI logic (Vitest, in `ui/`):** pure functions such as hunk merge (AC-A1), timemap → loop
   bounds (AC-S5), and snapshot → meter state.
4. **UI integration (Playwright, preinstalled Chromium):** load each built HTML in a **mock host
   page** that implements the host side of `postMessage` JSON-RPC (`ui/initialize`, then replay
   `tool-input` and `tool-result` fixtures), answers `tools/call` from fixtures, and records
   `ui/message` and `update-model-context`. AC-P5, AC-R3, AC-C3, AC-O3 and AC-A3 live here.
5. **End-to-end (manual, `@pytest.mark.manual`):** real hosts such as Claude Desktop and VS Code,
   with a checklist per app.

Integration tests that start the real server and read resources over stdio are marked
`@pytest.mark.integration`, per the hard rules.

---

## 9. Roadmap

| Phase | Deliverable | Depends on | Size |
|---|---|---|---|
| **0. Spike** | `ui/` workspace and kit host bridge. A minimal Score Viewer on `render-mcp`, end to end in one real host. Check that Verovio WASM loads in the sandbox, its bundle size, and colour support. | none | S |
| **1. P0** | Practice Coach (server mic, option A). Practice Player with `audio_id` chunking and the `part_gains` engine change. | 0 | L |
| **2. P1** | Score Viewer polish, Diff Viewer, Recognition Review (without measure linking). | 0 | L |
| **3. P2** | ABC Workbench, and the pitch browser mic (option B, `AudioSource` refactor). | 1 | M |
| **4. P3** | Setup Doctor with a standard `health_check` `structuredContent` across all six servers. | 0 | S |
| **5. Reuse** | Ship the kit components in the Phase 2 web PoC through an HTTP `HostBridge`. | 1–3 | M |

Each phase updates the server docs (`HANDOVER.md`, `PLAN.md`, `requirements.md`,
`architecture.md`) per the repository's document update policy.

---

## 10. Open questions

1. **Committed or CI-built HTML assets?** Committing keeps `uvx <server>` working from source
   without Node. Building in CI keeps the repo lean but needs a release-time build step.
   *Leaning:* build in CI and include the files in the sdist and wheel. Commit nothing.
2. **Bundle size budget.** Is a resource of several MB (Verovio WASM inlined) acceptable in the
   target hosts, especially on mobile? To be measured in the Phase 0 spike.
3. **Downloads from the sandbox.** Do target hosts allow Blob downloads (`get_pdf`) from the
   iframe? If not, use `ui/open-link` or tell the user where the file is.
4. **Browser mic priority.** Should option B (browser microphone) move into Phase 1, given the
   Phase 3 Android goal?
5. **Per-part gain semantics.** Linear 0.0–2.0 on CC7, or dB? Should "my part" be a named
   preset ("learning track for Alto")?
6. **Pitch polling rate.** Is 5–10 tool calls per second through the host acceptable for every
   target host, or do some throttle app-initiated `tools/call`?

---

## References

- MCP Apps specification (SEP-1865), stable 2026-01-26:
  <https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx>
- MCP Apps SDK and examples: <https://github.com/modelcontextprotocol/ext-apps>
- Verovio (notation engraving, WASM toolkit, timemap): <https://www.verovio.org>
- abcjs: <https://github.com/paulrosen/abcjs>
- Repository context: [README.md](../../README.md), [docs/conventions.md](../conventions.md),
  [docs/SETUP_UX_PLAN.md](../SETUP_UX_PLAN.md), each server's `docs/architecture.md`.
