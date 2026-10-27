# UX Wave 1 plan: contract foundation and core library

**Status:** Approved 2026-10-27 with the decisions in [§7](#7-decisions). Implementation in progress.
**Date:** 2026-10-27
**Parent:** [ux-architecture-and-tool-improvements.md](ux-architecture-and-tool-improvements.md),
roadmap wave 1, decisions E1–E8.
**Servers:** all six, plus the new `sheet-music-mcp-core` package.

## Progress

| Step | Content | Status |
|---|---|---|
| 1 | Conventions contract | ✅ `cf32796` |
| 2 | `sheet-music-mcp-core` library, plus review fixes ([core-library-review.md](core-library-review.md)) | ✅ `46921a0`, `c8e730d` |
| 3 | Servers adopt core wiring and errors | ✅ `ce38fb3` |
| 4 | Titles, annotation presets, server instructions | ✅ `8c4afec` |
| 5 | Part selector, `part`/`parts` renames, `hint`/`choices` in errors | ✅ this step |
| 6 | Result content (inline PNG, file links) | ⏳ |
| 7 | Pitch idle timeout and `list_sessions` | ⏳ |
| 8 | OMR resolution pre-check | ⏳ |

---

## 1. Goal and scope

Wave 1 delivers the small, additive fixes that reduce retries, permission prompts and privacy
risk. It also bootstraps the shared core library (decision E1) that later waves build on.

| Item | What ships | Servers |
|---|---|---|
| **Contract** | `docs/conventions.md` gains part selection, error fields, annotations, result content, server instructions and core library usage. | docs |
| **A2 (bootstrap)** | `sheet-music-mcp-core` 0.1.0 with `errors`, `parts`, `wiring`, `annotations` and `content` modules. | new package |
| **B1** | Part selector that accepts an ID, a name or a voice role. Fixes unnamed parts that cannot be selected and same-named parts that cannot be told apart ([review F1](core-library-review.md#f1)). Parameters renamed to `part` / `parts`, with the old names kept as deprecated aliases for one minor release (W1). | synth, abc, pitch, comparer |
| **B3** | `annotations` and `title` on all 34 tools. | all |
| **B4** | `ImageContent` for PNG renders and `ResourceLink` for written files. | render, synth, omr |
| **B5** | Optional `hint` and `choices` in error responses. | all |
| **A5** | Server `instructions` at initialize. | all |
| **C3** | Fast fail for clearly too-small images before Audiveris runs. | omr |
| **C23** | Pitch session idle timeout, plus `list_sessions`. | pitch |

### Out of scope for Wave 1

- Score references (A1), `describe_score` (C18) and `core.paths` and `core.scores` (Wave 2).
- MCP Apps. The render-mcp Score Viewer spike runs independently. It will consume
  `core.wiring` and `core.content` once they exist, and its `ui` module can move into the core in
  Wave 2.

---

## 2. Definition of done

| # | Criterion |
|---|---|
| DoD-1 | Every server's existing default `pytest` run passes. Tests change only where a response intentionally gains a field (`hint`, `choices`, an extra content block), and each such change is listed in the PR. |
| DoD-2 | `content[0]` of every successful tool result is unchanged. New blocks are only appended. |
| DoD-3 | The core package has its own unit tests in the CI matrix. Importing `sheet_music_mcp_core.errors`, `.parts` and `.annotations` does not import `mcp`, so engines may use them. |
| DoD-4 | `docs/conventions.md` describes every new rule before any server implements it. |
| DoD-5 | The part-ID regressions in [review F1](core-library-review.md#f1) pass: the MusicXML ID `P1` works, unnamed parts get stable IDs, and same-named parts can be told apart. They fail on `main` today. |
| DoD-6 | A pitch session with no activity for `PITCH_SESSION_IDLE_MINUTES` has its stream closed. |
| DoD-7 | The core package is published to PyPI before any server release that depends on it ([§6](#6-release-sequencing)). |
| DoD-8 | Docs are updated per the repository policy: each server's `requirements.md` and `architecture.md`, local `HANDOVER.md` and `PLAN.md`, the root `CLAUDE.md` hard rules and status, and `.github/copilot-instructions.md`. |

---

## 3. Core library design (SOLID)

```
sheet-music-mcp-core/                       # new top-level directory; not an MCP server
  pyproject.toml                            # deps: none at runtime except `mcp` (wiring/content only)
  src/sheet_music_mcp_core/
    errors.py        # ProcessingError(message, error_code, hint=None, choices=None)
                     # error_payload(...) -> dict -- the {error, error_code, hint?, choices?} envelope (no mcp import)
    parts.py         # PartInfo, resolve_parts(), resolve_part(), PartSelectionError
    params.py        # aliased(arguments, name, deprecated) -- deprecated parameter names (W1)
    annotations.py   # READ_ONLY, WRITES_FILE, SESSION_STATE, DOWNLOADS presets -> ToolAnnotations kwargs
    content.py       # error_content(...) -> [TextContent]; png_block(path), file_link(path, mime)
    wiring.py        # make_handlers(list_tools, call_tool) -> (on_list_tools, on_call_tool)
  tests/
```

| Principle | How it applies |
|---|---|
| **S** | One concern per module. `parts` knows nothing about music21. Each server converts its parsed parts into `PartInfo(id, name)`. |
| **O** | Servers add behaviour by passing data (annotation presets, part lists), not by editing the core. |
| **L** | `PartSelectionError` is a `ProcessingError`, so every existing `except ProcessingError` path keeps working unchanged. |
| **I** | `errors`, `parts`, `params` and `annotations` have no `mcp` import, so engines can use them without breaking the rule "`engine.py` must not import from `mcp`". Only `wiring` and `content` import `mcp`. |
| **D** | `wiring.make_handlers` receives the server's `list_tools` and `call_tool` callables. The core never imports a server. |

**Per-server `ProcessingError`.** Each engine keeps its name with
`from sheet_music_mcp_core.errors import ProcessingError`, so existing raises and tests are
untouched, and the class gains `hint` and `choices`.

**Development and packaging.**

- Servers declare `sheet-music-mcp-core>=0.1,<0.2` (0.x, so the pin is minor-level).
- For development, they use `[tool.uv.sources] sheet-music-mcp-core = { path = "../sheet-music-mcp-core", editable = true }`.
- `uv build` keeps the PyPI requirement and drops the path source, so published wheels resolve the
  core from PyPI.
- Each server still has its own `.venv` and `uv.lock` (hard rule).

### 3.1 Part selector specification (B1)

```python
@dataclass(frozen=True)
class PartInfo:
    id: str
    name: str

def resolve_parts(requested: Sequence[str], available: Sequence[PartInfo]) -> list[str]: ...
def resolve_part(requested: str, available: Sequence[PartInfo]) -> str: ...  # exactly one match or error
```

Each requested string is matched in tiers, and the first tier that matches wins:

1. **Exact ID**, case-sensitive (`P2`).
2. **Name or ID**, after normalising (casefold, strip punctuation, collapse spaces, Roman
   `I/II/III/IV` to `1/2/3/4`). `"alto ii"` matches `Alto 2`.
3. **Voice role** using an alias table. The role matches every part whose normalised name is the
   role, optionally followed by a divisi number.

| Role | Aliases (normalised) |
|---|---|
| soprano | `s`, `sop`, `soprano`, `soprani`, `sopran`, `cantus`, `canto`, `tr`, `treble`, `trebles` |
| alto | `a`, `alt`, `alto`, `alti`, `contralto`, `altus` |
| countertenor | `ct`, `countertenor`, `counter tenor`, `countertenors`, `contratenor`, `contra tenor` |
| tenor | `t`, `ten`, `tenor`, `tenori` |
| bass | `b`, `bas`, `bass`, `bassi`, `basso`, `bassus` |
| mezzo-soprano | `ms`, `mez`, `mezzo`, `mezzo soprano`, `mezzosoprano` |
| baritone | `bar`, `bari`, `bariton`, `baritone`, `baritono` |

Latin and Italian forms (W2): `cantus` and `canto` map to soprano, `altus` to alto, `bassus` and
`basso` to bass. Treble is a soprano alias (R5). Mezzo-soprano, baritone (W2) and countertenor
(R5) are roles of their own: `"Alto"` never selects a mezzo or countertenor part, and `"Bass"`
never selects a baritone part.

Divisi: `A1`, `Alto 1` and `Alt I` match only `Alto 1`. `Sopran` and `Alt` cover the German and
Estonian part names common in choir editions.

Results and errors:

- `resolve_parts` returns the IDs in request order, without duplicates. `"Alto"` on a score with
  `Alto 1` and `Alto 2` returns both, which is the natural "play the altos".
- `resolve_part` (single-part tools: pitch, ABC) raises `PartSelectionError` when a request
  matches several parts.
- No match raises `INVALID_PARAMETER` with `choices: ["Soprano (P1)", "Alto (P2)", …]`. An
  ambiguous match does the same, with the matching parts as `choices`. The `hint` is "Pass one of
  the listed part names or IDs".

**Part IDs** ([review F1](core-library-review.md#f1)): every adopting engine builds its part list
with `music21_part_infos(score.parts)` and selects parts by position against it, never by music21's
`part.id`. `get_parts` reports the same IDs.

**Adoption per server**

| Server | New parameter | Deprecated alias (W1) | Call |
|---|---|---|---|
| synth | `synthesize.parts` | `part_ids` | `resolve_parts` |
| musicxml-abc | `musicxml_to_abc.part` | `part_id` | `resolve_part` |
| pitch | `analyze_recording.part`, `load_score.part` | `part_id` | `resolve_part` |
| comparer | `list_changes.part` (name unchanged), `options.parts` | `options.part_filter` | `resolve_parts` against the **reference** score's parts. The resolved IDs map to names for the existing name-based target matching. |

Tool descriptions are updated to say "part ID, name or voice (e.g. 'P1', 'Soprano', 'S')".

**Alias rules** (`core.params.aliased`):

- The schema lists both names. The old one's description starts with "(Deprecated: use `part`)".
  Where a part is required, the schema uses
  `anyOf: [{"required": ["part"]}, {"required": ["part_id"]}]`.
- Passing only the old name works and logs one deprecation warning per process.
- Passing both with equal values is accepted. Passing both with different values returns
  `INVALID_PARAMETER`.
- The aliases are removed in each server's next minor release after Wave 1, consistent with E3.

### 3.2 Annotations and titles (B3)

The presets in `core.annotations`:

| Preset | `read_only_hint` | `destructive_hint` | `idempotent_hint` | `open_world_hint` |
|---|---|---|---|---|
| `READ_ONLY` | true | – | – | false |
| `READ_ONLY_DOWNLOADS` | true | – | – | true (first-use model or engine download) |
| `WRITES_FILE` | false | false (never overwrites) | false | false |
| `WRITES_FILE_DOWNLOADS` | false | false | false | true |
| `SESSION_STATE` | false | false | false | false |

| Server | Tool | Preset | Title |
|---|---|---|---|
| omr | `recognize_sheet` | READ_ONLY_DOWNLOADS | Recognize sheet music |
| omr | `recognize_sheets` | READ_ONLY_DOWNLOADS | Recognize multi-page sheet music |
| omr | `recognize_sheet_to_file` | WRITES_FILE_DOWNLOADS | Recognize sheet music to file |
| omr | `list_capabilities`, `list_supported_formats`, `health_check` | READ_ONLY | OMR capabilities / OMR formats (deprecated) / OMR health check |
| render | `render_to_pdf` | WRITES_FILE | Render score to PDF |
| render | `render_to_image` | WRITES_FILE | Render score page to image |
| render | `list_capabilities`, `health_check` | READ_ONLY | Render capabilities / Render health check |
| synth | `get_parts` | READ_ONLY | List voice parts |
| synth | `synthesize` | WRITES_FILE | Play voice parts |
| synth | `list_capabilities`, `health_check` | READ_ONLY | Synth capabilities / Synth health check |
| abc | `musicxml_to_abc`, `abc_to_musicxml`, `validate_abc` | READ_ONLY | MusicXML to ABC / ABC to MusicXML / Validate ABC |
| abc | `list_capabilities`, `health_check` | READ_ONLY | ABC capabilities / ABC health check |
| pitch | `analyze_recording` | READ_ONLY | Analyze a recording |
| pitch | `load_score` | SESSION_STATE | Load score for practice |
| pitch | `start_monitoring` | SESSION_STATE | Start listening (microphone) |
| pitch | `get_current_position`, `list_sessions` | READ_ONLY | Current singing position / Practice sessions |
| pitch | `stop_monitoring` | SESSION_STATE | Stop listening |
| pitch | `list_capabilities`, `health_check` | READ_ONLY | Pitch capabilities / Pitch health check |
| comparer | all 8 tools | READ_ONLY | Compare scores, Compare score files, Score similarity, List score changes, Comparison report, Export color-annotated diff, Comparer capabilities, Comparer health check |

The titles follow the repository's American spelling. The source of truth is each server's
`tests/test_tool_metadata.py`. `list_sessions` gets its row in step 7.

`start_monitoring` is deliberately **not** read-only, so hosts that auto-approve read-only tools
still ask before the microphone opens.

### 3.3 Result content (B4)

- `render_to_image` with `format="png"` appends `ImageContent` (base64 PNG) when the file is at
  most 1 MB. Larger files get only the link. SVG gets no image block, because many hosts do not
  display SVG.
- Every tool that writes a file appends a `ResourceLink`:

  | Tool | `file://` link MIME type |
  |---|---|
  | `render_to_pdf` | `application/pdf` |
  | `render_to_image` | `image/png` or `image/svg+xml` |
  | `synthesize` | `audio/wav` |
  | `recognize_sheet_to_file` | `application/vnd.recordare.musicxml+xml` |

- Order: the existing JSON text stays `content[0]`. Extra blocks are appended (DoD-2).

### 3.4 Server instructions (A5)

Each `Server(name, instructions=...)` gets 3–6 lines. Draft:

| Server | Instructions (draft) |
|---|---|
| omr | Converts photos or scans of printed music to MusicXML. For choir (SATB, multi-staff) scores use `engine="audiveris"` with 300+ DPI images; oemer merges staves into one part. First use downloads models (oemer ~100 MB, Audiveris ~80 MB). |
| render | Renders MusicXML to PDF, PNG or SVG. PNG results are shown inline when the client supports images. |
| synth | Plays chosen voice parts of a MusicXML score as WAV. Parts may be given as ID, name or voice letter (S/A/T/B). `tempo_factor` 0.75 = 75 % speed. Call `get_parts` if unsure which parts exist. |
| abc | Converts MusicXML to compact ABC text for reading or editing, and back. The round trip keeps notes but drops dynamics and complex articulations. |
| pitch | Follows a singer from the microphone. Flow: `load_score`, `start_monitoring`, `get_current_position` (repeat), `stop_monitoring`. Always stop when done; idle sessions close after `PITCH_SESSION_IDLE_MINUTES` (default 10). |
| comparer | Music-aware diff of two MusicXML scores. `quick_similarity` for a score, `list_changes` for targeted questions, `generate_comparison_report` for a readable summary. |

### 3.5 Pitch idle timeout (C23)

- Add a **`SessionRegistry`** class in `engine.py` (single responsibility) that replaces the
  module-level `_sessions` dict and lock. It has an injected `clock` (default `time.monotonic`),
  plus `add`, `get`, `remove`, `list`, `touch` and `reap(now)`.
- Activity means `start_monitoring` or `get_current_position` on the session. Sessions that are
  loaded but never started expire too, which frees memory.
- `reap(now)` stops every session idle longer than the timeout and closes its stream. It keeps the
  summary in an `_expired` map for 1 hour.
  - `stop_monitoring` on an expired session returns that summary with `"timed_out": true`.
  - `get_current_position` on an expired session returns `SESSION_NOT_FOUND` with the hint "timed
    out after N minutes idle; call stop_monitoring for the summary".
- A **`Reaper`** daemon thread calls `registry.reap(clock())` every 30 s. It starts on the first
  `load_score`, and both its sleep and clock are injected. Unit tests call `reap()` directly with a
  fake clock, so there are no timing-dependent tests.
- `PITCH_SESSION_IDLE_MINUTES`: an integer, default 10. `0` disables the timeout. An invalid value
  logs a warning and falls back to 10.
- New tool `list_sessions` returns `[{session_id, part_name, state: "loaded" | "monitoring", idle_seconds}]`.
- The rule against I/O and locking in the audio callback is unaffected: the registry lock is never
  taken in the callback.

### 3.6 OMR resolution pre-check (C3)

Image DPI metadata is unreliable (phone JPEGs usually say 72 DPI), so the check uses pixel size
only and applies only to `engine="audiveris"`:

| Longest side | Result |
|---|---|
| < 1500 px | Fail at once with `INVALID_INPUT`, hint "Audiveris needs about 300 DPI: rescan or photograph closer (≥ 2500 px on the long side)". This takes milliseconds, where today Audiveris runs first and then fails. |
| 1500–2499 px | Run, and add a `warnings[]` entry: "low resolution; recognition may fail". |
| ≥ 2500 px | Run as today. |

`check_resolution(path) -> ResolutionCheck(long_side_px, verdict, message)` is a pure function in
`utils.py`. The thresholds are named constants. Test images are generated with Pillow inside the
tests, so no binary fixtures are added.

---

## 4. Work breakdown (one PR each, test first)

Each step starts with the listed tests failing, then the minimum code to pass, then a refactor.

| PR | Content | Tests first (red) | Depends on | Est. |
|---|---|---|---|---|
| **1. Contract** | `docs/conventions.md`: error fields `hint` and `choices`, part selector semantics and alias table, annotation presets and the per-tool table, result content rules, server instructions, core library usage and the dev path source. The root `CLAUDE.md` hard rules gain "use `sheet-music-mcp-core` for errors, parts and wiring". | Documentation only, reviewed against §3. | none | 0.5 d |
| **2. Core package** | `sheet-music-mcp-core/` with the modules in §3. Add it to the `tests.yml` matrix. `publish.yml` accepts the `sheet-music-mcp-core/v*` tag and skips the `server.json` check and the MCP Registry steps for it. | `test_errors.py`: envelope with and without `hint`/`choices`; JSON shape matches the conventions. `test_parts.py`: every tier, the alias table, divisi, Roman numerals, ambiguous single match, multi match, no match listing choices, order and de-duplication. `test_params.py`: new name only, old name only (one warning), both equal, both different gives `INVALID_PARAMETER`, neither. `test_annotations.py`: preset values. `test_content.py`: PNG to `ImageContent`, size cap, `ResourceLink` URI and MIME type. `test_wiring.py`: schema validation error, exception becomes `isError`, unknown tool. `test_import_isolation.py`: importing `errors`, `parts`, `params` and `annotations` leaves `mcp` absent from `sys.modules`. | 1 | 1.5 d |
| **3. Adopt wiring** | Each server replaces its copy of `_on_list_tools` and `_on_call_tool` with `core.wiring.make_handlers` and imports `ProcessingError` from the core. This is a pure refactor. | No new tests. The existing `test_mcp_protocol.py` in all six servers must stay green. That is the safety net. | 2 | 0.5 d |
| **4. Annotations, titles, instructions** | B3 tables and A5 text in all six `list_tools` and `Server(...)` calls. | Per server, `test_server.py`: every tool has a `title`. Read-only tools match the table exactly, and no file-writing or session tool is read-only. `start_monitoring` is not read-only. `test_mcp_protocol.py`: `client.instructions` contains the key phrase (for example "audiveris" for omr, "stop_monitoring" for pitch). | 3 | 1 d |
| **5. Part selector and errors** | B1 adoption (§3.1) in synth, abc, pitch and comparer, including the `part` / `parts` renames with deprecated aliases (W1). B5 `hint` and `choices` on part errors, plus the C3/C23 hints when those land. Tool descriptions updated. | **Regression first** ([review F1](core-library-review.md#f1)): `load_score(part="P1")` and `musicxml_to_abc(part="soprano")` succeed on a named SATB fixture. An unnamed fixture gives the same IDs on every call. Two `Tenor` parts can be selected one at a time as `P3` and `P4`. `synthesize(part_ids=["S","A"])` includes P1 and P2. `list_changes(part="alto")` matches `Alto`. An unknown part returns `choices`. An ambiguous single part returns the matching `choices`. Old parameter names still work, and conflicting old and new values are rejected. | 3 | 1.5 d |
| **6. Result content** | B4 in render, synth and omr (§3.3). | `render_to_image` PNG: `content[0]` unchanged, `content[1]` is `ImageContent` with `image/png`, `content[2]` is a `ResourceLink` with a `file://` URI. Over 1 MB gives no image block. SVG gives no image block. `render_to_pdf`, `synthesize` and `recognize_sheet_to_file` each have a `ResourceLink` with the right MIME type. | 3 | 0.5 d |
| **7. Pitch idle timeout** | C23 (§3.5), including `list_sessions`. | `SessionRegistry` with a fake clock: no reap before the timeout; reap after it closes the stream (fake stream) and stores the summary; `stop_monitoring` after a reap returns the summary with `timed_out`; `get_current_position` after a reap gives `SESSION_NOT_FOUND` and the hint; activity resets the idle time; `0` disables. Env parsing: valid, invalid falls back. `Reaper` with an injected sleep calls `reap` once per tick and stops on its stop event. `list_sessions` shape and states. | 3 | 1 d |
| **8. OMR pre-check** | C3 (§3.6). | `check_resolution` at 1499, 1500, 2499 and 2500 px (generated images). `recognize_sheet(engine="audiveris")` on a 1000 px image returns `INVALID_INPUT` with a `hint` **without calling** `_run_audiveris` (mocked and asserted not called). oemer is unaffected by the check. | 3 | 0.5 d |

PRs 4–8 are independent after PR 3 and can be reviewed in parallel. **Total: about 7 working
days.**

---

## 5. Risks

| Risk | Mitigation |
|---|---|
| Servers on `main` depend on an unpublished core. | Development uses the path source. Releases follow [§6](#6-release-sequencing). |
| An older MCP client mishandles `ResourceLink` or `ImageContent`. | Both are appended after the unchanged `content[0]`. PR 6 starts by checking whether the SDK exposes the negotiated protocol version. If it does, links are sent only for protocol 2025-06-18 or later. |
| The alias table surprises someone, for example a part named "B" that is not a bass. | Tier order: an exact ID and name always beat the role alias. Ambiguity returns `choices` rather than guessing. |
| Annotation hints are treated as security. | Hosts must not rely on them, and nor do we. The path confinement and no-overwrite rules stay in force. |
| The pitch reaper thread adds concurrency. | All registry state sits behind one lock that the audio callback never takes. The reaper only calls `stop()`, which already exists. Unit tests drive `reap()` without threads. |
| A bad core release breaks all servers at once. | The minor-level pin (`<0.2`), the core's own CI, and each server's CI against the core path source before release. |

---

## 6. Release sequencing

1. **Owner action (one-time):** add a PyPI *pending publisher* for `sheet-music-mcp-core`
   (same repository, workflow `publish.yml`, environment `pypi`), as was done for the six servers.
2. Merge PRs 1–2, then tag `sheet-music-mcp-core/v0.1.0`. This publishes to PyPI only, not to the
   MCP Registry.
3. Merge PRs 3–8.
4. Bump each server's minor version: omr 0.3.0, render 0.3.0, synth 0.3.0, musicxml-abc 0.3.0,
   pitch 0.4.0, comparer 0.3.0. Update `server.json` and the changelogs (new optional behaviour,
   no breaking changes), then tag one server per push as today.

---

## 7. Decisions

Agreed with the project owner on 2026-10-27. The sections above already reflect them.

| # | Item | Decision |
|---|---|---|
| W1 | Parameter names | Rename **in Wave 1**: `part` for one part and `parts` for several. The old names (`part_id`, `part_ids`, `options.part_filter`) are deprecated aliases for **one minor release**. |
| W2 | Voice names | Add **Latin and Italian forms** (cantus, canto, altus, bassus, basso) and **baritone and mezzo-soprano as their own roles**, on top of the English, German and Estonian forms. |
| W3 | Core package | `sheet-music-mcp-core/` at the repo root. PyPI name `sheet-music-mcp-core`, import `sheet_music_mcp_core`. |
| W4 | Annotation table | Approved as written (§3.2). |
| W5 | Pitch idle timeout | 10 minutes by default, configurable. |
| W6 | OMR thresholds | Reject below 1,500 px and warn below 2,500 px on the long side. |
| W7 | Order | **Wave 1 first.** The MCP Apps spike follows and reuses `core.wiring`. |
| W8 | Release versions | As in §6. No objection was raised, so the default stands. |
