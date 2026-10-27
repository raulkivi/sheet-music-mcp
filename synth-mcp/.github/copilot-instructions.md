# synth-mcp — Copilot Instructions

## What This Server Does

Synthesizes audio from a MusicXML score. Callers select voice parts (Soprano, Alto, Tenor, Bass,
or any combination) and an optional tempo factor. Returns a path to a rendered WAV file.

**Status:** Phase 1 complete. 64 unit + 7 integration tests pass.

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
synth-mcp/
├── pyproject.toml
├── .python-version          # "llm311"
├── src/synth_mcp/
│   ├── server.py            # MCP tool definitions and async handlers
│   ├── engine.py            # music21 + pyfluidsynth pipeline — NO mcp imports
│   └── utils.py             # MusicXML validation, tempo validation, path helpers
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
| `get_parts` | Parse MusicXML → list of parts with IDs, names, measure counts |
| `synthesize` | Render selected parts to WAV with optional tempo scaling |
| `list_capabilities` | Server metadata, backend, soundfont path status |

---

## Environment

- **System soundfonts:** `/usr/share/sounds/sf2/TimGM6mb.sf2` and `default-GM.sf2`
- **libfluidsynth:** `/usr/lib/x86_64-linux-gnu/libfluidsynth.so.3` (installed)
- **Backend:** music21 (MusicXML → MIDI) + pyfluidsynth with `audio.driver=file` (no subprocess)
- Synthesis tests skip automatically when `SYNTH_SOUNDFONT_PATH` env var is unset

---

## Coding Standards

- **Package manager:** `uv` only — never `pip install`
- **`engine.py` must not import from `mcp`** — keeps it independently unit-testable
- **All tool handlers must be `async def`**
- **All error responses:** `{"error": "human description", "error_code": "SCREAMING_SNAKE"}`
- **Standard error codes:** `FILE_NOT_FOUND`, `INVALID_INPUT`, `PROCESSING_FAILED`, `INVALID_PARAMETER`
- **Integration tests** must be `@pytest.mark.integration` — not run in the default `pytest` invocation
- **Python 3.11+**; `asyncio_mode = "auto"` in pytest config

---

## Running Tests

```bash
# Unit tests (fast, default)
VIRTUAL_ENV= .venv/bin/pytest tests/ -v

# Integration tests (needs soundfont)
VIRTUAL_ENV= SYNTH_SOUNDFONT_PATH=/usr/share/sounds/sf2/TimGM6mb.sf2 \
  .venv/bin/pytest tests/ -v -m integration

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

- **Never select parts by music21's `part.id`.** music21 replaces it with the part name, repeats
  it for same-named parts and gives unnamed parts a new integer on every parse. Part IDs are the
  MusicXML `<score-part id>` (`"P1"`) from `sheet_music_mcp_core.parts.music21_part_infos`; select
  by position against that list. Callers pass `parts` as IDs, names or voices (`"P1"`, `"Alto"`,
  `"A"`); `part_ids` is a deprecated alias.
- **pyfluidsynth, not CLI.** Use `fluidsynth.Synth` with `audio.driver=file` +
  `fluid_player_join()` to render MIDI → WAV. The `fluidsynth` CLI binary is not needed.
- **`SYNTH_SOUNDFONT_PATH` must be set for synthesis.** Warn at startup if missing — don't crash.
- **`tempo_factor` changes MIDI tempo, not audio pitch** — this is correct behaviour.

---

## When You Finish Work

Update these documents so the next session starts with accurate information:
- **`docs/HANDOVER.md`** — check off done items, add new gotchas, update status
- **`docs/PLAN.md`** — check off completed phase items, note changed decisions
- **`docs/requirements.md`** — update if behaviour or interfaces changed
- **`docs/architecture.md`** — update if implementation structure changed
