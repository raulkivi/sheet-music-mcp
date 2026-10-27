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
- `part_filter`: part name(s), applied before part matching
- `measure_range`: `[start, end]` inclusive, applied to measures and key/time signature diffs
- `ignore_articulations`: blanks `NoteInfo.articulations`
- `normalize_pitch`: transposes transposing instruments to concert/sounding pitch (`Score.toSoundingPitch()`) before comparing
- `expand_repeats`: unfolds repeat structure (`Score.expandRepeats()`) before comparing; **default `false`** (opt-in — see `docs/PLAN.md` "Changed decisions"); a malformed repeat structure raises `ProcessingError("PROCESSING_FAILED")` rather than crashing

`list_changes`'s `part`/`measure_range` arguments remain a separate, server.py-side post-filter of
an already-computed result (unrelated to `options`, unchanged since Phase 3).

### FR-6: Quick similarity

Return only the similarity score and summary statistics (no note-level detail) for fast queries.

### FR-7: MCP tools

Expose as MCP server with tools: `compare_musicxml`, `compare_musicxml_files`, `quick_similarity`, `list_changes`, `generate_comparison_report`, `export_annotated_musicxml`, `health_check`, `list_capabilities`.

### FR-8: Human-readable comparison report

`generate_comparison_report` returns a multi-line text summary of a `ComparisonResult`: overall
similarity headline, missing/extra parts, missing/extra measures, key/time signature changes, and
note-level differences grouped into measure-range runs (e.g. "8 pitch changes in measures 17-24",
or "transposed by 3 semitones in measures 17-24" when every pitch change in a run shares the same
`interval_error`).

### FR-9: Annotated MusicXML diff export

`export_annotated_musicxml` returns two MusicXML documents — `reference_annotated_musicxml` and
`target_annotated_musicxml` — with per-note `color` attributes marking the diff operation
(`PITCH_CHANGE`, `DURATION_CHANGE`, `SUBSTITUTION`, `INSERTION`, `DELETION`; `MATCH` left
uncolored). Both documents are valid standalone MusicXML, chainable directly into render-mcp's
`render_to_pdf`/`render_to_image` tools (both accept a raw `musicxml` string) to visualize the
diff. Structural-only diffs (a whole measure/part missing or extra on one side) are not colored.

---

## Non-functional requirements

### NFR-1: No MCP dependency in engine

`engine.py` must not import from `mcp` — keeps comparison logic independently testable and reusable by other servers.

### NFR-2: Error format

All tool errors return `{"error": "human description", "error_code": "SCREAMING_SNAKE"}`.

Standard error codes: `FILE_NOT_FOUND`, `INVALID_INPUT`, `UNSUPPORTED_FORMAT`, `PROCESSING_FAILED`, `INVALID_PARAMETER`.

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

### Input formats

- MusicXML string (`<score-partwise>` or `<score-timewise>`)
- MusicXML file path (`.musicxml`, `.xml`, `.mxl`)

### Output format

JSON-serializable `ComparisonResult` — see `docs/architecture.md` §4 for full data model.
