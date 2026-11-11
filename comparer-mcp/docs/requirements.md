# comparer-mcp — Requirements

## Functional requirements

### FR-1: Full comparison

Compare two MusicXML inputs (string or file path) and return a structured `ComparisonResult` containing:
- Global similarity score (0.0–1.0)
- Summary statistics (parts matched/missing, notes identical/changed/missing)
- Per-part diffs with per-measure and per-note detail

### FR-2: Part matching

Match parts between two scores using a priority cascade:
1. Exact part name (case-insensitive)
2. MIDI program / instrument
3. Positional order
4. Pitch range heuristic

**Currently implemented: steps 1 and 3 only.** Steps 2 and 4 are not implemented (see
`docs/HANDOVER.md` "What does NOT exist yet" and "Next steps (beyond Phase 4)") — a part with no
name match falls straight to positional pairing, skipping any instrument- or range-based match.

Report unmatched parts as missing (in reference only) or extra (in target only).

### FR-3: Note-level alignment

Within matched measures, align note sequences using edit-distance. Classify each difference as:
`MATCH`, `PITCH_CHANGE`, `DURATION_CHANGE`, `SUBSTITUTION`, `INSERTION`, `DELETION`.

### FR-4: Similarity scoring

Weighted aggregate: 30% structure (parts + measures matched) + 70% note accuracy.

### FR-5: Filtering

Support filtering comparison by, via `options` on `compare()`/`compare_files()`:
- `parts` (deprecated alias `part_filter`): part IDs, names or voices, resolved against the
  reference score and applied before part matching; target parts are picked by the selected
  parts' names (by ID when unnamed). An unknown part is `INVALID_PARAMETER` with `choices`.
- `list_changes.part`: one part ID, name or voice, resolved against the compared parts
- Part IDs in results are MusicXML score-part ids (`"P1"`), never music21's `part.id`; unnamed
  parts are reported by ID in `part_name`, `parts_missing` and `parts_extra`
