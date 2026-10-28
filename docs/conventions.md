# MCP Server Conventions

Shared standards for all MCP servers in this project. Every server must follow these conventions
so they compose cleanly in Phase 2 and are consistent for contributors.

---

## Directory Structure

Each MCP server lives in its own top-level directory and is independently deployable.

```
<name>-mcp/
├── pyproject.toml              # Package config and dependencies
├── README.md                   # Installation, usage, tool reference
├── .python-version             # Pins Python version (3.11)
├── src/
│   └── <name>_mcp/
│       ├── __init__.py
│       ├── server.py           # MCP server entry point, tool registration
│       ├── engine.py           # Core business logic (no MCP dependency)
│       └── utils.py            # Validation, format helpers, shared utilities
├── tests/
│   ├── __init__.py
│   ├── test_server.py          # Tool schema and MCP protocol tests
│   ├── test_engine.py          # Unit tests for engine.py (mocked I/O)
│   ├── test_utils.py           # Unit tests for utils.py
│   └── fixtures/               # Static test data (images, XML files, audio)
│       └── README.md           # Documents what fixtures are available and why
├── test_samples/               # Larger real-world samples (not committed if >10MB)
├── docs/
│   ├── HANDOVER.md             # Status, remaining work, definition of done
│   ├── PLAN.md                 # Architecture decisions and rationale
│   ├── requirements.md         # Functional and non-functional requirements
│   └── architecture.md         # Component diagram and data-flow
└── examples/
    └── claude_desktop_config.json  # Ready-to-use Claude Desktop config snippet
```

### Naming

- Directory: `<name>-mcp/` (kebab-case)
- Python package: `<name>_mcp` (snake_case)
- Entry point command: `<name>-mcp` (matches directory name)

---

## pyproject.toml Template

```toml
[project]
name = "<name>-mcp"
version = "0.1.0"
description = "<One sentence description>"
requires-python = ">=3.11"
dependencies = [
    "jsonschema>=4.20.0",
    "mcp>=2.2.0,<3.0.0",
    # add server-specific dependencies here
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
]

[project.scripts]
<name>-mcp = "<name>_mcp.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

---

## Required Tool: `list_capabilities`

Every MCP server must expose a `list_capabilities` tool. This is the discovery contract between
servers and the orchestration layer (Phase 2 web app).

**Returns:**
```json
{
  "server": "<name>-mcp",
  "version": "0.1.0",
  "input_formats": ["<format>", ...],
  "output_formats": ["<format>", ...],
  "tools": ["tool_name_1", "tool_name_2", "list_capabilities"],
  "backend": "<library or engine name>",
  "backend_version": "<version string>"
}
```

---

## Health Reports

Every `health_check` tool returns the core's standard report as `structuredContent`, for the shared
Setup Doctor app ([proposal §5.7](research/mcp-apps-ux-proposal.md#57-all-servers-setup-doctor)).
Its text `content` stays as it is.

```json
{
  "status": "ready | degraded | not_ready",
  "checks": [{"name": "Soundfont", "status": "ok | warn | fail", "version": "…", "hint": "…", "fix_snippet": "…", "doc_url": "…"}]
}
```

Wiring: build `[HealthCheck(...)]` with MCP-free code (engine or presenter), return
`health_report(checks)`, declare `output_schema=HEALTH_OUTPUT_SCHEMA`, register
`setup_doctor_resource("<uri name>")` in the server's `UiRegistry` and link the tool with
`meta=ui_registry.meta_for(SETUP_DOCTOR)`. Unset fields are omitted, never `null`.

Mapping rules:

- **One check per thing a user installs or configures**: a package, a system library, a file or
  environment variable, a smoke test. `name` is what the user recognises, not an internal key.
- **`status`**: `fail` when the main tools cannot work without it; `warn` when an optional feature is
  off or the first use will be slow but the main tools work; `ok` when it works, or is optional and
  in its expected default state.
- **`version`**: the dependency's version when known; sentinels ("unknown", "unavailable") become unset.
- **`hint`**: one sentence for `warn`/`fail`: what is wrong and what stops working, with the old
  error text. On `ok` only when the user must know something (a download on first use).
- **`fix_snippet`**: only text to paste verbatim, a shell command or a client-config fragment.
- **`doc_url`**: on `warn`/`fail`, `https://github.com/raulkivi/sheet-music-mcp/blob/main/<dir>/TROUBLESHOOTING.md`.
- **Overall status** is derived, never set: any `fail` is `not_ready`, else any `warn` is
  `degraded`, else `ready`.

