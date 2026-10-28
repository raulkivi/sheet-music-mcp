# CLAUDE.md — Choir Music Assistant

Project-level instructions for Claude Code. Read this before doing any work in this repository.

---

## What this project is

Six independent MCP servers for choir practice. Each server lives in its own directory, has its own Python venv, and can be deployed standalone.

| Server | Directory | Input → Output | Goal |
|--------|-----------|----------------|------|
| omr-mcp | `omr-mcp/` | Sheet music image → MusicXML | Digitize scores |
| render-mcp | `render-mcp/` | MusicXML → PDF / PNG | Print / display |
| synth-mcp | `synth-mcp/` | MusicXML + voice → WAV | Practice audio |
| musicxml-abc-mcp | `musicxml-abc-mcp/` | MusicXML ↔ ABC | LLM editing bridge |
| pitch-mcp | `pitch-mcp/` | Mic audio + score → position + accuracy | Sing-along feedback |
| comparer-mcp | `comparer-mcp/` | Two MusicXML → structured diff | Score comparison |

Shared code (errors, part selection, deprecated parameter names, tool annotations, result content,
handler wiring, score paths, `describe_score`, measure ranges, MCP Apps UI resources and artifact handles) lives in the library [`sheet-music-mcp-core/`](sheet-music-mcp-core/), which every
server depends on. It is not an MCP server; its tests run from its own directory like a server's.

See [README.md](README.md) for the full vision and data flow.

---

## Working on a specific server

**Each server has its own local instruction files — read these first:**

| Server | Claude Code | Copilot |
|--------|-------------|---------|
| omr-mcp | [omr-mcp/CLAUDE.md](omr-mcp/CLAUDE.md) | [omr-mcp/.github/copilot-instructions.md](omr-mcp/.github/copilot-instructions.md) |
| synth-mcp | [synth-mcp/CLAUDE.md](synth-mcp/CLAUDE.md) | [synth-mcp/.github/copilot-instructions.md](synth-mcp/.github/copilot-instructions.md) |
| comparer-mcp | [comparer-mcp/CLAUDE.md](comparer-mcp/CLAUDE.md) | [comparer-mcp/.github/copilot-instructions.md](comparer-mcp/.github/copilot-instructions.md) |
| render-mcp | [render-mcp/CLAUDE.md](render-mcp/CLAUDE.md) | [render-mcp/.github/copilot-instructions.md](render-mcp/.github/copilot-instructions.md) |
| musicxml-abc-mcp | [musicxml-abc-mcp/CLAUDE.md](musicxml-abc-mcp/CLAUDE.md) | [musicxml-abc-mcp/.github/copilot-instructions.md](musicxml-abc-mcp/.github/copilot-instructions.md) |
| pitch-mcp | [pitch-mcp/CLAUDE.md](pitch-mcp/CLAUDE.md) | [pitch-mcp/.github/copilot-instructions.md](pitch-mcp/.github/copilot-instructions.md) |

Also read the server's `docs/HANDOVER.md`, `docs/PLAN.md`, `docs/requirements.md`, and `docs/architecture.md`
before writing any code.

---

## Server status

| Server | Status | Tests |
|--------|--------|-------|
| omr-mcp | ⚠️ Phase 1-4 complete; default (oemer) engine loses SATB voice structure — fixed via opt-in `engine="audiveris"`, not yet the default (see omr-mcp/docs/HANDOVER.md) | 267 unit (+89 skipped) + 41 integration; MCP Apps Recognition Review server side done (`structuredContent`, app-only `get_recognized_score` / `get_source_preview`), page not built yet |
| synth-mcp | ✅ Phase 1 + UX complete; MCP Apps Practice Player server side done (`structuredContent`, app-only `read_audio_chunk` / `get_score_xml`), page not built yet | 380 unit + 10 integration |
| render-mcp | ✅ Phase 1 + UX complete; MCP Apps spike 0c (Score Viewer, app-only `render_page_svg`) awaiting manual host checks | 234 unit + 12 integration |
| musicxml-abc-mcp | ✅ Phase 1 + UX complete | 161 unit + 4 integration |
| pitch-mcp | ✅ Phase A+B + UX complete (audio-driven position tracking, DTW via dtaidistance); MCP Apps Practice Coach server side done (`structuredContent`, app-only `get_score_for_session`), page not built yet | 331 unit (+6 skipped) + 4 integration |
| comparer-mcp | ✅ Phase 4 (Advanced features) complete — all originally-scoped phases done; MCP Apps Diff Viewer server side done (`structuredContent`, output schemas), page not built yet | 314 unit + 7 integration |

| sheet-music-mcp-core | ✅ 0.3.1 shared library: Wave 1 helpers, score references (`paths`, `scores`, `references`), measure ranges (`measures`), MCP Apps UI resources and app-only tool visibility (`ui`, `wiring`) and opaque artifact handles read in chunks (`artifacts`). Not yet on PyPI — publish before the next server release | 566 unit |