- `measures` (deprecated alias `measure_range`, one minor release): `[start, end]` inclusive measure
  numbers, applied to measures and key/time signature diffs. A filter: the scores are not cut
  (unlike the other servers' `measures`). Validated by the core's
  `measures.parse_range(..., param="options.measures")`: a reversed or malformed range is
  `INVALID_PARAMETER` with a hint; both names with different values is `INVALID_PARAMETER`
  (`params.aliased`), and the old name alone logs one deprecation warning per process
- `ignore_articulations`: blanks `NoteInfo.articulations`
- `normalize_pitch`: transposes transposing instruments to concert/sounding pitch (`Score.toSoundingPitch()`) before comparing
- `expand_repeats`: unfolds repeat structure (`Score.expandRepeats()`) before comparing; **default `false`** (opt-in — see `docs/PLAN.md` "Changed decisions"); a malformed repeat structure raises `ProcessingError("PROCESSING_FAILED")` rather than crashing

`list_changes`'s `part`/`measures` arguments remain a separate, server.py-side post-filter of
an already-computed result (unrelated to `options`, unchanged since Phase 3). Its `measures` has the
same deprecated alias `measure_range` and the same validation (`parse_range`, `param="measures"`).

### FR-6: Quick similarity

Return only the similarity score and summary statistics (no note-level detail) for fast queries.

### FR-7: MCP tools

Expose as MCP server with tools: `compare_musicxml`, `compare_musicxml_files`, `quick_similarity`, `list_changes`, `generate_comparison_report`, `export_annotated_musicxml`, `describe_score`, `health_check`, `list_capabilities`.

`describe_score` is the shared tool from `sheet-music-mcp-core` (UX Wave 2, C18): title, composer,
key, time, tempo, parts (MusicXML part ID, name, clef, range), measures, lyrics and duration as small
JSON, from `musicxml` or `musicxml_path`.

### FR-8: Human-readable comparison report

`generate_comparison_report` returns a multi-line text summary of a `ComparisonResult`: overall
similarity headline, missing/extra parts, missing/extra measures, key/time signature changes, and
note-level differences grouped into measure-range runs (e.g. "8 pitch changes in measures 17-24",
or "transposed by 3 semitones in measures 17-24" when every pitch change in a run shares the same
`interval_error`).

### FR-9: Annotated MusicXML diff export

`export_annotated_musicxml` produces two MusicXML documents — the annotated reference and the
annotated target — with per-note `color` attributes marking the diff operation
(`PITCH_CHANGE`, `DURATION_CHANGE`, `SUBSTITUTION`, `INSERTION`, `DELETION`; `MATCH` left
uncolored). Both documents are valid standalone MusicXML. Structural-only diffs (a whole
measure/part missing or extra on one side) are not colored.

How they are returned depends on `return` (UX Wave 2, C25; `deliver_score` from the core):

| `return` | Result |
|---|---|
| `inline` | `reference_annotated_musicxml` and `target_annotated_musicxml` as text, as before Wave 2 |
| `path` | Both written to `<output root>/scores/annotated-<field>-<timestamp>.musicxml`; the result has `reference_annotated_musicxml_path`, `target_annotated_musicxml_path` and `score_summary` keyed by field (`reference_annotated_musicxml`, `target_annotated_musicxml`), followed by one `ResourceLink` per file |
| `auto` (default) | `inline` when both documents are at most `SHEET_MUSIC_INLINE_MAX_BYTES` (8192 bytes); otherwise `path` for both |

`similarity_score` and `legend` are always present. Feed the returned paths to render-mcp's
`render_to_pdf`/`render_to_image` as `musicxml_path` to visualize the diff. Because the tool may
write files, its annotation preset is `WRITES_FILE`.

---

## Non-functional requirements

### NFR-1: No MCP dependency in engine

`engine.py` must not import from `mcp` — keeps comparison logic independently testable and reusable by other servers.

### NFR-2: Error format

All tool errors return `{"error": "human description", "error_code": "SCREAMING_SNAKE"}`.

Standard error codes: `FILE_NOT_FOUND`, `FILE_TOO_LARGE`, `INVALID_INPUT`, `UNSUPPORTED_FORMAT`, `PROCESSING_FAILED`, `INVALID_PARAMETER`.

### NFR-3: Performance

- Simple SATB comparison (4 parts, 30 measures): < 5 seconds
- Large orchestral score: best-effort, no hard timeout

### NFR-4: Test coverage

- Unit tests for all modules (target: 30+ for Phase 1)
- Integration tests marked `@pytest.mark.integration`
- Integration tests must not run in default `pytest` invocation

---

## Interfaces

### Tool metadata and server instructions

Every tool sets a human-readable `title` and an annotation preset from `sheet-music-mcp-core`
(see [conventions: Tool Annotations and Titles](../../docs/conventions.md#tool-annotations-and-titles)).
The per-tool table of titles and presets is `tests/test_tool_metadata.py`. The server sends
`instructions` at initialize ([conventions: Server Instructions](../../docs/conventions.md#server-instructions)).

### MCP Apps: Diff Viewer

`ui://comparer/diff-viewer` (proposal 5.4). `compare_musicxml`, `compare_musicxml_files` and
`generate_comparison_report` link it through `_meta.ui.resourceUri` when the HTML is packaged;
without a UI build the resource is unlisted and the tools carry no `_meta.ui`. Those tools also
return `structuredContent` and declare an `output_schema`: the full `ComparisonResult` (schema
generated from `models.py`, AC-C1) or `{report, similarity_score}`. `content` is unchanged text
(golden test). The viewer reuses `list_changes` and `export_annotated_musicxml` as ordinary
app-callable tools; no app-only tools exist. Failures stay `{error, error_code}` with `isError: true`
and no `structuredContent`. Open: AC-C2 (size-bounded `content`, proposal P7) is not implemented.

### Input formats

- MusicXML string (`<score-partwise>` or `<score-timewise>`)
- MusicXML file path (`.musicxml`, `.xml`, `.mxl`)

### Score inputs (UX Wave 2)

`compare_musicxml`, `quick_similarity`, `list_changes`, `generate_comparison_report` and
`export_annotated_musicxml` take each score inline or as a path
([conventions: Score References](../../docs/conventions.md#score-references)):

| Side | Inline | Path |
|---|---|---|
| Reference | `reference_xml` | `reference_path` |
| Target | `target_xml` | `target_path` |

Exactly one of each pair is required (`"allOf": [oneOf reference, oneOf target]`); the sides can
mix, e.g. `reference_path` with `target_xml`. Both or neither of a pair is `INVALID_PARAMETER`.
Paths are read by the core's `load_score`: inside the read roots (output root
`SHEET_MUSIC_OUTPUT_ROOT`, the client's MCP roots, `SHEET_MUSIC_INPUT_ROOTS`), `.musicxml`/`.xml`/
`.mxl`, at most `SHEET_MUSIC_MAX_SCORE_BYTES`, well-formed MusicXML. A path outside the roots or
with another suffix is `INVALID_PARAMETER`; a missing file `FILE_NOT_FOUND`; too large
`FILE_TOO_LARGE`; not MusicXML `INVALID_INPUT` (prefixed with the parameter name). Errors never
contain file contents. Inline text keeps its `reference_xml: ...` / `target_xml: ...` checks, and
an inline call returns exactly what it did before Wave 2.

`compare_musicxml_files` keeps its schema (`reference_path` and `target_path`, both required) and
reads both files through the same policy, then runs the text comparison. Since Wave 2 (plan
decision W2-2) a file outside the read roots is rejected (`INVALID_PARAMETER`) and a wrong suffix
is `INVALID_PARAMETER` instead of `UNSUPPORTED_FORMAT`; add other folders with
`SHEET_MUSIC_INPUT_ROOTS`.

`list_capabilities` reports `input_formats: ["musicxml", "mxl"]` and
`input_parameters: ["reference_xml", "reference_path", "target_xml", "target_path"]`.

### Output format

JSON-serializable `ComparisonResult` — see `docs/architecture.md` §4 for full data model.