Per server (source → checks, in this order; "omit" means the row is left out):

| Server (URI name) | Source field | Check `name` | `ok` when | otherwise | `hint` (not ok) | `fix_snippet` |
|---|---|---|---|---|---|---|
| omr (`omr`) | `omr_engine.health_check()["checks"]["oemer"]` | `oemer` | `status == "ok"`; `version` | `fail` | `oemer is not installed: {error}` | `uv sync` |
| | `…["model_cache"]` | `oemer model cache` | `status == "ok"` | `warn` | `note` | – |
| | `…["audiveris"]` | `Audiveris (optional)` | `status` `ok` (with `version`) or `not_installed` (`hint` = `note`) | – | – | – |
| render (`render`) | `engine.get_health_status()["backend"]` | `Rendering backend` | not None; `version` = `importlib.metadata.version("verovio")` if `"verovio"` | `fail` | `No rendering backend found; render_to_pdf and render_to_image fail.` | `uv add verovio cairosvg` |
| | `["cairosvg_available"]`, only if `verovio_available` | `cairosvg` | true | `warn` | `PNG and PDF output via Verovio will fail; SVG still works.` | `sudo apt install libcairo2` |
| synth (`synth`) | `SYNTH_SOUNDFONT_PATH` (probes now inline in `server.py`; move them to an MCP-free function, text unchanged) | `Soundfont` | set and the file exists | `fail` | unset: `SYNTH_SOUNDFONT_PATH is not set; download an SF2 soundfont such as TimGM6mb.sf2 (https://sourceforge.net/projects/timidity/files/).` Missing file: `No soundfont file at {path!r}.` | `"env": {"SYNTH_SOUNDFONT_PATH": "/path/to/TimGM6mb.sf2"}` |
| | `import fluidsynth` | `FluidSynth` | imports; `version` = `importlib.metadata.version("pyfluidsynth")` | `fail` (`ImportError`/`OSError`) | `FluidSynth could not be loaded: {e}` | `sudo apt install libfluidsynth-dev` |
| | `import music21` | `music21` | imports; `music21.__version__` | `fail` | `music21 is not installed: {e}` | `uv sync` |
| abc (`abc`) | `engine.health_check()["checks"]["music21"]` | `music21` | `ok`; `version` | `fail` | `music21 is not installed: {error}` | `uv sync` |
| | `…["round_trip"]` (omit if absent) | `ABC round trip` | `ok` | `fail` | `MusicXML → ABC → MusicXML smoke test failed: {error}` | – |
| comparer (`comparer`) | `engine.health_check()["checks"]["music21"]` | `music21` | `ok`; `version` | `fail` | `music21 is not installed: {error}` | `uv sync` |
| | `…["self_compare"]` (omit if absent) | `Self-comparison` | `ok` | `fail` | `Comparing a score with itself failed: {error}` | – |
| pitch (`pitch`) | `engine.health_check()["offline_analysis"]` | `librosa (offline analysis)` | `available`; `librosa_version` | `fail` | `librosa is not installed; analyze_recording fails.` | `uv sync` |
| | `["realtime_monitoring"]` | `Server microphone (PortAudio)` | `available`; `sounddevice_version` | `warn` | `{sounddevice is not installed \| libportaudio2 is missing}; start_monitoring with the server microphone fails. The Practice Coach can still use the browser microphone.` | `uv sync` if not `sounddevice_available`, else `sudo apt install libportaudio2` |
| | `["realtime_monitoring"]["microphone_detected"]`, only if `available` | `Microphone` | true | `warn` | `No input device found on the server; use the browser microphone instead.` | – |

