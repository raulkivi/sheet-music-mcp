# comparer-mcp — Claude Code Instructions

## What This Server Does

Music-aware comparison of two MusicXML files. Provides structured, multi-level diffs
from global similarity score down to individual note differences. Primary use cases:
version/arrangement comparison, OMR quality evaluation, round-trip fidelity testing.

**Status:** Phase 4 (Advanced features) complete — all originally-scoped phases done. UX Wave 2
(score references) complete. 239 unit tests pass (+7 integration, which need the omr-mcp `.mxl`
samples). `server.py` exposes all 9 tools; engine.py/models.py/part_matcher.py/note_aligner.py/
measure_comparator.py/report.py/annotator.py/utils.py are all implemented and independently usable.

---

## Running Tests

```bash
# From this directory
VIRTUAL_ENV= .venv/bin/pytest tests/ -v              # unit tests
VIRTUAL_ENV= .venv/bin/pytest tests/ -v -m integration  # integration tests
```

Install dependencies: `uv sync --extra dev` (pytest is in the `dev` extra; plain `uv sync` removes it)

---

## Key Files

| File | Purpose |
|------|---------|
| `src/comparer_mcp/server.py` | MCP tool definitions and handlers |
| `src/comparer_mcp/score_inputs.py` | Reference/target pair: schema and loading (inline or path) |
| `src/comparer_mcp/engine.py` | Comparison orchestration (no MCP imports) |
| `src/comparer_mcp/models.py` | Dataclasses: ComparisonResult, NoteDiff, etc. |
| `src/comparer_mcp/part_matcher.py` | Part matching logic (name, instrument, range) |
| `src/comparer_mcp/note_aligner.py` | Edit-distance note alignment |
| `src/comparer_mcp/measure_comparator.py` | Measure-level structural comparison |
| `src/comparer_mcp/report.py` | Human-readable comparison report (pure `ComparisonResult` -> str) |
| `src/comparer_mcp/annotator.py` | Colored MusicXML diff export |
| `src/comparer_mcp/utils.py` | Validation, pitch names, duration formatting |
| `docs/HANDOVER.md` | Status, remaining work, definition of done |
| `docs/PLAN.md` | Implementation plan and technology decisions |
| `docs/requirements.md` | Functional/non-functional requirements |
| `docs/architecture.md` | Full vision, pipeline design, data model |

---

## Implemented Tools

| Tool | Description |
|------|-------------|
| `compare_musicxml` | Full diff of two scores (inline or by path) |
| `compare_musicxml_files` | Full diff of two MusicXML file paths (read roots apply) |
| `quick_similarity` | Similarity score (0.0–1.0) + summary |
| `list_changes` | Filtered note-level diffs |
| `generate_comparison_report` | Human-readable version comparison report |
| `export_annotated_musicxml` | Colored MusicXML diff export; paths for large results (`return`), feed them to render-mcp's `musicxml_path` |
| `describe_score` | Shared core tool: parts (IDs), key, time, range, measures — cheap, no music21 |
| `health_check` | Server status and music21 version |
| `list_capabilities` | Server metadata per conventions |

Score references (UX Wave 2): every tool that took `reference_xml` / `target_xml` also takes
`reference_path` / `target_path`, exactly one of each pair (`score_inputs.py`, built on
`sheet_music_mcp_core.references`). Paths are confined to the read roots (`SHEET_MUSIC_OUTPUT_ROOT`,
client roots, `SHEET_MUSIC_INPUT_ROOTS`) — `compare_musicxml_files` too, so tests that read files
must set one of those to their tmp dir. Never open a score path yourself; use `load_pair()`.

---

## Environment

- **Core library:** `music21` — MusicXML parsing, score model, stream alignment
- **No system dependencies** required
- **music21 import is slow** (~2s first time) — this is expected

---

## Hard Rules

- **Never `pip install`** — use `uv sync` or `uv add`
- **`engine.py` must not import from `mcp`** — keeps it unit-testable
- **All tool handlers must be `async def`**
- **All errors** → `{"error": "...", "error_code": "..."}` (codes: `FILE_NOT_FOUND`, `FILE_TOO_LARGE`, `INVALID_INPUT`, `UNSUPPORTED_FORMAT`, `PROCESSING_FAILED`, `INVALID_PARAMETER`)
- **Integration tests** must be `@pytest.mark.integration`

---

## MCP Server Startup Pattern

```python
import asyncio
import mcp.server.stdio

async def _run():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

asyncio.run(_run())
```

`run_server()` does not exist in the installed MCP SDK — use the context manager above.
