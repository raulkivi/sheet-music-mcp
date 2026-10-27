# render-mcp — Copilot Instructions

## What This Server Does

Renders MusicXML scores to PDF (for printing) or PNG (for display in web/mobile apps).
Backend: Verovio (in-process Python) + cairosvg + pypdf. No MuseScore CLI required.

**Status:** Phase 1 + UX Waves 1–3 complete. 169 unit tests (default run) + 9 integration tests.

---

## Before You Write Any Code

Read these documents in order:
1. **`docs/HANDOVER.md`** — current status, remaining work, pre-flight checks, known gotchas, definition of done
2. **`docs/PLAN.md`** — architecture decisions and technology rationale
3. **`docs/requirements.md`** — functional and non-functional requirements, error codes
4. **`docs/architecture.md`** — component diagram, data-flow, module responsibilities

---

## Project Structure

```
render-mcp/
├── pyproject.toml
├── .python-version          # "llm311"
├── src/render_mcp/
│   ├── server.py            # MCP tool definitions and async handlers
│   ├── engine.py            # Verovio + cairosvg rendering — NO mcp imports
│   └── utils.py             # MusicXML validation, path helpers
├── tests/
│   ├── test_server.py       # protocol tests
│   ├── test_engine.py       # unit + integration tests
│   ├── test_utils.py        # unit tests
│   ├── test_score_references.py  # musicxml_path, describe_score
│   ├── test_measures.py     # measures range (backend spies, errors, real Verovio cut)
│   └── fixtures/
└── docs/
    ├── requirements.md
    └── architecture.md
```

MXL test fixtures are in `../omr-mcp/test_samples/pdmx_satb_samples/mxl/` — 10 SATB files.

---

## Implemented Tools

| Tool | Description |
|------|-------------|
| `render_to_pdf` | MusicXML → multi-page PDF at caller-specified or auto-generated path |
| `render_to_image` | MusicXML → PNG or SVG, single page, configurable DPI (72–600) |
| `list_capabilities` | Server metadata, active backend, format support |
| `health_check` | Runtime dependency check |
| `describe_score` | Shared (core) tool: parts with IDs, key, time, tempo, measures, duration — no rendering |

Both render tools take the score as `musicxml` (inline) or `musicxml_path` (`.musicxml`, `.xml`,
`.mxl`; exactly one). Paths are read via `sheet_music_mcp_core.references.load_score()`, confined
to the output root, the client's roots and `SHEET_MUSIC_INPUT_ROOTS` (UX Wave 2, score references).
Both also take an optional `measures: [start, end]` (printed bar numbers, inclusive; UX Wave 3):
the engine cuts the score with `sheet_music_mcp_core.measures.select_measures()` before backend
dispatch, so MuseScore and Verovio render the same bars.

---

## Environment

- **Backend:** Verovio (MusicXML → SVG, pure Python) + cairosvg (SVG → PNG/PDF) + pypdf (merge)
- **System dep:** `libcairo.so.2` — installed system-wide on Ubuntu; no sudo needed
- **No MuseScore CLI** — do not check for or call `mscore4`/`musescore4`
- Integration tests run in-process (Verovio requires no external tools) — no special setup needed

---

## Coding Standards

- **Package manager:** `uv` only — never `pip install`
- **`engine.py` must not import from `mcp`** — keeps it independently unit-testable
- **All tool handlers must be `async def`**
- **All error responses:** `{"error": "human description", "error_code": "SCREAMING_SNAKE"}`
- **Standard error codes:** `INVALID_INPUT`, `PROCESSING_FAILED`, `INVALID_PARAMETER`, `FILE_NOT_FOUND`
- **Integration tests** must be `@pytest.mark.integration` — not run in the default `pytest` invocation
- **Python 3.11+**; `asyncio_mode = "auto"` in pytest config
- **Score paths:** read only through `sheet_music_mcp_core.references.load_score()`; never open them directly

---

## Running Tests

```bash
# All tests including integration (Verovio is in-process, no external deps)
VIRTUAL_ENV= .venv/bin/pytest tests/ -v

# Install dependencies
uv sync
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

---

## Known Gotchas

- **cairosvg DPI with Verovio SVGs.** Verovio emits SVGs with fixed pixel dimensions — the `dpi`
  kwarg in `cairosvg.svg2png(dpi=...)` has no effect. Use `scale=dpi/96.0` instead.
- **Multi-page PDF pipeline:** each SVG page → single-page PDF via cairosvg → merge with pypdf.
  Single-page scores skip the merge step.
- **MuseScore is not installed.** Don't attempt to call any MuseScore CLI command.
- **Schema `oneOf`, not `required`.** The render tools take exactly one of `musicxml` /
  `musicxml_path`; there is no `required` list.
- **Measure ranges are cut in the engine, not the backends.** `render_to_pdf` / `render_to_image`
  apply `select_measures` before dispatch; keep the `_render_*` functions unaware of ranges.
  `page` counts pages of the cut score. Bad ranges are `INVALID_PARAMETER` with a `hint`.

---

## When You Finish Work

Update these documents so the next session starts with accurate information:
- **`docs/HANDOVER.md`** — check off done items, add new gotchas, update status
- **`docs/PLAN.md`** — check off completed phase items, note changed decisions
- **`docs/requirements.md`** — update if behaviour or interfaces changed
- **`docs/architecture.md`** — update if implementation structure changed
