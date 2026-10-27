# synth-mcp — Claude Code Instructions

## What This Server Does

Synthesizes audio from a MusicXML score. Callers select voice parts (Soprano, Alto, Tenor, Bass,
or any combination) and an optional tempo factor. Returns a WAV file path.

**Status:** Phase 1 complete. 64 unit + 7 integration tests pass.

---

## Running Tests

```bash
# From this directory
VIRTUAL_ENV= .venv/bin/pytest tests/ -v                          # 64 unit tests (fast)

# Integration tests require a soundfont
VIRTUAL_ENV= SYNTH_SOUNDFONT_PATH=/usr/share/sounds/sf2/TimGM6mb.sf2 \
  .venv/bin/pytest tests/ -v -m integration
```

Synthesis tests **skip automatically** when `SYNTH_SOUNDFONT_PATH` is unset.

Install dependencies: `uv sync`

---

## Key Files

| File | Purpose |
|------|---------|
| `src/synth_mcp/server.py` | MCP tool definitions and handlers |
| `src/synth_mcp/engine.py` | music21 + pyfluidsynth pipeline (no MCP imports) |
| `src/synth_mcp/utils.py` | MusicXML validation, tempo validation, path helpers |
| `docs/HANDOVER.md` | Status, remaining work, definition of done |
| `docs/PLAN.md` | Architecture decisions and rationale |
| `docs/requirements.md` | Functional/non-functional requirements |
| `docs/architecture.md` | Component diagram and data-flow |

---

## Implemented Tools

| Tool | Description |
|------|-------------|
| `get_parts` | Parse MusicXML and return list of parts with IDs and measure counts |
| `synthesize` | Render selected parts to WAV with optional tempo scaling |
| `list_capabilities` | Server metadata, backend, soundfont status |

---

## Environment

- **System soundfonts:** `/usr/share/sounds/sf2/TimGM6mb.sf2` and `default-GM.sf2`
- **libfluidsynth:** `/usr/lib/x86_64-linux-gnu/libfluidsynth.so.3` (installed)
- **Backend:** music21 (MusicXML → MIDI) + pyfluidsynth with `audio.driver=file` (no subprocess)
- **MXL fixtures:** `../omr-mcp/test_samples/pdmx_satb_samples/mxl/` (10 SATB files)

---

## Hard Rules

- **Never `pip install`** — use `uv sync` or `uv add`
- **`engine.py` must not import from `mcp`** — keeps it unit-testable
- **All tool handlers must be `async def`**
- **All errors** → `{"error": "...", "error_code": "..."}` (codes: `FILE_NOT_FOUND`, `INVALID_INPUT`, `PROCESSING_FAILED`, `INVALID_PARAMETER`)
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

- **Never select parts by music21's `part.id`.** music21 replaces it with the part name, repeats
  it for same-named parts and gives unnamed parts a new integer on every parse. Part IDs are the
  MusicXML `<score-part id>` (`"P1"`) from `sheet_music_mcp_core.parts.music21_part_infos`; select
  by position against that list. Callers pass `parts` as IDs, names or voices (`"P1"`, `"Alto"`,
  `"A"`); `part_ids` is a deprecated alias.
- **pyfluidsynth, not CLI.** Use `fluidsynth.Synth` with `audio.driver=file` +
  `fluid_player_join()`. The `fluidsynth` CLI binary is not required.
- **`SYNTH_SOUNDFONT_PATH` must be set for synthesis.** Warn at server startup if missing —
  don't crash, but synthesis calls will fail with a clear error.
- **Running tests:** `VIRTUAL_ENV=` prefix prevents uv from picking up the wrong venv.

---

## Claude Desktop Config

```json
{
  "mcpServers": {
    "synth": {
      "command": "uv",
      "args": ["--directory", "/path/to/synth-mcp", "run", "synth-mcp"],
      "env": {
        "SYNTH_SOUNDFONT_PATH": "/usr/share/sounds/sf2/TimGM6mb.sf2"
      }
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
