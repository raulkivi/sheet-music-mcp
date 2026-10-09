# musicxml-abc-mcp — Copilot Instructions

## What This Server Does

Converts between MusicXML and ABC notation. ABC is compact and text-based, making it practical
for Claude to read and edit scores directly in its context window.

**Status:** Phase 1 complete. 74/74 tests pass including integration tests.

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
musicxml-abc-mcp/
├── pyproject.toml
├── .python-version          # "llm311"
├── src/musicxml_abc_mcp/
│   ├── server.py            # MCP tool definitions and async handlers
│   ├── engine.py            # Conversion pipeline + custom ABC serializer — NO mcp imports
│   └── utils.py             # Input validation helpers
├── tests/
│   ├── test_server.py       # protocol tests
│   ├── test_engine.py       # unit + integration tests
│   ├── test_utils.py        # unit tests
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
| `musicxml_to_abc` | MusicXML string → ABC notation (all parts or one specific part) |
| `abc_to_musicxml` | ABC notation → MusicXML string |
| `validate_abc` | Validate ABC syntax, return `valid`, `errors`, `warnings` |
| `list_capabilities` | Server metadata and format support |

---

## Environment

- **No system dependencies** — pure Python
- **Backend:** music21 (parsing + abc_to_musicxml) + custom ABC serializer in `engine.py`
  (music21 9.x has no ABC write support — the serializer walks music21's note model directly)

---

## Coding Standards

- **Package manager:** `uv` only; install dev deps with `uv sync --extra dev` (not `--group dev`)
- **`engine.py` must not import from `mcp`** — keeps it independently unit-testable
- **All tool handlers must be `async def`**
- **All error responses:** `{"error": "human description", "error_code": "SCREAMING_SNAKE"}`
- **Standard error codes:** `INVALID_INPUT`, `INVALID_PARAMETER`, `PROCESSING_FAILED`
- **Integration tests** must be `@pytest.mark.integration` — not run in the default `pytest` invocation
- **Python 3.11+**; `asyncio_mode = "auto"` in pytest config

---

## Running Tests

```bash
# All tests including integration
VIRTUAL_ENV= .venv/bin/pytest tests/ -v

# Install dependencies (note --extra dev, not --group dev)
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

---

## Known Gotchas

- **music21 9.x has NO ABC write support.** `ConverterABC.registerOutputExtensions = ()`.
  `engine.py` uses a custom serializer that walks music21's note model directly — do not replace
  this with a call to `music21.converter.toData(score, fmt='abc')`.
- **ABC octave convention (v2.1):** uppercase `C` = C4 (middle C); lowercase `c` = C5.
  Notes with octave marks: `c'` = C6, `C,` = C3. music21 parses ABC the same way.
- **Round-trips are not lossless.** Dynamics, complex articulations, and some ornaments have no
  ABC equivalent. Surface these in the `warnings` field of responses.
- **`X:` header required** in ABC. music21 adds it automatically on output but may reject input
  that lacks it.
- **Minimal valid ABC:**
  ```
  X:1
  T:Title
  M:4/4
  L:1/8
  K:G
  GABG DEFD | GABc d4 |]
  ```

---

## When You Finish Work

Update these documents so the next session starts with accurate information:
- **`docs/HANDOVER.md`** — check off done items, add new gotchas, update status
- **`docs/PLAN.md`** — check off completed phase items, note changed decisions
- **`docs/requirements.md`** — update if behaviour or interfaces changed
- **`docs/architecture.md`** — update if implementation structure changed
