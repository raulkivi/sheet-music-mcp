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
| omr-mcp | ⚠️ Phase 1-4 complete; default (oemer) engine loses SATB voice structure — fixed via opt-in `engine="audiveris"`, not yet the default (see omr-mcp/docs/HANDOVER.md) | 111 unit |
| synth-mcp | ✅ Phase 1 + UX complete | 64 unit + 7 integration |
| render-mcp | ✅ Phase 1 + UX complete | 73/73 incl. integration |
| musicxml-abc-mcp | ✅ Phase 1 + UX complete | 74/74 incl. integration |
| pitch-mcp | ✅ Phase A+B + UX complete (audio-driven position tracking, DTW via dtaidistance) | 112 unit + 4 integration |
| comparer-mcp | ✅ Phase 4 (Advanced features) complete — all originally-scoped phases done | 134/134 (127 unit + 7 integration) |

UX deliverables (all servers): PyPI packaging, `install.sh`, `SETUP.md`, `examples/` client configs, `health_check` tool, `TROUBLESHOOTING.md`. See [docs/SETUP_UX_PLAN.md](docs/SETUP_UX_PLAN.md).

---

## Hard rules (apply to all servers)

- **Never use `pip install`** — always `uv sync` or `uv add`
- **Never share venvs** between servers; each has its own `.venv`
- **`engine.py` must not import from `mcp`** — keeps it unit-testable without the MCP stack
- **All tool handlers must be `async def`**
- **All error responses** must use `{"error": "...", "error_code": "..."}` — see [docs/conventions.md](docs/conventions.md) for the full code list
- **Integration tests** must be marked `@pytest.mark.integration` and must not run in the default `pytest` invocation

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
`server.py` with `Server(name, on_list_tools=_on_list_tools, on_call_tool=_on_call_tool)`.
`_on_call_tool` validates arguments against the tool's `input_schema` and returns exceptions as
`isError` results, which 2.x no longer does itself. Tools needing the request context (progress)
take it as a `ctx` argument; `app.request_context` no longer exists.

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
