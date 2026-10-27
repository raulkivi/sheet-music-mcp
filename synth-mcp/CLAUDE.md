# synth-mcp — Claude Code Instructions

## What This Server Does

Synthesizes audio from a MusicXML score. Callers select voice parts (Soprano, Alto, Tenor, Bass,
or any combination) and an optional tempo factor. Returns a WAV file path.

**Status:** Phase 1 + UX Wave 1 + UX Wave 2 (score references: `musicxml_path`, `describe_score`)
+ UX Wave 3 (practice tracks: `measures`, `repeat`, count-in/metronome, `timbre`, part gains and
presets; new `starting_pitches` tool) complete. 302 unit + 10 integration tests (integration needs
a soundfont, libfluidsynth and, for most, the omr-mcp MXL fixtures).

---

## Running Tests

```bash
# From this directory
VIRTUAL_ENV= .venv/bin/pytest tests/ -v                          # 302 unit tests (fast)

# Integration tests require a soundfont
VIRTUAL_ENV= SYNTH_SOUNDFONT_PATH=/usr/share/sounds/sf2/TimGM6mb.sf2 \
  .venv/bin/pytest tests/ -v -m integration
```

Synthesis tests **skip automatically** when `SYNTH_SOUNDFONT_PATH` is unset.

Install dependencies: `uv sync --extra dev`

---

## Key Files

| File | Purpose |
|------|---------|
| `src/synth_mcp/server.py` | MCP tool definitions and handlers |
| `src/synth_mcp/engine.py` | music21 + pyfluidsynth pipeline (no MCP imports) |
| `src/synth_mcp/practice.py` | Practice-track steps: gains, repeat, clicks, timbre, MIDI post-processing (no MCP imports) |
| `src/synth_mcp/clip.py` | `starting_pitches`: text, clip MIDI, render + downmix to mono 16 kHz (no MCP imports) |
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
| `synthesize` | Render selected parts to WAV with optional tempo scaling and practice options: `measures`, `repeat`, `count_in_bars`, `metronome`, `timbre`, `part_gains` / `preset` / `focus_part` |
| `starting_pitches` | Each part's first note as text (`"S: D5, A: A4, …"`) plus a short piano WAV (inline when ≤ 200 KB); text only, not an error, without a soundfont |
| `describe_score` | Shared core tool: title, key, time, tempo, parts (ID, clef, range), measures, duration — no music21 |
| `list_capabilities` | Server metadata, backend, soundfont status |
| `health_check` | Soundfont, FluidSynth and music21 readiness |

`get_parts`, `synthesize`, `starting_pitches` and `describe_score` take the score as `musicxml` (inline text) **or**
`musicxml_path` (`.musicxml`, `.xml`, `.mxl`), exactly one (`oneOf`). Paths are read with
`sheet_music_mcp_core.references.load_score` (read roots: `SHEET_MUSIC_OUTPUT_ROOT`, client MCP
roots, `SHEET_MUSIC_INPUT_ROOTS`); never open a score path yourself.

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
- **Score paths go through the core.** `call_tool(name, arguments, ctx=None)` calls
  `load_score(arguments, ctx)` first, then the unchanged inline validation and engine calls, so a
  path call gives the same `content[0]` as the inline call. `make_handlers(..., pass_context=True)`
  supplies `ctx` for the client's roots; direct test calls pass none.
- **`confine_output_path` lives in the core.** `utils.confine_output_path` is a re-export of
  `sheet_music_mcp_core.paths.confine_output_path` (raises `PathPolicyError`, also a `ValueError`).
- **`output_path` accepts `.mid` / `.midi` but always writes WAV** (known gap, not yet fixed).
- **Install the dev extra:** plain `uv sync` removes pytest; use `uv sync --extra dev`.
- **Practice options are no-ops at their defaults** (DoD-1). `call_tool` passes only the practice
  options the caller gave to `extract_midi`; with none, the MIDI is byte-identical to before.
  Test practice features at MIDI level (`tests/midi_helpers.py` reads bytes back with
  `music21.midi.MidiFile`), never with FluidSynth.
- **music21 shares a MIDI channel between parts with the same instrument** (channels are keyed by
  program), so CC7 gains need `tune_midi` to give each melodic part its own channel (max 15).
- **music21's conductor track keeps tempo/time marks only in ascending offset order, first part
  first.** The count-in's meter and tempo therefore go at offset 0 of the first part, not in the
  click part; the click part is appended last so it is the last MIDI track.
- **A bare `<sound tempo>` is `numberSounding`, not `number`.** `select_measures` carries the tempo
  that way; music21's MIDI export prefers `numberSounding`, so `scale_tempo` scales both.
- **`starting_pitches` without audio is not an error.** Any `ProcessingError` from `render_clip`
  (no soundfont, no FluidSynth, render failure) becomes `"audio_unavailable"`; the
  `audio/starting-pitches-*.wav` path is only created after rendering worked. Tests patch
  `synth_mcp.clip.synthesize_midi`.
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