Overall status changes against today's output: omr with `oemer` missing, abc and comparer
`degraded` become `not_ready` (nothing works); render with Verovio but no cairosvg, and pitch
with PortAudio but no input device, become `degraded` (they used to say `ok`).

---

## Error Response Format

All tools must return errors in this consistent structure (never raise unhandled exceptions to the
MCP client):

```json
{
  "error": "Human-readable description of what went wrong",
  "error_code": "SCREAMING_SNAKE_CASE_CODE"
}
```

### Standard error codes

| Code | When to use |
|------|-------------|
| `FILE_NOT_FOUND` | Input file path does not exist |
| `UNSUPPORTED_FORMAT` | File extension or MIME type not supported |
| `FILE_TOO_LARGE` | Input exceeds size limit |
| `INVALID_INPUT` | Input is present but malformed (bad XML, corrupt image, etc.) |
| `PROCESSING_FAILED` | Backend engine error during processing |
| `INVALID_PARAMETER` | A tool parameter value is out of range or logically invalid |
| `SESSION_NOT_FOUND` | Referenced session ID does not exist (for stateful tools) |
| `RESOURCE_NOT_FOUND` | `resources/read` for a URI the server does not offer (sent as JSON-RPC `-32602`, envelope in `data`) |
| `UI_ASSET_MISSING` | A registered MCP Apps UI whose HTML was not built or packaged; the message says to run `npm run build` in `ui/` (sent as JSON-RPC `-32603`, envelope in `data`) |

### Optional fields: `hint` and `choices`

An error may add two optional fields, so the model can recover in one step without a lookup call:

| Field | Type | When to use |
|-------|------|-------------|
| `hint` | string | The fix, written as an instruction: "Re-run with engine='audiveris'", "Scan at 300+ DPI". |
| `choices` | list of strings | The valid values when a parameter did not match: part names, engines. |

```json
{
  "error": "Part 'Sopran' not found",
  "error_code": "INVALID_PARAMETER",
  "hint": "Pass one of the listed part names or IDs",
  "choices": ["Soprano (P1)", "Alto (P2)", "Tenor (P3)", "Bass (P4)"]
}
```

