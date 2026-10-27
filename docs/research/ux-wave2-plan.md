# UX Wave 2 plan: score references

**Status:** In progress
**Date:** 2026-10-27
**Parent:** [ux-architecture-and-tool-improvements.md](ux-architecture-and-tool-improvements.md),
roadmap wave 2 (A1, C5, C25, C18), decisions E4 and E7.
**Builds on:** [ux-wave1-plan.md](ux-wave1-plan.md) (core library 0.1.0).

## Progress

| Step | Content | Status |
|---|---|---|
| 1 | Plan and conventions contract (Score References) | ⏳ |
| 2 | Core 0.2.0: `paths`, `scores`, `references`; wiring messages for `oneOf` | ⏳ |
| 3 | Servers adopt score references and `describe_score` (six subagents, one per server) | ⏳ |
| 4 | Review, relock, docs and status tables | ⏳ |

---

## 1. Goal and scope

Chaining tools today means copying the whole MusicXML score through the model: about 29k tokens
for a 24-bar chorale, each way ([evidence](ux-architecture-and-tool-improvements.md#2-evidence-the-musicxml-round-trip-problem)).
Wave 2 lets every tool take and return a **file path** instead.

| Item | What ships | Servers |
|---|---|---|
| **A1 (input)** | Every `musicxml` input gains a `musicxml_path` sibling; comparer's `reference_xml` / `target_xml` gain `reference_path` / `target_path`. Exactly one of each pair is required (`oneOf`). `.musicxml`, `.xml` and `.mxl` are accepted everywhere. | render, synth, abc, pitch, comparer |
| **A1 (read policy)** | Paths are confined to the allowed read roots: the output root, the client's MCP roots and `SHEET_MUSIC_INPUT_ROOTS` (E4). Symlinks are resolved, suffixes and size are checked, and errors never echo file contents. | core |
| **A1 (output)** | Score producers gain `return: "auto" \| "path" \| "inline"`. `auto` returns inline up to 8 KB and a path plus `score_summary` above it. | omr, abc, comparer |
| **C5** | `recognize_sheet` and `recognize_sheets` return a path plus summary for large scores by default. | omr |
| **C25** | `export_annotated_musicxml` writes both annotated scores and returns paths. | comparer |
| **C18** | `describe_score` in the core (E7), parsed with the standard library, exposed by every server that takes a score. | render, synth, abc, pitch, comparer |
| **Tidy-up** | The three copies of `confine_output_path` move into `core.paths`. `compare_musicxml_files` uses the shared read policy. | render, synth, omr, comparer |

### Out of scope

- Read confinement for **images and audio** (omr `image` / `input_path`, pitch `audio_path`).
  `core.paths` takes a suffix list, so they can adopt it in a later wave (decision W2-3).
- Removing the deprecated Wave 1 aliases, and consolidating comparer's tools (C24, Wave 5).
- MCP Apps; the Score Viewer spike stays independent.

---

## 2. Definition of done

| # | Criterion |
|---|---|
| DoD-1 | Every server's existing default `pytest` run passes. Tests change only where behaviour changes on purpose, and each change is listed in the PR: the `oneOf` schema, producer annotations, `return: "auto"` on large results, and `compare_musicxml_files` confinement. |
| DoD-2 | Inline calls behave exactly as before: same `content[0]` for the same inline input. |
| DoD-3 | The §7 acceptance criteria of the parent proposal pass as tests (see §4 below). |
| DoD-4 | `docs/conventions.md` describes Score References before any server implements them. |
| DoD-5 | `paths` and `scores` import neither `mcp` nor `music21`. `scores` parses with `defusedxml`, never echoes file contents in errors, and guards `.mxl` decompression size. |
| DoD-6 | The core is released as 0.2.0 before any server release that needs it; servers depend on `sheet-music-mcp-core>=0.2.0,<0.3.0`. |

---

## 3. Design

### 3.1 Core modules

```
sheet_music_mcp_core
├── paths       (no mcp)  read and write confinement, output files
├── scores      (no mcp)  read .musicxml/.xml/.mxl, describe_score, score_summary
└── references  (mcp)     schema helpers, client roots, load_score(), deliver_score(),
                          the describe_score tool
```

Each module has one job (SRP). Servers depend on the `references` functions, not on how roots
or files are resolved (DIP). New input kinds reuse `confine_read_path` with their own suffix list
instead of changing it (OCP).

**`paths`**

| Name | Behaviour |
|---|---|
| `SCORE_SUFFIXES` | `(".musicxml", ".xml", ".mxl")` |
| `max_score_bytes()` | `SHEET_MUSIC_MAX_SCORE_BYTES`, default 16 MiB |
| `output_root()` | `SHEET_MUSIC_OUTPUT_ROOT`, default the working directory, resolved |
| `input_roots()` | `SHEET_MUSIC_INPUT_ROOTS`, split on `os.pathsep`; blank entries ignored |
| `read_roots(client_roots=())` | Output root + client roots + input roots, resolved, de-duplicated, order kept |
| `confine_read_path(path, *, roots, suffixes, max_bytes, param)` | Resolves `~`, relative paths (against the output root) and symlinks, then checks in this order: inside a root → else `INVALID_PARAMETER` with a `hint` naming the roots and `SHEET_MUSIC_INPUT_ROOTS`; suffix → `INVALID_PARAMETER`; exists and is a file → `FILE_NOT_FOUND`; size → `FILE_TOO_LARGE`. The root check comes first, so a path outside the roots never reveals whether it exists. Raises `PathPolicyError` |
| `confine_output_path(path, suffixes)` | Moved unchanged from render, synth and omr: inside the output root, allowed suffix, never overwrites. Raises `PathPolicyError` |
| `new_output_path(stem, suffix, *, subdir="scores")` | `<output root>/scores/<stem>-<YYYYmmdd-HHMMSS-ffffff><suffix>`; the folder is created with mode 0700; never overwrites |
| `PathPolicyError` | Subclass of `ProcessingError` **and** `ValueError`, so existing `except ValueError` handlers keep working |

**`scores`**

| Name | Behaviour |
|---|---|
| `read_score_file(path, *, max_bytes)` | Returns the MusicXML text. `.mxl`: rootfile from `META-INF/container.xml`, otherwise the first `.musicxml`/`.xml` member outside `META-INF/`; the member's uncompressed size is capped at `max_bytes` (`FILE_TOO_LARGE`), so a zip bomb is rejected before extracting. Bad zip or undecodable text → `INVALID_INPUT` |
| `describe_score(text)` | `{title, composer, key, time, tempo_bpm, parts: [{id, name, abbreviation, clef, range: {low, high}}], measures, has_lyrics, duration_quarters, duration_seconds}` |
| `score_summary(text)` | The A1 subset: `{title, parts: [{id, name, range}], measures, key, time, tempo_bpm}` |
| `ScoreFormatError` | `ProcessingError` with code `INVALID_INPUT`. Messages give only the line and column of a parse error, never content |

`describe_score` details:

- Parses with `defusedxml.ElementTree`, so entity-expansion attacks are rejected (`INVALID_INPUT`).
- Accepts `score-partwise` and `score-timewise` (timewise is regrouped per part); any other root is
  `INVALID_INPUT` without naming the root.
- `title`: `work/work-title`, else `movement-title`, else the first `credit-words`; `null` if none.
  `composer`: `identification/creator[@type="composer"]`.
- Part `id` is the `score-part@id` (`P1` …), the same ID the Wave 1 part resolver uses.
- `key` from the first `<key>`: `fifths` and `mode` → `"D major"`, `"B minor"`; `null` if absent.
  `time`: `"3/4"` from the first `<time>`; `null` if absent.
- `tempo_bpm`: first `<sound tempo>`, else the first `<metronome>` per-minute (converted to
  quarter notes per minute when the beat unit is given); `null` if absent.
- `clef`: the first clef of the part, as `treble`, `treble_8vb`, `bass`, `alto`, `tenor`,
  `percussion` or `"<sign><line>"` otherwise.
- `range`: lowest and highest sounding pitch in scientific notation (`"D3"`, `"F#4"`, `"Bb3"`),
  ignoring rests and unpitched notes; `null` for a part without pitches.
- `measures`: number of `<measure>` elements in the first part. `has_lyrics`: any `<lyric>`.
- `duration_quarters`: the first part's length, summing each measure's furthest position from
  note and `forward` durations (chord notes don't advance, `backup` steps back) divided by
  `divisions`. `duration_seconds` = `duration_quarters × 60 / tempo_bpm`, or `null` without a
  tempo.

**`references`**

| Name | Behaviour |
|---|---|
| `score_input_properties(inline, path, *, what)` | The JSON Schema `properties` for the pair, e.g. `{"musicxml": {...}, "musicxml_path": {...}}` |
| `exactly_one(inline, path)` | `{"oneOf": [{"required": [inline]}, {"required": [path]}]}`; a tool with two pairs combines them with `allOf` |
| `RETURN_PROPERTY` | `{"return": {"type": "string", "enum": ["auto", "path", "inline"], "default": "auto", ...}}` |
| `async client_roots(ctx)` | The client's `file://` roots as paths. `[]` when `ctx` is `None`, the client does not declare the roots capability, the request fails or it takes longer than 2 s |
| `async load_score(arguments, ctx, *, inline="musicxml", path="musicxml_path")` | Returns MusicXML text: the inline string as is, or the confined, size-checked file read with `scores.read_score_file`. Raises `ProcessingError` |
| `deliver_score(payload, *, field, musicxml, mode, stem)` | `inline` (or `auto` at most `SHEET_MUSIC_INLINE_MAX_BYTES`, default 8192 UTF-8 bytes): `payload` unchanged as `content[0]`. Otherwise writes `musicxml` to `new_output_path(stem, ".musicxml")`, replaces `payload[field]` with `payload[field + "_path"]` and adds `score_summary`, then appends a `file_link`. Returns the content list |
| `DESCRIBE_SCORE_TOOL`, `async describe_score_tool(arguments, ctx)` | The shared `describe_score` tool (`READ_ONLY`, title "Describe score") taking `musicxml` or `musicxml_path` |

`wiring._describe` learns the `oneOf` "both given" case: *"give only one of these parameters:
'musicxml', 'musicxml_path'"*, without echoing the arguments. Nested `allOf` errors report their
innermost `oneOf`.

### 3.2 Per-server changes

| Server | Tools gaining path input | Producers (`return`) | `describe_score` | Other |
|---|---|---|---|---|
| omr | – | `recognize_sheet`, `recognize_sheets` (field `musicxml`) | – (takes no score) | `recognize_sheet_to_file` adds `score_summary`; `confine_output_path` from core; annotations `READ_ONLY_DOWNLOADS` → `WRITES_FILE_DOWNLOADS` for the two producers |
| render | `render_to_pdf`, `render_to_image` | – | ✅ | `confine_output_path` from core |
| synth | `get_parts`, `synthesize` | – | ✅ | `confine_output_path` from core |
| abc | `musicxml_to_abc` | `abc_to_musicxml` (field `musicxml`) | ✅ | annotation `READ_ONLY` → `WRITES_FILE` for `abc_to_musicxml` |
| pitch | `analyze_recording`, `load_score` | – | ✅ | `oneOf` combines with the existing `part` / `part_id` `anyOf` |
| comparer | `compare_musicxml`, `quick_similarity`, `list_changes`, `generate_comparison_report`, `export_annotated_musicxml` (`reference_path`, `target_path`) | `export_annotated_musicxml` (both fields; `auto` writes both when either exceeds the limit) | ✅ | `compare_musicxml_files` reads through `confine_read_path`; annotation `READ_ONLY` → `WRITES_FILE` for the export |

Every server that reads paths calls `make_handlers(..., pass_context=True)` so `load_score` can
ask the client for its roots. Server `instructions` gain one line: prefer `musicxml_path` and pass
the paths that producers return.

---

## 4. Tests first

Core (`sheet-music-mcp-core/tests/`):

- `test_paths.py`: `/etc/passwd`, `../x.musicxml` and a symlink pointing out → `INVALID_PARAMETER`
  whose text contains no file content; a missing file outside the roots gives `INVALID_PARAMETER`,
  not `FILE_NOT_FOUND`; a wrong suffix; `FILE_TOO_LARGE`; `SHEET_MUSIC_INPUT_ROOTS` and client roots
  extend the allowed set; `confine_output_path` keeps the behaviour of the three server copies.
- `test_scores.py`: `.mxl` with and without `container.xml` equals the plain text; a zip bomb
  (uncompressed member over the limit) → `FILE_TOO_LARGE`; malformed XML → line and column only;
  billion-laughs → `INVALID_INPUT`; `describe_score` on an SATB fixture, an unnamed two-part fixture,
  a timewise fixture and a score without tempo.
- `test_references.py`: `load_score` with an inline score, a path, both and neither; client roots
  are used when declared and ignored on error or timeout; `deliver_score` inline at the limit and
  path above it (no `<score-partwise` in `content[0]`); the `describe_score` tool through
  `mcp.Client`.
- `test_wiring.py`: `oneOf` with both or neither parameter gives a concise message.
- `test_import_isolation.py`: `paths` and `scores` import neither `mcp` nor `music21`.

Servers (each server's `tests/test_score_references.py`):

- A path call returns the same `content[0]` as the inline call (synth: same duration and parts).
- Both or neither of the pair → `INVALID_PARAMETER`; a path outside the roots → `INVALID_PARAMETER`
  with no file content; an `.mxl` path works.
- `describe_score` is listed and works (five servers).
- Producers: `return: "auto"` above the limit gives `musicxml_path` and `score_summary` and no
  `<score-partwise` in `content[0]`; `inline` is unchanged; `path` always writes.

---

## 5. Steps and subagents

1. **Me:** this plan and the conventions contract.
2. **One subagent:** core 0.2.0, test-first, against §3.1. I review the diff before step 3.
3. **Six subagents in parallel**, one per server directory (disjoint files): tests first, then
   adopt `references`, bump the core constraint to `>=0.2.0,<0.3.0` and relock with
   `uvx --from 'uv==0.13.6' uv lock`. Each updates its server's docs.
4. **Me:** review each diff, run every suite, update `CLAUDE.md`, `README.md`, the copilot
   instructions and this plan, then commit per step.

---

## 6. Release sequencing

The servers' Wave 1 minor bumps ([wave 1 §6](ux-wave1-plan.md#6-release-sequencing)) have not
been released, so Wave 1 and Wave 2 ship in the same server minors.

1. Publish `sheet-music-mcp-core` 0.2.0 first (tag `sheet-music-mcp-core/v0.2.0`, after the PyPI
   pending publisher is added). 0.1.0 was never published and can be skipped.
2. Then bump and tag the servers as planned in Wave 1 §6. The changelogs list the behaviour
   changes in DoD-1.

---

## 7. Decisions

Agreed with the project owner on 2026-10-27.

| # | Question | Decision |
|---|---|---|
| W2-1 | Default `return` mode for producers | **`auto` now.** Small scores stay inline; large ones become a path plus `score_summary`. Clients that need the text pass `return: "inline"`. |
| W2-2 | `compare_musicxml_files` reading any path | **Confine now** to the shared read roots. Users add folders with `SHEET_MUSIC_INPUT_ROOTS`. |
| W2-3 | Confine image and audio inputs too | **Later wave.** Wave 2 covers scores only. |
| W2-4 | Where producers write without an `output_path` | **`<output root>/scores/`**, so every server can read the files back by default. |
| W2-5 | Annotations of producers that may now write | `WRITES_FILE` / `WRITES_FILE_DOWNLOADS`. They write in `auto` mode, so `readOnlyHint` would be wrong (Wave 1 B3 rule). |
| W2-6 | Core version | **0.2.0.** New modules and a new dependency (`defusedxml`); 0.1.0 is skipped. |
