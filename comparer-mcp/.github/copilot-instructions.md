# comparer-mcp — Copilot Instructions

## What This Server Does

Music-aware comparison of two MusicXML files. Provides structured, multi-level diffs
from global similarity score down to individual note differences. Primary use cases:
version/arrangement comparison, OMR quality evaluation, round-trip fidelity testing.

**Status:** Phase 4 (Advanced features) complete — all originally-scoped phases done. UX Wave 2
(score references) complete. 239 unit tests pass (+7 integration). `server.py` exposes all 9 tools.

---

## Before You Write Any Code

Read these documents in order:
1. **`docs/HANDOVER.md`** — current status, remaining work, definition of done
2. **`docs/PLAN.md`** — implementation plan and technology decisions
3. **`docs/requirements.md`** — functional and non-functional requirements
4. **`docs/architecture.md`** — full vision, 5-layer comparison pipeline, data model, similarity scoring

---

## Project Structure

```
comparer-mcp/
├── pyproject.toml
├── .python-version          # 3.11
├── src/comparer_mcp/
│   ├── server.py            # MCP tool definitions, dispatches to engine
│   ├── score_inputs.py      # Reference/target pair: schema and loading (inline or path)
│   ├── engine.py            # Comparison orchestration — NO mcp imports
│   ├── models.py            # Dataclasses: ComparisonResult, NoteDiff, etc.
│   ├── part_matcher.py      # Part matching (name, instrument, range)
│   ├── measure_comparator.py # Measure-level structural comparison
│   ├── note_aligner.py      # Edit-distance note alignment
│   ├── report.py            # Human-readable comparison report (pure ComparisonResult -> str)
│   ├── annotator.py         # Colored MusicXML diff export
│   └── utils.py             # Validation, pitch names, duration formatting
├── tests/
│   ├── test_engine.py       # End-to-end comparison tests
│   ├── test_server.py       # Tool schemas, error propagation
│   ├── test_part_matcher.py # Part matching edge cases
│   ├── test_note_aligner.py # Alignment algorithm tests
│   ├── test_report.py
│   ├── test_annotator.py
│   ├── test_score_references.py # Path inputs, read policy, return modes, describe_score
│   ├── test_utils.py
│   └── fixtures/            # MusicXML test files
└── docs/
    ├── HANDOVER.md
    ├── PLAN.md
    ├── requirements.md
    └── architecture.md
```

---

## Implemented Tools

| Tool | Description |
|------|-------------|
| `compare_musicxml` | Full diff of two scores (inline or by path) → structured `ComparisonResult` JSON |
| `compare_musicxml_files` | Full diff of two MusicXML file paths (read roots apply) → structured `ComparisonResult` JSON |
| `quick_similarity` | Similarity score (0.0–1.0) + summary statistics |
| `list_changes` | Filtered note-level diffs (by part, measure range) |
| `generate_comparison_report` | Human-readable version comparison report |
| `export_annotated_musicxml` | Colored MusicXML diff export; paths for large results (`return`), feed them to render-mcp's `musicxml_path` |
| `describe_score` | Shared core tool: parts (IDs), key, time, range, measures |
| `health_check` | Server status and music21 version |
| `list_capabilities` | Server metadata per conventions |

Each score is given inline (`reference_xml`, `target_xml`) or by path (`reference_path`,
`target_path`), exactly one of each pair. Paths go through `sheet_music_mcp_core.references.load_score`
(via `score_inputs.load_pair`), which confines them to the read roots.

---

## Coding Standards

- **Package manager:** `uv` only — never `pip install`
- **`engine.py` must not import from `mcp`** — keeps it independently unit-testable
- **All tool handlers must be `async def`**
- **All error responses:** `{"error": "human description", "error_code": "SCREAMING_SNAKE"}`
- **Standard error codes:** `FILE_NOT_FOUND`, `FILE_TOO_LARGE`, `INVALID_INPUT`, `UNSUPPORTED_FORMAT`, `PROCESSING_FAILED`, `INVALID_PARAMETER`
- **Integration tests** → `@pytest.mark.integration`
- **Python 3.11+**; `asyncio_mode = "auto"` in pytest config

---

## Running Tests

```bash
# Unit tests
VIRTUAL_ENV= .venv/bin/pytest tests/ -v

# Integration tests
VIRTUAL_ENV= .venv/bin/pytest tests/ -v -m integration

# Install dependencies (pytest is in the dev extra)
uv sync --extra dev
```

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

`mcp.server.stdio.run_server()` does not exist — always use the context manager above.
