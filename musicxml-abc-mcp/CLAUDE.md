# musicxml-abc-mcp — Claude Code Instructions

## What This Server Does

Converts between MusicXML and ABC notation. ABC is compact and text-based — Claude can read and
edit it directly in its context window, which is impractical with verbose MusicXML.

**Status:** Phase 1 + UX Wave 1 + UX Wave 2 (score references) + UX Wave 3 (`measures`) complete.
233 unit tests pass (`-m "not integration"`) + 4 integration. MCP Apps ABC Workbench server side done (`structuredContent`, output schemas, app-only `get_abc`); the page is not built yet.

---

## Running Tests

```bash
# From this directory
VIRTUAL_ENV= .venv/bin/pytest tests/ -v               # 233 unit tests (integration deselected)
VIRTUAL_ENV= .venv/bin/pytest tests/ -v -m integration # round-trip conversion tests
```

Install dependencies: `uv sync --extra dev` (note: `--extra dev`, not `--group dev`)

---

## Key Files

| File | Purpose |
|------|---------|
| `src/musicxml_abc_mcp/server.py` | MCP tool definitions and handlers |
| `src/musicxml_abc_mcp/presenter.py` | `structuredContent` + output schemas for the ABC Workbench tools |
| `src/musicxml_abc_mcp/abc_store.py` | `AbcStore`: bounded, expiring `abc_id` handles to `musicxml_to_abc` results (no MCP imports) |
| `src/musicxml_abc_mcp/engine.py` | Conversion pipeline + custom ABC serializer (no MCP imports) |
| `src/musicxml_abc_mcp/utils.py` | Input validation helpers |
| `docs/HANDOVER.md` | Status, remaining work, definition of done |
| `docs/PLAN.md` | Architecture decisions and rationale |
| `docs/requirements.md` | Functional/non-functional requirements |
| `docs/architecture.md` | Component diagram and data-flow |

---

## Implemented Tools

| Tool | Description |
|------|-------------|
| `musicxml_to_abc` | MusicXML (`musicxml` text or `musicxml_path`, `.mxl` too) → ABC notation (all parts or one specific part; `measures` [start, end] for a range of printed bars) |
| `abc_to_musicxml` | ABC notation → MusicXML; `return` `auto` (default) / `path` / `inline` — large scores come back as `musicxml_path` + `score_summary` (`WRITES_FILE`) |
| `validate_abc` | Check ABC syntax, return errors/warnings |
| `list_capabilities` | Server metadata and format support |
| `health_check` | MusicXML → ABC → MusicXML round-trip self-test |
| `describe_score` | Shared core tool: title, key, time, tempo, parts (`P1`…), ranges, measures, duration |
| `get_abc` | App-only: the ABC of an earlier `musicxml_to_abc` by `abc_id` (omit for the latest); no paths |

---

## Environment

- **No system dependencies** — pure Python (music21 + custom serializer)
- **Backend:** music21 (parsing + abc_to_musicxml) + custom ABC serializer for MusicXML → ABC
- **MXL fixtures:** `../omr-mcp/test_samples/pdmx_satb_samples/mxl/` (10 SATB files)

---

## Hard Rules

- **Never `pip install`** — use `uv sync --extra dev` or `uv add`
- **`engine.py` must not import from `mcp`** — keeps it unit-testable
- **All tool handlers must be `async def`**
- **All errors** → `{"error": "...", "error_code": "..."}` (codes: `INVALID_INPUT`, `INVALID_PARAMETER`, `PROCESSING_FAILED`)
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

- **music21 9.x has NO ABC write support.** `ConverterABC.registerOutputExtensions = ()` means
  `music21.converter.toData(score, fmt='abc')` fails silently or errors. The engine uses a custom
  ABC serializer that walks music21's note model directly.
- **ABC octave convention (v2.1):** uppercase `C` = C4 (middle C); lowercase `c` = C5.
  `C D E F G A B` = C4–B4; `c d e f g a b` = C5–B5; `c' d'...` = C6+; `C, D,...` = C3–B3.
  music21 parses ABC with the same convention, so the serializer must match it or
  ABC → MusicXML → ABC round-trips drift by an octave.
- **Round-trips are not lossless.** Dynamics, complex articulations, and some ornaments have no
  ABC equivalent. Surface these in the `warnings` field.
- **Score references (Wave 2).** Read scores with `sheet_music_mcp_core.references.load_score`,
  never open a path yourself; return `abc_to_musicxml` through `deliver_score` so inline output
  stays byte-identical. Paths are confined to `SHEET_MUSIC_OUTPUT_ROOT` (default: working
  directory), the client's roots and `SHEET_MUSIC_INPUT_ROOTS`; files are written under
  `<output root>/scores/`. Tests must set `SHEET_MUSIC_OUTPUT_ROOT` to `tmp_path` before a call
  that may write (any ABC giving over 8 KB of MusicXML in `auto` mode).
- **Measure ranges (Wave 3).** `musicxml_to_abc(measures=[start, end])` cuts the MusicXML text
  with core `select_measures` *before* music21 parses it (printed numbers, pickup 0); never filter
  music21 measures by `.number`. The cut score carries its tempo as a bare `<sound tempo>`, which
  music21 reads as a MetronomeMark with only `numberSounding`, so `Q:` falls back to it
  (`_tempo_number`). The serializer has no pickup or bar-number logic, so a cut starting at bar 3
  needs no special case.
- **MCP Apps ABC Workbench.** `musicxml_to_abc` and `abc_to_musicxml` link `ui://abc/workbench`
  only when `musicxml_abc_mcp/ui/assets/abc-workbench.html` is packaged (gitignored, shipped via
  hatch `artifacts`); tests use the `packaged_ui` fixture in `conftest.py`. `content` is pinned by
  `tests/golden/abc_content.json` (`ABC_GOLDEN_UPDATE=1` re-records it; music21's random part ids
  are masked). `structuredContent` never holds a MusicXML score: `abc_to_musicxml` reports
  `{warnings, delivery, musicxml_bytes}`. Every `musicxml_to_abc` success stores its result in
  `server.abc_store` under a fresh `abc_id` (only in `structuredContent`, never `content`); the
  app-only `get_abc` returns it. Tests get a fresh store from an autouse fixture.
- **`X:` header required.** music21's ABC parser requires the tune-number header. It adds it
  automatically on output but may fail to parse input that lacks it.

---

## ABC Quick Reference

Minimal valid ABC:
```
X:1
T:Test Tune
M:4/4
L:1/8
K:G
GABG DEFD | GABc d4 |]
```

Standard: https://abcnotation.com/wiki/abc:standard:v2.1

---

## Claude Desktop Config

```json
{
  "mcpServers": {
    "musicxml-abc": {
      "command": "uv",
      "args": ["--directory", "/path/to/musicxml-abc-mcp", "run", "musicxml-abc-mcp"]
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
