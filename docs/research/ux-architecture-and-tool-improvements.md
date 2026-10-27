# UX improvements: architecture and MCP tool changes

**Status:** Research / proposal; decisions recorded in [§9](#9-decisions). No code has been
written. Next step: [Wave 1 plan](ux-wave1-plan.md).
**Date:** 2026-10-27
**Companion to:** [mcp-apps-ux-proposal.md](mcp-apps-ux-proposal.md). That document adds UIs; this
one changes what sits underneath them: tool contracts, data flow and packaging. Most items help
**every** host, including the Claude Code CLI and Cursor, which never show an MCP App.

---

## Table of contents

1. [Summary](#1-summary)
2. [Evidence: the MusicXML round-trip problem](#2-evidence-the-musicxml-round-trip-problem)
3. [Architecture changes (A1–A7)](#3-architecture-changes)
4. [Cross-cutting tool contract changes (B1–B6)](#4-cross-cutting-tool-contract-changes)
5. [Per-server tool changes (C1–C26)](#5-per-server-tool-changes)
6. [Compatibility and versioning](#6-compatibility-and-versioning)
7. [Acceptance criteria for the top items (TDD)](#7-acceptance-criteria-for-the-top-items-tdd)
8. [Roadmap and interplay with MCP Apps](#8-roadmap-and-interplay-with-mcp-apps)
9. [Decisions](#9-decisions)

---

## 1. Summary

The servers work, but chaining them is expensive and fragile. **Every tool takes the whole score
as an inline MusicXML string**, so the model has to copy tens of thousands of tokens of XML from
one tool result into the next tool call. That is the single largest UX problem, and it gets worse
with each step a user adds ([§2](#2-evidence-the-musicxml-round-trip-problem)).

The ten changes worth doing first, ordered by UX gain per unit of effort:

| # | Change | Gain | Effort | Breaking? |
|---|---|---|---|---|
| **A1** | **Score references:** pass a file path instead of inline MusicXML, in and out of every server. | Removes the ~29k-token copy per tool call for a 24-bar chorale. Chains become fast and reliable. | M | No (additive) |
| **B1** | **Unified part selector:** accept an ID, a name or a voice role (`"P2"`, `"Alto"`, `"A"`). Fixes real bugs: unnamed parts can't be selected at all, and parts sharing a name can't be told apart. | Ends "Part … not found" retry loops. | S | No |
| **B3** | **Tool annotations and titles** (`readOnlyHint` and others). | Hosts can skip permission prompts for read-only tools and show friendly names. | S | No |
| **B4** | **Inline images and file links** in results (`ImageContent`, `ResourceLink`). | The score preview appears in chat even without MCP Apps. | S | No |
| **C8** | **Learning-track mix** (`part_gains` plus presets, D3) on `synth-mcp`. | The most-requested choir practice format. | S | No |
| **B2** | **`measures` range** on render, synth, ABC and pitch. | "Play/show/practise bars 17–24" in one call. | M | No |
| **C1** | **OMR `engine: "auto"`**: picks Audiveris for choir scores. | Users no longer need to know about the SATB limitation. | M | Default change in a later minor |
| **C16** | **ABC fragment edit** (`apply_abc_edit`): edit bars 12–14 of one part and merge the change back. | Tiny context, and dynamics and lyrics elsewhere survive. | M | No |
| **C23** | **Pitch session idle timeout:** close the microphone automatically. | Privacy: today the mic stays open if `stop_monitoring` is never called. | S | No |
| **A4** | **MCP Tasks for long jobs:** OMR, long synthesis. | Multi-minute OMR no longer blocks the conversation, and the user can cancel it. | M | No |

Larger bets, decided in [§9](#9-decisions):

- **A3:** an optional all-in-one `sheet-music-mcp` distribution (one config entry, and
  cross-server MCP Apps become possible).
- **A2:** a shared core library to stop copying the same code across the six servers.
- **C24:** consolidating comparer-mcp's five compare tools into one.

---

## 2. Evidence: the MusicXML round-trip problem

Measured on Bach chorales from the music21 corpus, written as MusicXML by music21 (the same
writer the servers use):

| Score | Parts | Measures | Notes | MusicXML size | Approx. tokens* |
|---|---|---|---|---|---|
| BWV 66.6 | 4 | 10 | 165 | 49,957 B | ~17k |
| BWV 269 | 4 | 24 | 229 | 87,224 B | ~29k |
| Typical 60–80 bar choir piece (extrapolated) | 4 | 70 | ~700 | ~250 KB | ~80k |

\* Assumes about 3 bytes per token for XML. This is an estimate, not a tokenizer count.

The README example, "Convert this photo to MusicXML and play me the alto part at 80 % tempo":

| Step | Today | With A1 (score references) |
|---|---|---|
| `recognize_sheet` result | ~29k tokens **into** context | ~150 tokens: path, part list and summary |
| `synthesize` call | ~29k tokens **generated** by the model as arguments | ~40 tokens: `{"musicxml_path": "...", "parts": ["Alto"], "tempo_factor": 0.8}` |
| Total for 2 steps | ~58k tokens, with the generated half produced one token at a time | ~200 tokens |

Generated tokens are the slow and risky part:

- They are produced sequentially, so copying a 29k-token document takes minutes.
- A longer piece can exceed a host's per-response output limit.
- One dropped `</note>` while copying makes the next tool return `INVALID_INPUT`.

Every extra step (render, then pitch practice) repeats the copy. Today the
`recognize_sheet_to_file` and `compare_musicxml_files` variants do not help: **no downstream
server accepts a MusicXML path**, so a saved file still has to be read back into context.

---

## 3. Architecture changes

### A1. Score references instead of inline MusicXML (P0)

**Change.** Every tool that takes `musicxml`, `reference_xml` or `target_xml` also accepts a
path sibling, with exactly one of the two required:

```json
"oneOf": [ {"required": ["musicxml"]}, {"required": ["musicxml_path"]} ]
```

- `musicxml_path` accepts `.musicxml`, `.xml` and compressed `.mxl` everywhere. Today only
  comparer-mcp reads `.mxl`. `.mxl` is much smaller (BWV 269: 87 KB as MusicXML, 4.9 KB as
  `.mxl`, about 18×) and is what Audiveris and MuseScore export.
- Producers return a path and a small summary by default when the score is large:
  - `recognize_sheet` gains `return: "auto" | "path" | "inline"`. `auto` returns inline below
    about 8 KB and a path above it, so small scores keep today's behaviour.
  - `abc_to_musicxml` and `export_annotated_musicxml` gain the same option.
- The summary is a small `score_summary` object, also used by `describe_score` (C18):
  `{title, parts:[{id,name,range}], measures, key, time, tempo_bpm}`.

**Read-access policy (security).** Reading arbitrary paths is a new capability, so it is
confined:

1. Allowed roots are the client's **MCP roots** (`roots/list`, when the client supports them),
   plus `SHEET_MUSIC_OUTPUT_ROOT`, plus an optional `SHEET_MUSIC_INPUT_ROOTS` (path list).
2. Resolve symlinks, reject anything outside the roots, and allow only the suffixes above.
   Enforce the size limit (`FILE_TOO_LARGE`).
3. Parse errors never echo file contents, only the line and column, so a misdirected read
   cannot leak a non-music file into context.

**Why paths and not opaque handles.** The servers are separate processes. A file path in a shared
root is the only reference all six can resolve without a shared store. With the all-in-one
distribution (A3), in-memory handles would also become possible.

```
Today:   omr --(29k tokens XML)--> model --(29k tokens XML)--> synth
A1:      omr --writes--> $ROOT/scores/ave-verum.mxl
             --(path + summary, ~150 tokens)--> model --(path, ~40 tokens)--> synth --reads--> file
```

### A2. Shared core library (P1, owner decision)

**Problem.** The same infrastructure is copied by hand across servers. `confine_output_path` is
in 3 servers and the `_on_call_tool` validation and error wrapper in all 6. A1, B1, B2, B5 and the
MCP Apps `UiRegistry` would each add another copy to 4–6 servers, and they would drift apart.

**Change.** Add a small PyPI package `sheet-music-mcp-core` with no heavy dependencies:

| Module | Responsibility (SRP) |
|---|---|
| `paths` | Read and write confinement (A1), MCP roots, suffix and size rules |
| `scores` | `load_score(musicxml \| musicxml_path)` → text. `.mxl` unzip. `score_summary`. |
| `parts` | The part selector resolver (B1) |
| `errors` | The `{error, error_code, hint?, choices?}` envelope (B5) and the `ProcessingError` base |
| `wiring` | `make_call_tool_handler(list_tools, call_tool)`: schema validation and `isError`, used by all six |
| `ui` | `UiResource`, `UiRegistry`, `AssetSource` (MCP Apps spike) |

**Independence is kept:**

- Each server still installs and deploys alone (`uvx render-mcp` pulls in `core` as an ordinary
  dependency).
- Each server keeps its own venv. `core` never imports music21, so the engines stay unit-testable
  with no MCP imports.
- Version skew is handled with semver, pinning `core>=X.Y,<X+1`, and a shared conformance test
  suite that each server runs.

**Alternative** if the owner prefers zero shared dependencies: keep copies, but add one
conformance suite (`tests/conformance/`) that every server runs against its own copy. This is
cheaper now and adds more drift risk later.

### A3. Optional all-in-one distribution (P2, owner decision)

**Problem.**

- Non-developers configure up to six servers, six `health_check`s and six sets of system
  dependencies.
- MCP Apps cannot call tools on other servers, so no single practice screen can combine the
  score (render), audio (synth) and singing feedback (pitch).

**Change.** A seventh package, `sheet-music-mcp`, that composes the six servers' tool lists in one
process:

- One client config entry: `uvx sheet-music-mcp[omr,synth,pitch]`. Extras keep heavy
  dependencies optional (oemer/ONNX, FluidSynth, PortAudio). Tools whose extra is missing are
  hidden from `tools/list` and reported by one `health_check`.
- An in-process score store gives opaque `score://` handles, with no file round trip.
- One MCP App could then offer the full "Rehearsal Studio": score, mixer, singing cursor and
  feedback.
- Tool names stay the same. They are already unique across servers, except `list_capabilities`
  and `health_check`, which merge.

**Kept as is:** the six standalone servers remain the primary, tested units, and the composite
only imports them.

**Cost:** Python 3.12+ (pitch-mcp's floor), a combined dependency resolution that must be tested,
and another release artifact. **Recommendation:** decide after A1 and A2. Prototype it as the
Phase 2 web PoC's backend, which needs the same composition anyway.

### A4. MCP Tasks for long-running work (P1)

OMR takes minutes, and so do Audiveris and synthesis of long scores. The installed SDK supports
task-augmented tools (`Tool.execution.task_support`). Declare it `optional` on:

- `recognize_sheet`, `recognize_sheets` and `recognize_sheet_to_file`
- `synthesize`
- `compare_musicxml_files`

Hosts that support Tasks then return immediately with a task ID. The user keeps chatting, the
host shows status, and the user can cancel. Hosts without support keep today's synchronous call
with heartbeat progress. Engine code is unchanged, because the existing
`_run_with_progress` (`asyncio.to_thread`) already runs the work off the event loop.

### A5. Server `instructions` at initialize (P1)

`Server(instructions=...)` exists in the SDK and costs one string per server. Use it for the
routing knowledge the model currently has to discover through `list_capabilities` or failure:

- omr: "For choir (SATB) scores use `engine='auto'` or `'audiveris'` (300+ DPI)."
- All servers: "Prefer `musicxml_path` over inline `musicxml` when chaining."
- pitch: "Always call `stop_monitoring`; sessions auto-close after N minutes idle."

### A6. MCP Prompts for the core workflows (P2)

Prompts appear as slash commands or menu items in hosts, which makes workflows discoverable for
non-technical singers. Each server exposes the prompts whose entry point it owns:

| Prompt | Server | Arguments | What it does |
|---|---|---|---|
| `digitize-score` | omr | image(s), choir? | OMR with the right engine, then describe and offer render or play |
| `learn-my-part` | synth | score, voice, tempo | Learning-track mix at 75 %, then an offer to speed up |
| `practice-session` | pitch | score, voice, bars | Load, start, poll, stop, then feedback |
| `compare-editions` | comparer | two scores | Report, then annotated scores |
| `fix-a-bar` | musicxml-abc | score, part, bars, problem | Fragment export, edit, `apply_abc_edit` |

### A7. One-click install and desktop platforms (P2, revisit scope)

`SETUP_UX_PLAN.md` puts macOS and Windows out of scope for this phase, and `install.sh` is apt
only. Choir members mostly use macOS and Windows. Proposal for the next setup phase:

- Ship **MCP Bundles (`.mcpb`)** for Claude Desktop, giving one-click install with a soundfont
  file picker in the install dialog.
- Document Homebrew and winget equivalents of the system libraries.

---

## 4. Cross-cutting tool contract changes

### B1. Unified part selector (P0, includes a bug fix)

**Today's inconsistency:**

| Server / tool | Parameter | Matches on |
|---|---|---|
| synth `synthesize` | `part_ids` (array) | ID |
| musicxml-abc `musicxml_to_abc` | `part_id` | music21 `part.id`, exact |
| pitch `analyze_recording`, `load_score` | `part_id` | music21 `part.id`, exact |
| comparer `list_changes` | `part` | name, case-insensitive |
| comparer options | `part_filter` | name |

> **Corrected 2026-10-27** after testing with real scores ([core library review](core-library-review.md#f1)).
> An earlier version of this section said that `"Soprano"` fails because the IDs are `P1`…`P4`.
> That is wrong.

The servers match on music21's `part.id`, and music21 (10.x) does not keep the MusicXML part ID
there:

| Score | MusicXML `<score-part id>` | music21 `part.id` | Effect today |
|---|---|---|---|
| Named parts (`Soprano`, `Alto`, …) | `P1`, `P2`, … | the part name (`"Soprano"`) | `"Soprano"` works by accident. The real ID `"P1"` and `"soprano"` (lower case) fail. |
| Two parts with the same name (`Tenor`, `Tenor`; `Voice`, `Voice`) | `P3`, `P4` | `"Tenor"`, `"Tenor"` | One part cannot be selected on its own. |
| Unnamed parts (common in OMR output) | `P1`, `P2` | a Python object number such as `140320038121744`, **different on every parse** | `get_parts` returns an ID that the next call can never match, so the part cannot be selected at all. |

The model then has to call `get_parts` (which only exists on synth-mcp) and retry, or cannot
succeed at all.

**Change.** One resolver, shared or copied (A2), used by every part parameter. It matches in this
order:

1. Exact ID (`P2`)
2. Name, case-insensitive (`alto`)
3. Voice role or abbreviation (`A`, `Alt`, `Contralto`). Divided parts match as `Alto 1` and
   `A1`.

On no match or an ambiguous match, return `INVALID_PARAMETER` with `choices` (B5). Parameter
names converge on `parts` (array) and `part` (single). Old names keep working as aliases.

### B2. `measures` range everywhere (P1)

Accept `measures: [start, end]` (inclusive, using the score's printed measure numbers) on:

- `render_to_pdf` and `render_to_image`: show bars 17–24 only.
- `synthesize`: play bars 17–24. Combine with `repeat` (C9) for looping.
- `musicxml_to_abc`: export a fragment, giving smaller context for edits (C16).
- `load_score` and `analyze_recording`: practise bars 17–24 only.

comparer-mcp already has `measure_range`. Rename it to `measures` with an alias.

### B3. Tool annotations and titles (P0, small)

| Annotation | Tools |
|---|---|
| `readOnlyHint: true` | all `list_*`, `health_check`, `get_parts`, `describe_score`, `musicxml_to_abc`, `validate_abc`, every comparer tool, `get_current_position`, `analyze_recording` |
| `destructiveHint: false`, `idempotentHint: false` | tools that write files (they never overwrite) |
| `openWorldHint: false` | all tools, except the first Audiveris and model download (`true` on omr recognize tools) |
| `title` | Human names for host UIs: "Recognise sheet music", "Play voice parts", and so on |

Hosts use these hints to auto-approve read-only tools or group them, which means fewer permission
prompts for the user.

### B4. Richer result content (P0, small)

- `render_to_image` (PNG) adds an **`ImageContent`** block next to today's JSON. Hosts that show
  images (Claude Desktop, claude.ai, VS Code) then show the page inline with no MCP App.
- Every tool that writes a file adds a **`ResourceLink`** (`file://` URI, MIME type, size), so
  hosts can show a clickable file chip instead of a bare path string.
- Linked tools add `structuredContent` and `outputSchema`. The MCP Apps spike already plans this
  for render.
- **`AudioContent`** only for short clips (C13, under about 200 KB). Full practice tracks stay as
  files.

### B5. Actionable errors (P1)

Extend the error envelope in `docs/conventions.md` with optional fields. This is backward
compatible:

```json
{"error": "Part 'Sopran' not found", "error_code": "INVALID_PARAMETER",
 "hint": "Use one of the listed parts", "choices": ["Soprano (P1)", "Alto (P2)", "Tenor (P3)", "Bass (P4)"]}
```

`hint` holds the fix (for example "re-run with engine='audiveris'", or "scan at 300+ DPI").
`choices` holds valid values. The model can then recover in one step without a lookup call.

### B6. Tool surface tidy-up (P2)

- Remove the deprecated `list_supported_formats` (omr) at the next minor release.
- Keep `list_capabilities` as the Phase 2 discovery contract, and move model-facing guidance to
  `instructions` (A5).

---

## 5. Per-server tool changes

Effort: S = under a day, M = 1–3 days, L = more than 3 days. "New" means a new tool. Everything
else is a new optional parameter or output field.

### omr-mcp

| # | Change | UX gain | Effort |
|---|---|---|---|
| C1 | `engine: "auto"`. Count staves per system on the image (a cheap projection profile). If there are 3 or more and Audiveris is available, use Audiveris. Otherwise use oemer and add a warning. Make it the default in a later minor release. | Choir users get correct SATB parts without knowing the engines exist. Today's known limitation becomes automatic. | M |
| C2 | **PDF input** (scanned PDF scores, the most common thing a choir receives): split pages with `pypdfium2`, rasterise at 300 DPI, then run `recognize_sheets`. | No manual screenshotting per page. | M |
| C3 | **Pre-flight DPI check** before Audiveris. Today a low-resolution image fails only *after* the Audiveris run. | Fails in under a second with a fix hint, instead of after minutes. | S |
| C4 | `warnings[]` in results: parts fewer than staves, empty measures, measure-count mismatch across parts, very low note density. | Problems surface before singing starts. | S |
| C5 | Return path plus summary by default (A1). | ~29k fewer tokens per page. | in A1 |

### render-mcp

| # | Change | UX gain | Effort |
|---|---|---|---|
| C6 | `layout` presets: `a4`, `letter`, `phone` (one system per page, large staff), `large-print`. | Readable on a phone at rehearsal. Large print for older singers. | S |
| C6b | `parts` filter: render a single-voice part score. | Each singer prints only their own part. | S |
| C6c | `transpose` (semitones or target key). Also on synth (C14). | Choirs often change key for their range. | S |
| C7 | PNG as `ImageContent` inline (B4). | Instant preview in any image-capable host. | in B4 |

### synth-mcp

| # | Change | UX gain | Effort |
|---|---|---|---|
| C8 | `part_gains` 0.0–2.0, plus `preset: "learning" \| "karaoke" \| "equal"` with `focus_part` (D3). | Learning tracks (your part loud) and karaoke (your part muted). | S |
| C9 | `measures` (B2) and `repeat: 1–20`. | Drill a passage in a loop. | S |
| C10 | `count_in_bars` and `metronome: bool` (click on the GM percussion channel). | Singers come in on time. Practising with a click. | S |
| C11 | `timbre: "piano" \| "choir" \| "organ"` (GM programmes 0, 52 and 19). | Piano is clearer for learning notes and "choir aahs" for blend. Today the timbre is whatever music21 assigns. | S |
| C12 | `format: "wav" \| "flac" \| "ogg"` (FluidSynth `-T`, falling back to WAV). | Files about 5–10× smaller, easy to send to a phone or share with the section. | S |
| **C13 (new)** | `starting_pitches(score, parts?)` returns a short clip that plays each part's first note, then the chord, plus text: "S: D5, A: A4, T: F#4, B: D3". | Replaces the pitch pipe. Asked for at every rehearsal. | S |
| C14 | `transpose` (shared with C6c). | Practise in the performance key. | S |

### musicxml-abc-mcp

| # | Change | UX gain | Effort |
|---|---|---|---|
| C15 | **Measure-numbered ABC:** emit `%m17`-style comments, or ABC line breaks aligned to measure numbers. | The model can reliably find "bar 17" when editing. Today it has to count bar lines. | S |
| **C16 (new)** | `apply_abc_edit(score, part, measures, abc)` replaces only those measures of that part in the original MusicXML. Everything else (other parts, dynamics, lyrics, layout) is kept byte-for-byte. Returns a path (A1) and a change summary. | Edits stay small (one fragment, not the whole score), and unedited material no longer loses dynamics or articulations in the round trip (today's documented loss). | M |
| C17 | `validate_abc` returns `line`, `column` and `measure` for each error. | Precise fixes. Supports the inline markers in the ABC Workbench app. | S |
| **C18 (new)** | `describe_score(score)` returns title, composer, key, time, tempo, parts (ID, name, clef, range), measures, has_lyrics and duration. It is small, read-only JSON. | The model answers "what is this piece / which parts" without converting the whole score. Replaces most `get_parts` and `musicxml_to_abc` calls made just for orientation. | S |

### pitch-mcp

| # | Change | UX gain | Effort |
|---|---|---|---|
| **C19 (new)** | `start_practice(score, part, tempo_bpm?, measures?)` does `load_score` and `start_monitoring` in one call. | One turn fewer for every practice run. | S |
| C20 | `get_updates(session_id, since?, wait_ms?)` returns the note events completed since a cursor (each with its accuracy) and the current position. `wait_ms` long-polls for up to 2 s. | Without an MCP App, each model poll loses nothing between polls and fewer polls are needed. | M |
| C21 | Phone recordings: accept `.m4a`, `.mp3`, `.ogg` and `.flac` (via `soundfile` or `audioread`/ffmpeg when present, otherwise a clear `UNSUPPORTED_FORMAT` with a hint), and `audio_base64`. | Voice memos from a phone work directly. | S–M |
| C22 | `highlights[]` in summaries in plain musical language: "flat on the high E's in m.12–14 (−35 c avg)". | Feedback a singer can act on. Less reasoning over per-note arrays. | S |
| C23 | **Idle timeout:** auto-stop and summarise a session after N minutes without polls (env `PITCH_SESSION_IDLE_MINUTES`, default 10). Also `list_sessions`. | Privacy: today the microphone stays open until `stop_monitoring` is called, which a model can forget. `list_sessions` recovers a lost `session_id`. | S |

### comparer-mcp

| # | Change | UX gain | Effort |
|---|---|---|---|
| C24 | **Consolidate** `compare_musicxml`, `compare_musicxml_files`, `quick_similarity`, `list_changes` and `generate_comparison_report` into `compare_scores(reference, target, detail: "summary" \| "changes" \| "report" \| "full", parts?, measures?, options?)`. Inputs accept a string or a path (A1). Old names stay as deprecated aliases for one minor release. | Five overlapping tools become one. Fewer wrong-tool picks, and a smaller tool list for every host. | M |
| C25 | `export_annotated_musicxml` writes two files and returns paths (A1) instead of two full MusicXML documents in context. | Up to about 60k fewer tokens for a 24-bar chorale pair. | S |
| C26 | `detail: "report"` output as a Markdown table grouped by part and measure range. | Reads well in chat. | S |

---

## 6. Compatibility and versioning

1. **Additive first.** New parameters are optional. New output fields sit alongside the old ones,
   and `content` stays compatible. The default `pytest` suites must pass unchanged at every step.
2. **Default changes** (C1 `engine: "auto"`, A1 `return: "auto"` thresholds) ship off by default
   in minor N and become the default in N+1, with a changelog note.
3. **Deprecations** (old parameter names, C24 aliases, `list_supported_formats`) log a warning
   for one minor release, are marked "(Deprecated)" in the tool description, and are removed in
   the next.
4. **`docs/conventions.md` changes** (B5 error fields, B1 part semantics, A1 path policy) are made
   first, so all six servers implement one written contract.

---

## 7. Acceptance criteria for the top items (TDD)

Written as failing tests to start from.

**A1. Score references**

- Given a fixture written to `$SHEET_MUSIC_OUTPUT_ROOT/s.mxl`, when `synthesize` is called with
  `musicxml_path`, then the audio equals the audio from the inline call (same duration and
  parts).
- Given `musicxml_path` outside every allowed root (`/etc/passwd`, `../x.musicxml`, or a
  symlink pointing out), then `INVALID_PARAMETER`, and the error text contains no file content.
- Given both `musicxml` and `musicxml_path`, or neither, then schema validation fails.
- Given `recognize_sheet` with `return: "auto"` and a result over the threshold, then `content`
  holds a path and `score_summary`, and contains no `<score-partwise`.

**B1. Part selector**

- `resolve(["Soprano"])`, `resolve(["soprano"])`, `resolve(["S"])` and `resolve(["P1"])` all
  return `["P1"]` for the OMR fixture.
- `resolve(["Alto"])` on a score with `Alto 1` and `Alto 2` raises an ambiguity error whose
  `choices` lists both.
- Regressions that fail today: `load_score(part="P1")` succeeds on a named SATB fixture. An
  unnamed two-part fixture can be selected with `"P2"`, and gives the same ID on every call. In a
  score with two `Tenor` parts, `"P4"` selects only the second.

**C8. Learning track**

- `part_gains={"P2": 0}` puts CC7 = 0 on P2's channel in the generated MIDI.
- `preset="learning", focus_part="Alto"` gives Alto CC7 above every other part's CC7.

**C23. Idle timeout**

- With an injected fake clock, a session with no polls for `PITCH_SESSION_IDLE_MINUTES` is
  stopped, its stream is closed, and `get_current_position` returns `SESSION_NOT_FOUND`, with a
  `hint` that the session timed out.

**B3. Annotations**

- Every tool in a server's read-only list has `annotations.read_only_hint is True`, and no tool
  that writes files has it.

---

## 8. Roadmap and interplay with MCP Apps

| Wave | Items | Unlocks |
|---|---|---|
| **1. Contract foundation** ✅ ([plan](ux-wave1-plan.md)) | conventions.md update, B1, B3, B4, B5, C3, C23, A5 | Fewer retries and prompts, safer mic handling. All small. |
| **2. Score references** ✅ ([plan](ux-wave2-plan.md)) | A1, C5, C25, C18 (and A2 if approved, since A1 is its first client) | Fast and reliable chaining. The MCP Apps' "handles not paths" rule reuses A1's path policy. |
| **3. Practice features** | C8–C11, C13, B2, C19, C22 | The Practice Player and Practice Coach apps (proposal §5.1–5.2) need C8, B2 and C22. |
| **4. Smarter OMR and editing** | C1, C2, C4, C15–C17, A4 | Recognition Review and ABC Workbench apps (proposal §5.5–5.6). |
| **5. Consolidation and distribution** | C24, B6, A6, A7, A3 (if approved) | One install. Cross-server Rehearsal Studio app. |

The MCP Apps Phase 0 spike (render-mcp Score Viewer) is independent of all waves and can run in
parallel. Wave 1's B3 and B4 also apply to render-mcp and can share its PR.

---

## 9. Decisions

Agreed with the project owner on 2026-10-27.

| # | Question | Decision | Consequence |
|---|---|---|---|
| E1 | A2: how to share the copied plumbing | **Shared core library** `sheet-music-mcp-core` on PyPI, with no heavy dependencies. | Each server depends on it and still installs alone. Wave 1 bootstraps it ([plan](ux-wave1-plan.md)). |
| E2 | A3: all-in-one distribution | **Later, as the Phase 2 backend.** Decide after A1 and A2 land. | The six standalone servers stay primary. No near-term work. |
| E3 | C24: merge the comparer tools | **Merge into `compare_scores`.** The old names stay as deprecated aliases for **one** minor release, then are removed. | Wave 5. |
| E4 | A1: folders servers may read scores from | **The output root, plus MCP client roots, plus an optional `SHEET_MUSIC_INPUT_ROOTS` setting** from day one. | Wave 2. The policy goes in `core.paths`. |
| E5 | A7: platforms for the next setup phase | **`.mcpb` bundles** for one-click Claude Desktop install. | ⚠️ Claude Desktop runs only on macOS and Windows, so bundles need at least documented macOS and Windows setup for the system libraries (Cairo, FluidSynth, PortAudio). Full macOS and Windows installers stay out of scope. To be confirmed when Wave 5 is planned. |
| E6 | C1: when `engine: "auto"` becomes the default | **Opt-in first, the default one minor release later**, with a changelog note. | Wave 4. |
| E7 | C18: where `describe_score` lives | **In the core library, exposed by every server that takes a score.** | It must parse MusicXML without music21 (stdlib `xml.etree`) so the core stays light. Wave 2, together with the A1 score loader. |
| E8 | Next step | **Plan Wave 1 test-first** for approval. | [ux-wave1-plan.md](ux-wave1-plan.md) |