Build errors with `sheet_music_mcp_core.errors.error_payload()` or
`sheet_music_mcp_core.content.error_content()` (see [Shared core library](#shared-core-library)),
never by hand.

---

## Part Selection

Every parameter that names a voice part uses the shared resolver in `sheet_music_mcp_core.parts`.

**Part IDs.** A part's ID is its MusicXML `<score-part id>` (`P1`, `P2`, …), never music21's
`part.id`. music21 replaces `part.id` with the part name, repeats it for same-named parts, and
gives unnamed parts a new integer on every parse. Build the part list with
`music21_part_infos(score.parts)` and select parts **by position** against that list. Staves of one
multi-staff part (a piano) keep music21's staff IDs (`P3-Staff1`, `P3-Staff2`). Report the same IDs
from tools that list parts (`get_parts`).

A requested string is matched in tiers, and the first tier that matches wins:

1. **Exact part ID**, case-sensitive (`P2`).
2. **Part name, abbreviation or ID** after normalising: casefold, strip punctuation, collapse
   spaces, and turn Roman numerals `I`/`II`/`III`/`IV` into `1`/`2`/`3`/`4`. So `"alto ii"`
   matches `Alto 2`, `"q"` matches a part abbreviated `Q.` and `"p2"` matches `P2`.
3. **Voice role**, from the alias table below. A role matches every part whose normalised name is
   one of the role's aliases, optionally followed by a divisi number.

| Role | Aliases (normalised) |
|------|----------------------|
| soprano | `s`, `sop`, `soprano`, `soprani`, `sopran`, `cantus`, `canto`, `tr`, `treble`, `trebles` |
| mezzo-soprano | `ms`, `mez`, `mezzo`, `mezzo soprano`, `mezzosoprano` |
| alto | `a`, `alt`, `alto`, `alti`, `contralto`, `altus` |
| countertenor | `ct`, `countertenor`, `counter tenor`, `countertenors`, `contratenor`, `contra tenor` |
| tenor | `t`, `ten`, `tenor`, `tenori` |
| baritone | `bar`, `bari`, `bariton`, `baritone`, `baritono` |
| bass | `b`, `bas`, `bass`, `bassi`, `basso`, `bassus` |

- Mezzo-soprano, countertenor and baritone are roles of their own: `"Alto"` never selects a mezzo
  or countertenor part, and `"Bass"` never selects a baritone part. Treble is a soprano alias.
- A divisi request (`A1`, `Alto 1`, `Alt I`) matches only that division. A role without a
  number (`Alto`) matches every division (`Alto 1`, `Alto 2`).
- Tools that take several parts call `resolve_parts` and get the IDs in request order, without
  duplicates. Tools that take one part call `resolve_part`, which rejects a request matching
  more than one part.
- No match, or an ambiguous single-part match, returns `INVALID_PARAMETER` with `choices` listing
  `"<name> (<id>)"` for the candidate parts.

### Parameter names

| Meaning | Name | Type |
|---------|------|------|
| One part | `part` | string |
| Several parts | `parts` | array of strings |

Describe them in tool schemas as "part ID, name or voice (e.g. 'P1', 'Soprano', 'S')".

---

## Deprecated Parameter Names

When a parameter is renamed, the old name stays as an alias for **one minor release** and is then
removed. Use `sheet_music_mcp_core.params.aliased`:

- List both names in the schema. Start the old name's description with
  "(Deprecated: use `<new>`)". If the parameter is required, use
  `anyOf: [{"required": ["<new>"]}, {"required": ["<old>"]}]`.
- If only the old name is passed, accept it and log one deprecation warning per process.
- If neither is passed, `make_handlers` reports "one of these parameters is required: '<new>',
  '<old>'" and never echoes the arguments (which would put a whole score into the model's context).
- If both are passed with equal values, accept. If they differ, return `INVALID_PARAMETER`.
- Note the removal in the changelog of the release that removes it.

---

## Tool Annotations and Titles

Every tool sets a human-readable `title` and `annotations` from one of the presets in
`sheet_music_mcp_core.annotations`. Hosts use these to auto-approve read-only tools and to
label tools in their UI. They are hints, not security: path confinement and the no-overwrite
rule still apply.

| Preset | `readOnlyHint` | `destructiveHint` | `idempotentHint` | `openWorldHint` | Use for |
|--------|----------------|-------------------|------------------|-----------------|---------|
| `READ_ONLY` | true | – | – | false | Queries, conversions returned as text, comparisons, `list_capabilities`, `health_check` |
| `READ_ONLY_DOWNLOADS` | true | – | – | true | Read-only tools that may download models or engines on first use |
| `WRITES_FILE` | false | false | false | false | Tools that write an output file (they never overwrite) |
| `WRITES_FILE_DOWNLOADS` | false | false | false | true | The same, with a first-use download |
| `SESSION_STATE` | false | false | false | false | Tools that create, change or end server-side sessions, or open a device |

A tool that opens the microphone or another device is never `READ_ONLY`, so hosts still ask
before using it.

---

## Result Content

- `content[0]` is the JSON text response described in each server's requirements. Never change or
  reorder it. Extra blocks are only appended after it.
- A tool that writes a file appends a `ResourceLink` with a `file://` URI and the file's MIME type,
  using `sheet_music_mcp_core.content.file_link`.
- A tool that writes a PNG appends an `ImageContent` block when the file is at most 1 MB, using
  `sheet_music_mcp_core.content.png_block`. SVG gets no image block.
- A tool that writes a short WAV clip appends an `AudioContent` block (`audio/wav`) when the file
  is at most 200 KB, using `sheet_music_mcp_core.content.audio_block`. Full practice tracks are
  only linked.

---

## Server Instructions

Each server passes `instructions` to `Server(...)`: 3–6 lines the client gives the model at
initialize. Use them for routing knowledge the model would otherwise learn only by failing. For
example: which engine suits choir scores, the call order of a stateful flow, and accepted part
formats. Keep `list_capabilities` as the machine-readable discovery contract.

---

## Score References

Scores can be passed by **file path** instead of inline text, so the model never copies a whole
MusicXML document between tools ([wave 2 plan](research/ux-wave2-plan.md)).

### Inputs

- Every inline score parameter has a path sibling: `musicxml` / `musicxml_path`, and in
  comparer-mcp `reference_xml` / `reference_path` and `target_xml` / `target_path`.
- Exactly one of each pair is required: `{"oneOf": [{"required": ["musicxml"]}, {"required": ["musicxml_path"]}]}`.
  A tool with two pairs combines them with `allOf`. Build both with
  `sheet_music_mcp_core.references.score_input_properties()` and `exactly_one()`.
- Paths may end in `.musicxml`, `.xml` or `.mxl` (compressed). Load them with
  `references.load_score()`; never open a score path yourself.

### Read policy

A path is read only if, after resolving `~`, relative paths (against the output root) and symlinks,
it lies inside one of the **read roots**:

1. the output root, `SHEET_MUSIC_OUTPUT_ROOT` (default: the server's working directory);
2. the client's MCP roots (`roots/list`, when the client declares the capability);
3. the folders in `SHEET_MUSIC_INPUT_ROOTS` (separated by `:` on Linux and macOS, `;` on Windows).

| Check, in order | Error code |
|---|---|
| Outside every read root | `INVALID_PARAMETER`, with a `hint` naming the roots and `SHEET_MUSIC_INPUT_ROOTS` |
| Suffix not allowed | `INVALID_PARAMETER` |
| Missing or not a file | `FILE_NOT_FOUND` |
| Larger than `SHEET_MUSIC_MAX_SCORE_BYTES` (default 16 MiB), or an `.mxl` member that would decompress beyond it | `FILE_TOO_LARGE` |
| Not well-formed XML, not MusicXML, or a bad `.mxl` | `INVALID_INPUT` |

The root check comes first, so a path outside the roots never reveals whether it exists. Error
messages give a line and column at most and **never echo file contents**, so a misdirected read
cannot leak another file into the conversation.

### Outputs

Tools that produce a score take `return: "auto" | "path" | "inline"` (default `auto`):

- `inline`: the score text in `content[0]`, as before.
- `path`: the score is written to `<output root>/scores/<stem>-<timestamp>.musicxml`. In
  `content[0]` the text field (e.g. `musicxml`) is replaced by `<field>_path` plus a
  `score_summary`, and a `ResourceLink` to the file is appended.
- `auto`: `inline` up to `SHEET_MUSIC_INLINE_MAX_BYTES` (default 8192 bytes of UTF-8), otherwise
  `path`.

Use `references.deliver_score()`. Because these tools may write a file, they use the
`WRITES_FILE` or `WRITES_FILE_DOWNLOADS` annotation preset.

`score_summary` is `{title, parts: [{id, name, range}], measures, key, time, tempo_bpm}`.

### `describe_score`

Every server that takes a score exposes the shared `describe_score` tool
(`references.DESCRIBE_SCORE_TOOL`). It returns title, composer, key, time, tempo, parts (ID, name,
abbreviation, clef, range), measures, lyrics presence and duration as small JSON, parsed with the
standard library (`defusedxml`), not music21. Part IDs are the MusicXML `score-part` IDs, the same
ones the part selector accepts.

---

## Measure Ranges

Tools that play, show, export or practise part of a score take `measures: [start, end]`
([wave 3 plan](research/ux-wave3-plan.md)).

- **Printed numbers, inclusive.** `[17, 24]` means the bars numbered 17 to 24 on the page. A pickup
  bar is 0 (a first measure marked `implicit="yes"` is always 0). A suffixed number (`"12a"`)
  belongs to its integer (12); a number with no leading integer takes the previous bar's number.
- **Written order.** Repeats are not expanded and voltas are not skipped.
- **Cut, don't filter.** Use `sheet_music_mcp_core.measures.select_measures(text, measures)` on the
  MusicXML text before the engine parses it. The cut score keeps the key, time, clef, divisions,
  transposition and tempo in force at `start`, so the engine needs no range logic of its own.
- **Schema.** Add `measures.MEASURES_PROPERTY`. Values arriving outside the top-level schema (direct
  engine calls, an `options` object) go through `measures.parse_range()`.
- **Errors.** `start > end`, a range outside the score or a range holding no bar is
  `INVALID_PARAMETER` with a `hint` naming the score's first and last bar numbers.
- **Name.** Always `measures`. comparer-mcp's `options.measure_range` is a deprecated alias.

---

## Practice Audio

Parameter names for practice tracks (synth-mcp `synthesize`, [wave 3 plan](research/ux-wave3-plan.md#32-synth-mcp)):

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `part_gains` | object: part (ID, name or voice) → number 0.0–2.0 | none | Per-part volume as MIDI CC7, `round(127 × gain / 2)`. Parts not listed get 1.0. |
| `preset` | `learning` \| `karaoke` \| `equal` | none | Base gains: learning focus 1.5 / others 0.5; karaoke focus 0 / others 1.0; equal 1.0. `part_gains` overrides per part. |
| `focus_part` | string (part ID, name or voice) | none | The part a `learning` or `karaoke` preset is for; required by those presets. |
| `repeat` | integer 1–20 | 1 | Play the (selected) music this many times. |
| `count_in_bars` | integer 0–4 | 0 | Bars of clicks before the music, in its first time signature and tempo. |
| `metronome` | boolean | false | Clicks on every beat of the music too. |
| `timbre` | `score` \| `piano` \| `choir` \| `organ` | `score` | GM program 0, 52 or 19 on every melodic channel; `score` keeps the score's instruments. |

Clicks use MIDI channel 10: GM 76 (hi wood block) on beat 1 and 77 (low wood block) on other beats,
with beats as music21 counts them (6/8 has two). Every default reproduces the MIDI of earlier
releases.

---

## Shared Core Library

`sheet-music-mcp-core` (directory `sheet-music-mcp-core/`, import `sheet_music_mcp_core`) holds the
code every server needs, so it is written and tested once.

| Module | Purpose | Imports `mcp`? |
|--------|---------|----------------|
| `errors` | `ProcessingError` (with optional `hint` and `choices`), `error_payload()` dict | no |
| `parts` | `PartInfo`, `music21_part_infos()`, `resolve_parts()`, `resolve_part()`, `PartSelectionError` (music21 objects are duck-typed, not imported) | no |
| `params` | `aliased()` for deprecated parameter names | no |
| `annotations` | Annotation presets | no |
| `content` | `error_content()`, `processing_error_content()`, `file_link()`, `png_block()`, `audio_block()` | yes |
| `paths` | Read roots, `confine_read_path()`, `confine_output_path()`, `new_output_path()`, `PathPolicyError` (see [Score References](#score-references)) | no |
| `scores` | `read_score_file()` (`.musicxml`, `.xml`, `.mxl`), `describe_score()`, `score_summary()`, `first_pitches()`, `ScoreFormatError`; parses with `defusedxml`, not music21 | no |
| `measures` | `MEASURES_PROPERTY`, `parse_range()`, `printed_numbers()`, `select_measures()`, `MeasureRangeError` (see [Measure Ranges](#measure-ranges)) | no |
| `artifacts` | Opaque ids for output files that an MCP App reads back in chunks (proposal §5.2, §6.3 rule 3): the `ArtifactStore` protocol (`put(path, kind) -> id`, `info(id) -> ArtifactInfo(artifact_id, kind, byte_length)`, `read_chunk(id, offset, length)`), `FileArtifactStore(output_root=None, ttl_seconds=3600, max_entries=64)`, `InMemoryArtifactStore` (tests; also `put_bytes`), `chunk_payload()` (`{artifact_id, offset, length, byte_length, eof, data_b64}`, the result of every app-only chunk tool), `MAX_CHUNK_BYTES` (1 MiB), `ArtifactError`. The producing tool calls `put` on a file it wrote inside the output root; symlinks anywhere in the path are refused. Ids are random (`secrets.token_urlsafe`), never paths, and live for a fixed TTL from `put` (reads do not extend it), oldest evicted past `max_entries`, all lost on restart. Each read reopens the file with `O_NOFOLLOW` and checks it is the same inode and size inside the root. Unknown, expired or no longer valid ids, a negative or non-integer `offset`/`length`, or `length` over the limit (named in the `hint`) are `INVALID_PARAMETER`; `put` of a missing or non-regular file is `FILE_NOT_FOUND`. Reading at or past the end returns no bytes. The id table is an `expiring.ExpiringTable` | no |
| `expiring` | `ExpiringTable[K, V](*, ttl_seconds, max_entries, clock=time.monotonic, on_evict=None)`: a bounded, thread-safe map for server state an MCP App refers to by handle. `put(value) -> token` (`secrets.token_urlsafe(24)`), `set(key, value)` (replacing restarts the TTL), `get(key) -> value`, `discard(key)` (never raises), `len()`. The TTL is fixed at insert (reads do not extend it); past `max_entries` the oldest goes first. Every miss (never stored, expired, evicted, discarded, unhashable key) raises `EntryNotFound` (a `KeyError` that carries no key), which the caller maps to its own error, usually `INVALID_PARAMETER`. `on_evict(key, value)` runs for entries the table drops on its own (expiry, cap), not for `discard` or replacement, after the lock is released; its exceptions are logged, not raised | no |
| `health` | The standard `health_check` report (see [Health Reports](#health-reports)): `HealthCheck(name, status, version=None, hint=None, fix_snippet=None, doc_url=None)` (frozen; `status` is `ok`, `warn` or `fail`, else `ValueError`; `to_dict()` omits unset fields), `health_report(checks) -> {status, checks}` (duplicate names are a `ValueError`), `HEALTH_OUTPUT_SCHEMA`, `setup_doctor_resource(server) -> UiResource` (`ui://<server>/setup-doctor`, asset `setup-doctor.html`, `permissions={"clipboardWrite": {}}`; imports `ui`, and so `mcp`, only when called) | no |
| `references` | Score input schema helpers, `client_roots()`, `load_score()`, `deliver_score()`, the shared `describe_score` tool | yes |
| `wiring` | `make_handlers()`: input-schema validation and error results for `Server(...)`; pass the server's own `logger=`. Schema failures (`INVALID_PARAMETER`) and exceptions a tool did not handle (`PROCESSING_FAILED`, or a `ProcessingError`'s own code, hint and choices) come back as `isError` results in the `{error, error_code}` envelope. `make_resource_handlers()` serves a resource provider (a `UiRegistry`) as `on_list_resources` / `on_read_resource`; a failed read is logged and raised as an `MCPError` whose `data` is the envelope plus `uri` (`RESOURCE_NOT_FOUND` as `-32602`, anything else as `-32603`). `on_list_tools` hides app-only tools from clients that do not advertise MCP Apps (`client_supports_ui`); `tools/call` still validates and runs them | yes |
| `ui` | MCP Apps UI resources: `UI_MIME`, `UI_EXTENSION`, `UiResource(uri, asset, name, description=None, permissions=None, csp=None)` (with `tool_meta(app_only=False)` and `resource_meta()`), `UiRegistry` (`meta_for(resource, app_only=False)`, `list_resources()`, `read()`), `is_app_only(tool)`, the `AssetSource` protocol with `PackageAssetSource` (built HTML under `<package>/ui/assets/`) and `InMemoryAssetSource` (tests), `UiAssetMissing`, `UiResourceNotFound`, `client_supports_ui()`. An app whose HTML is not packaged is hidden: `meta_for()` returns `None` and it is not listed. `app_only=True` adds `visibility: ["app"]` for tools only an app calls (proposal §6.5); without the HTML such a tool keeps the visibility but loses the link, so the model never sees it. `permissions` (`microphone`, `camera`, `geolocation`, `clipboardWrite`) and `csp` (`connectDomains`, `resourceDomains`, `frameDomains`, `baseUriDomains`) follow the ext-apps `McpUiResourceMeta`: pass the SDK's `mcp.server.apps.ResourcePermissions` / `ResourceCsp` or the same JSON as a mapping (unknown keys are a `ValueError`). The registry sends them as `_meta.ui` on both the `resources/list` entry and the `resources/read` contents; an app that declares neither gets no `_meta` | yes |

- Engines may import only the modules without `mcp` (`errors`, `parts`, `params`, `annotations`, `paths`, `scores`, `measures`, `artifacts`, `expiring`, `health`). This keeps `engine.py` free of MCP imports.
- Servers depend on `sheet-music-mcp-core>=X.Y,<X.(Y+1)` while the core is 0.x. For development,
  they point uv at the local copy, which `uv build` leaves out of published wheels:

  ```toml
  [tool.uv.sources]
  sheet-music-mcp-core = { path = "../sheet-music-mcp-core", editable = true }
  ```

- The core is released before any server release that needs a new core version.

---

## Tooling Standards

| Concern | Standard |
|---------|----------|
| Python version | 3.11+ (pin in `.python-version`) |
| Package manager | `uv` — use `uv sync` to install, `uv run pytest` to test |
| MCP transport | `stdio` — local deployment, compatible with Claude Desktop |
| Async | All MCP tool handlers must be `async def` |
| Logging | Use Python `logging` module; logger name = package name |

### Common commands

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest tests/ -v

# Start the server (for manual testing with Claude Desktop)
uv run <name>-mcp
```

---

## Testing Requirements

Each server must have tests in three categories before it is considered complete:

| Category | Location | Coverage required |
|----------|----------|------------------|
| Unit tests | `tests/test_engine.py`, `tests/test_utils.py` | All validation logic, all error paths, metadata extraction |
| Protocol tests | `tests/test_server.py` | Tool schemas, `list_capabilities` response, error propagation |
| Integration tests | `tests/test_engine.py` (marked `@pytest.mark.integration`) | At least one real end-to-end test with a fixture file |

Integration tests should be skipped by default and opt-in via a marker:

```bash
# Unit tests only (default, fast)
uv run pytest tests/ -v

# Include integration tests (slow, requires real backends)
uv run pytest tests/ -v -m integration
```

---

## Separation of Concerns

Keep MCP protocol logic out of the engine:

| File | Responsibility | Must NOT contain |
|------|---------------|-----------------|
| `server.py` | MCP tool definitions, parameter parsing, calling engine, formatting responses | Business logic, file I/O beyond path resolution |
| `engine.py` | Core processing logic (OMR, synthesis, rendering, etc.) | MCP SDK imports |
| `utils.py` | Input validation, format conversion helpers, file size formatting | Business logic |

This separation makes `engine.py` independently testable without any MCP infrastructure.

---

## Claude Desktop Config Snippet

Every server's `examples/claude_desktop_config.json` must use this format:

```json
{
  "mcpServers": {
    "<name>": {
      "command": "uv",
      "args": ["--directory", "/path/to/<name>-mcp", "run", "<name>-mcp"],
      "env": {}
    }
  }
}
```

Users merge this into `~/.config/claude/claude_desktop_config.json`.
