# comparer-mcp

<!-- mcp-name: io.github.raulkivi/comparer-mcp -->

MCP server for music-aware comparison of MusicXML files. Provides structured, multi-level diffs
that report what changed between two scores — from global similarity down to individual notes.

## What it does

- **Version / arrangement comparison** — Compare different editions, arrangements, or simplifications of the same piece
- **OMR quality evaluation** — Compare `omr-mcp` output against a known-good reference
- **Round-trip fidelity** — Verify MusicXML → ABC → MusicXML through `musicxml-abc-mcp`
- **Regression testing** — Detect regressions when OMR models or conversion logic change
- **Score editing validation** — Confirm LLM-driven edits only changed intended elements

## Installation

```bash
bash install.sh
```

See [SETUP.md](SETUP.md) for client config snippets (Claude Desktop, Cursor, Windsurf, Continue, Zed)
and [TROUBLESHOOTING.md](TROUBLESHOOTING.md) if something doesn't work.

## MCP Tools

| Tool | Description |
|------|-------------|
| `compare_musicxml` | Full diff of two MusicXML strings → structured `ComparisonResult` JSON |
| `compare_musicxml_files` | Full diff of two MusicXML file paths (`.musicxml`, `.xml`, or `.mxl`) → structured `ComparisonResult` JSON |
| `quick_similarity` | Similarity score (0.0–1.0) + summary statistics only, no per-note detail |
| `list_changes` | Note-level diffs (operation != `MATCH`), optionally filtered by part name and/or measure range |
| `generate_comparison_report` | Human-readable version comparison report — similarity headline, missing/extra parts and measures, key/time signature changes, note-level differences grouped by measure range (e.g. "transposed by 3 semitones in measures 17-24") |
| `export_annotated_musicxml` | MusicXML with per-note color annotations marking the diff; returns `reference_annotated_musicxml` + `target_annotated_musicxml`, chainable straight into render-mcp's `render_to_pdf`/`render_to_image` |
| `health_check` | Server status — verifies music21 is importable and runs a self-comparison smoke test |
| `list_capabilities` | Server metadata per project conventions |

```json
// Compare two MusicXML strings
{
  "tool": "compare_musicxml",
  "arguments": {
    "reference_xml": "<score-partwise>...</score-partwise>",
    "target_xml": "<score-partwise>...</score-partwise>"
  }
}

// Compare two files
{
  "tool": "compare_musicxml_files",
  "arguments": {
    "reference_path": "/path/to/reference.musicxml",
    "target_path": "/path/to/omr_output.musicxml"
  }
}

// Quick similarity check
{
  "tool": "quick_similarity",
  "arguments": {
    "reference_xml": "<score-partwise>...</score-partwise>",
    "target_xml": "<score-partwise>...</score-partwise>"
  }
}
// → {"similarity_score": 0.87, "summary": {...}}

// Filtered changes, e.g. "what changed in the Alto, measures 17-24?"
{
  "tool": "list_changes",
  "arguments": {
    "reference_xml": "<score-partwise>...</score-partwise>",
    "target_xml": "<score-partwise>...</score-partwise>",
    "part": "Alto",
    "measure_range": [17, 24]
  }
}
// → {"changes": [{"measure_number": 18, "operation": "PITCH_CHANGE", "part_name": "Alto", ...}], "count": 1}

// Human-readable report
{
  "tool": "generate_comparison_report",
  "arguments": {
    "reference_xml": "<score-partwise>...</score-partwise>",
    "target_xml": "<score-partwise>...</score-partwise>"
  }
}
// → {"report": "Overall similarity: 87% (minor differences)\n...", "similarity_score": 0.87}

// Colored MusicXML diff export — chain straight into render-mcp to visualize
{
  "tool": "export_annotated_musicxml",
  "arguments": {
    "reference_xml": "<score-partwise>...</score-partwise>",
    "target_xml": "<score-partwise>...</score-partwise>"
  }
}
// → {"reference_annotated_musicxml": "...", "target_annotated_musicxml": "...",
//    "similarity_score": 0.87, "legend": {"PITCH_CHANGE": "#FF8800", ...}}
```

`compare_musicxml`, `compare_musicxml_files`, `generate_comparison_report`, and
`export_annotated_musicxml` all accept an optional `options` object:

```json
{
  "expand_repeats": false,        // unfold repeats before comparing (default: false — opt-in)
  "normalize_pitch": false,       // transpose transposing instruments to concert/sounding pitch
  "ignore_articulations": false,  // exclude articulations from NoteInfo/diffs
  "part_filter": ["Soprano"],     // compare only named parts (case-insensitive)
  "measure_range": [1, 32]        // compare only measures 1-32, inclusive
}
```

## Using the engine directly

The comparison engine (`src/comparer_mcp/engine.py`) has no MCP dependency and is fully usable as
a plain Python library, independent of the MCP server:

```bash
cd comparer-mcp
uv sync
```

```python
from comparer_mcp.engine import compare, compare_files

# Compare two MusicXML strings
result = compare(reference_xml, target_xml)

# Compare two files (.musicxml, .xml, or compressed .mxl)
result = compare_files("reference.musicxml", "omr_output.mxl")

print(result.similarity_score)   # float, 0.0-1.0
print(result.summary)            # ComparisonSummary: parts/measures/notes matched, missing, changed
print(result.part_diffs)         # list[PartDiff] -> list[MeasureDiff] -> list[NoteDiff]
```

Errors are raised as `comparer_mcp.engine.ProcessingError` (e.g. for a missing file or invalid
MusicXML), carrying a `.error_code` attribute (`FILE_NOT_FOUND`, `INVALID_INPUT`, etc.) matching
the format the MCP tools return.

## Testing

```bash
# Unit tests
VIRTUAL_ENV= .venv/bin/pytest tests/ -v -m "not integration"

# Integration tests (real .mxl SATB fixtures shared with omr-mcp)
VIRTUAL_ENV= .venv/bin/pytest tests/ -v -m integration

# Install dependencies
uv sync
```

## Dependencies

- [music21](https://web.mit.edu/music21/) — MusicXML parsing, score object model, stream alignment
- [numpy](https://numpy.org/) — distance matrix for note alignment (transitive via music21)
- [mcp](https://github.com/modelcontextprotocol/python-sdk) — MCP protocol

## System requirements

- Python 3.11+
- No system libraries required

## Phase status

| Phase | Status |
|-------|--------|
| Phase 1 — Core comparison (MVP) | **Complete** — 45/45 tests passing (43 unit + 2 integration) |
| Phase 2 — Rich detail (key/time signature diffs, voice-aware alignment, articulations) | **Complete** — 67/67 tests passing (65 unit + 2 integration) |
| Phase 3 — MCP server & integration (`server.py`, all 6 tools, `install.sh`, `SETUP.md`, client config examples) | **Complete** — 94/94 tests passing (90 unit + 4 integration) |
| Phase 4 — Advanced features (`options` wiring, `generate_comparison_report`, `export_annotated_musicxml`) | **Complete** — 134/134 tests passing (127 unit + 7 integration) |
