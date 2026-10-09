# musicxml-abc-mcp — Claude Code Instructions

## What This Server Does

Converts between MusicXML and ABC notation. ABC is compact and text-based — Claude can read and
edit it directly in its context window, which is impractical with verbose MusicXML.

**Status:** Phase 1 complete. 74/74 tests pass including integration.

---

## Running Tests

```bash
# From this directory
VIRTUAL_ENV= .venv/bin/pytest tests/ -v               # 71 unit + integration tests
VIRTUAL_ENV= .venv/bin/pytest tests/ -v -m integration # round-trip conversion tests
```

Install dependencies: `uv sync --extra dev` (note: `--extra dev`, not `--group dev`)

---

## Key Files

| File | Purpose |
|------|---------|
| `src/musicxml_abc_mcp/server.py` | MCP tool definitions and handlers |
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
| `musicxml_to_abc` | MusicXML string → ABC notation (all parts or one specific part) |
| `abc_to_musicxml` | ABC notation → MusicXML string |
| `validate_abc` | Check ABC syntax, return errors/warnings |
| `list_capabilities` | Server metadata and format support |

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