Unit counts are the default `pytest` run (`-m "not integration"`). UX Wave 1 (all servers): tool titles
and annotations, server instructions, part selection by ID/name/voice, inline PNG and file links,
pitch idle timeout, Audiveris pre-check — see [docs/research/ux-wave1-plan.md](docs/research/ux-wave1-plan.md).
UX Wave 2 (all servers): score references — `musicxml_path` inputs (`.mxl` too) confined to the read
roots, `return: auto|path|inline` on score producers, and the shared `describe_score` tool — see
[docs/research/ux-wave2-plan.md](docs/research/ux-wave2-plan.md).
UX Wave 3 (practice): `measures: [start, end]` (printed bar numbers) on render, synth, abc and pitch
(comparer's `measure_range` renamed); synth learning tracks (`part_gains`, `preset`, `focus_part`),
`repeat`, count-in/metronome, `timbre` and the `starting_pitches` tool; pitch `start_practice` and
plain-language `highlights` — see [docs/research/ux-wave3-plan.md](docs/research/ux-wave3-plan.md).

UX deliverables (all servers): PyPI packaging, `install.sh`, `SETUP.md`, `examples/` client configs, `health_check` tool, `TROUBLESHOOTING.md`. See [docs/SETUP_UX_PLAN.md](docs/SETUP_UX_PLAN.md).

---

## Hard rules (apply to all servers)

- **Never use `pip install`** — always `uv sync` or `uv add`
- **Never share venvs** between servers; each has its own `.venv`
- **`engine.py` must not import from `mcp`** — keeps it unit-testable without the MCP stack
- **All tool handlers must be `async def`**
- **All error responses** must use `{"error": "...", "error_code": "..."}` — see [docs/conventions.md](docs/conventions.md) for the full code list
- **Integration tests** must be marked `@pytest.mark.integration` and must not run in the default `pytest` invocation
- **Shared code lives in `sheet-music-mcp-core/`**. Use it for errors, part selection, deprecated parameter names, tool annotations, result content and handler wiring; don't copy that code into a server. Engines may import only its MCP-free modules (`errors`, `parts`, `params`, `annotations`, `paths`, `scores`, `measures`, `artifacts`). See [docs/conventions.md](docs/conventions.md#shared-core-library)
- **Every tool** sets a `title` and an annotation preset; **every part parameter** uses the shared resolver (see [docs/conventions.md](docs/conventions.md#part-selection))
- **Every score input** has a path sibling (`musicxml` / `musicxml_path`, exactly one required) loaded with `references.load_score()`; never open a score path yourself. Score producers take `return: auto|path|inline` via `references.deliver_score()` (see [docs/conventions.md](docs/conventions.md#score-references))

---

## Running tests

From inside each `*-mcp/` directory:

```bash
# Unit tests (fast, no external dependencies)
VIRTUAL_ENV= .venv/bin/pytest tests/ -v

# Integration tests
VIRTUAL_ENV= .venv/bin/pytest tests/ -v -m integration

# synth-mcp integration (needs soundfont)
VIRTUAL_ENV= SYNTH_SOUNDFONT_PATH=/usr/share/sounds/sf2/TimGM6mb.sf2 \
  .venv/bin/pytest tests/ -v -m integration

# pitch-mcp manual tests (real microphone, skip in CI)
VIRTUAL_ENV= .venv/bin/pytest tests/ -v -m manual
```

Install dev dependencies: `uv sync` (or `uv sync --extra dev` for musicxml-abc-mcp).

---

## MCP stdio pattern (applies to all servers)

Use `mcp.server.stdio.stdio_server()` — `run_server()` does not exist in the current SDK:

```python
async def _run():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

asyncio.run(_run())
```

mcp 2.x has no `@app.list_tools()`/`@app.call_tool()` decorators. Wire the handlers at the end of
`server.py` with the shared helper, which validates arguments against the tool's `input_schema` and
returns validation failures and unhandled exceptions as `isError` results in the
`{"error", "error_code"}` envelope (2.x no longer does either itself):

```python
from sheet_music_mcp_core.wiring import make_handlers

_on_list_tools, _on_call_tool = make_handlers(list_tools, call_tool, logger=logger)
app = Server(name, on_list_tools=_on_list_tools, on_call_tool=_on_call_tool)
```

Tools needing the request context (progress) take it as a `ctx` argument; pass
`pass_context=True` (as omr-mcp does). `app.request_context` no longer exists.

---

## System libraries (already installed on this machine)

| Library | Path | Used by |
|---------|------|---------|
| `libfluidsynth.so.3` | `/usr/lib/x86_64-linux-gnu/` | synth-mcp |
| `libcairo.so.2` | system-wide | render-mcp |
| `libportaudio2` | system-wide | pitch-mcp (real-time) |

Soundfonts available at `/usr/share/sounds/sf2/` — `TimGM6mb.sf2` and `default-GM.sf2`.

---

## Document update policy

When you finish work or reach a milestone, update:

1. `<server>/docs/HANDOVER.md` — check off done items, add new gotchas
2. `<server>/docs/PLAN.md` — check off phase items, note any changed decisions
3. `<server>/docs/requirements.md` — update if behaviour or interfaces changed
4. `<server>/docs/architecture.md` — update diagrams/algorithms if implementation changed
5. `.github/copilot-instructions.md` — update status markers
6. This file (`CLAUDE.md`) — update status table if needed
