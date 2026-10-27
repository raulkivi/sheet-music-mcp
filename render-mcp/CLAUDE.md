# render-mcp — Claude Code Instructions

## What This Server Does

Renders MusicXML scores to PDF (for printing) or PNG (for display in web/mobile apps).
Uses Verovio (in-process) + cairosvg + pypdf. No MuseScore CLI required.

**Status:** Phase 1 + UX Waves 1–2 complete. 147 unit tests (default run) + 9 integration.

---

## Running Tests

```bash
# From this directory
VIRTUAL_ENV= .venv/bin/pytest tests/ -v             # 147 unit tests (integration deselected)
VIRTUAL_ENV= .venv/bin/pytest tests/ -v -m integration  # Verovio runs in-process, always fast
```

Install dependencies: `uv sync`

---

## Key Files

| File | Purpose |
|------|---------|
| `src/render_mcp/server.py` | MCP tool definitions and handlers |
| `src/render_mcp/engine.py` | Verovio + cairosvg rendering pipeline (no MCP imports) |
| `src/render_mcp/utils.py` | MusicXML validation, path helpers |
| `docs/HANDOVER.md` | Status, remaining work, definition of done |
| `docs/PLAN.md` | Architecture decisions and rationale |
| `docs/requirements.md` | Functional/non-functional requirements |
| `docs/architecture.md` | Component diagram and data-flow |

---

## Implemented Tools

| Tool | Description |
|------|-------------|
| `render_to_pdf` | MusicXML → multi-page PDF at caller-specified path |
| `render_to_image` | MusicXML → PNG or SVG, single page, configurable DPI |
| `list_capabilities` | Server metadata, active backend, format support |
| `health_check` | Runtime dependency check |
| `describe_score` | Shared (core) tool: parts with IDs, key, time, tempo, measures, duration — no rendering |

Both render tools take the score as `musicxml` (inline) or `musicxml_path` (`.musicxml`, `.xml`,
`.mxl`; exactly one). Paths are read via `sheet_music_mcp_core.references.load_score()`, confined
to the output root, the client's roots and `SHEET_MUSIC_INPUT_ROOTS` (UX Wave 2, score references).

---

## Environment

- **Backend:** Verovio (MusicXML → SVG, in-process Python) + cairosvg (SVG → PNG/PDF) + pypdf (merge pages)
- **System dep:** `libcairo.so.2` — installed system-wide on Ubuntu, no sudo needed
- **No MuseScore CLI** — do not attempt to invoke `mscore4`/`musescore4`
- **MXL fixtures:** `../omr-mcp/test_samples/pdmx_satb_samples/mxl/` (10 SATB files)

---

## Hard Rules

- **Never `pip install`** — use `uv sync --extra dev` (pytest is a `dev` extra) or `uv add`
- **Never open a score path yourself** — use `references.load_score()`; output paths go through
  `confine_output_path` (re-exported from `sheet_music_mcp_core.paths` in `utils.py`)
- **`engine.py` must not import from `mcp`** — keeps it unit-testable
- **All tool handlers must be `async def`**
- **All errors** → `{"error": "...", "error_code": "..."}` (codes: `INVALID_INPUT`, `PROCESSING_FAILED`, `INVALID_PARAMETER`, `FILE_NOT_FOUND`)
- **Integration tests** must be `@pytest.mark.integration` and skipped in the default run

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

---

## Known Gotchas

- **cairosvg DPI with Verovio SVGs.** Verovio emits SVGs with fixed pixel dimensions — the `dpi`
  kwarg in `cairosvg.svg2png(dpi=...)` has no effect. Use `scale=dpi/96.0` instead (96 px/in is
  the CSS reference density).
- **Multi-page PDF:** each SVG page is converted to a single-page PDF via cairosvg, then merged
  with pypdf. Single-page scores skip the merge step.
- **MuseScore not installed.** Don't check for or attempt to call any MuseScore CLI command.
- **Schema `oneOf`, not `required`.** The render tools have no `required` list; `musicxml` /
  `musicxml_path` are an `exactly_one` pair. A direct `call_tool` with neither now returns
  `INVALID_PARAMETER` (from `load_score`) rather than `INVALID_INPUT`.
- **Integration tests need the omr-mcp samples.** They read
  `../omr-mcp/test_samples/pdmx_satb_samples/mxl/`; without that folder they fail with
  "Fixture dir not found".

---

## Claude Desktop Config

```json
{
  "mcpServers": {
    "render": {
      "command": "uv",
      "args": ["--directory", "/path/to/render-mcp", "run", "render-mcp"]
    }
  }
}
```

---

## Document Update Policy

When you finish work or reach a milestone, update:
1. `docs/HANDOVER.md` — check off done items, add new gotchas
2. `docs/PLAN.md` — check off phase items, note changed decisions
3. `docs/requirements.md` — update if behaviour changed
4. `docs/architecture.md` — update if implementation changed
