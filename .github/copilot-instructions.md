# Copilot Instructions

## Project Overview

Choir Music Assistant — a collection of independent MCP (Model Context Protocol) servers that
together enable choir singers to digitize, practice with, and navigate sheet music.

See [docs/Intro.md](../docs/Intro.md) for goals, phases, and data flow.
See [docs/conventions.md](../docs/conventions.md) for coding standards all servers must follow.
See [docs/implementation-plan.md](../docs/implementation-plan.md) for the high-level build order.

---

## Working on an MCP Server

Each server has its own local instruction file — **read it before writing any code:**

| Server | Instructions | Status |
|--------|-------------|--------|
| omr-mcp | [omr-mcp/.github/copilot-instructions.md](../omr-mcp/.github/copilot-instructions.md) | ✅ mostly complete |
| synth-mcp | [synth-mcp/.github/copilot-instructions.md](../synth-mcp/.github/copilot-instructions.md) | ✅ Phase 1 COMPLETE |
| render-mcp | [render-mcp/.github/copilot-instructions.md](../render-mcp/.github/copilot-instructions.md) | ✅ Phase 1 COMPLETE |
| musicxml-abc-mcp | [musicxml-abc-mcp/.github/copilot-instructions.md](../musicxml-abc-mcp/.github/copilot-instructions.md) | ✅ Phase 1 COMPLETE |
| pitch-mcp | [pitch-mcp/.github/copilot-instructions.md](../pitch-mcp/.github/copilot-instructions.md) | ✅ Phase A+B COMPLETE |
| comparer-mcp | [comparer-mcp/.github/copilot-instructions.md](../comparer-mcp/.github/copilot-instructions.md) | 🔲 Design complete |

The per-server files contain: status, key files, implemented tools, environment setup, test
commands, known gotchas, and the definition of done.

Also read the server's `docs/HANDOVER.md`, `docs/PLAN.md`, `docs/requirements.md`, and `docs/architecture.md`
before writing any code.

---

## Repository Structure

```
sheet-music-mcp/
├── docs/
│   ├── Intro.md                # Vision, goals, phases, data flow
│   ├── conventions.md          # Shared conventions for all MCP servers
│   ├── implementation-plan.md  # High-level build order and server summaries
│   └── sources.md              # Reference links (ABC notation, etc.)
├── omr-mcp/                    # Image → MusicXML          ✅ mostly complete
├── synth-mcp/                  # MusicXML → Audio          ✅ Phase 1 COMPLETE
├── render-mcp/                 # MusicXML → PDF/PNG        ✅ Phase 1 COMPLETE
├── musicxml-abc-mcp/           # MusicXML ↔ ABC            ✅ Phase 1 COMPLETE
├── pitch-mcp/                  # Mic audio → score pos/accuracy  ✅ Phase A+B COMPLETE
└── comparer-mcp/               # Two MusicXML → structured diff  🔲 Design complete
```

Each `*-mcp/` directory is a self-contained Python package deployable independently.

---

## Shared Standards (all servers)

### Environment

- **Python:** 3.11+ (pinned in `.python-version`)
- **Package manager:** `uv` — always use `uv sync` / `uv add`, never `pip install`
- **Venvs:** each server has its own `.venv` — never share between servers

### Coding rules

- **`engine.py` must not import from `mcp`** — keeps it unit-testable without the MCP stack
- **All tool handlers must be `async def`**
- **All error responses:** `{"error": "...", "error_code": "..."}` — see [docs/conventions.md](../docs/conventions.md) for all codes
- **Integration tests** must be `@pytest.mark.integration` and must not run in the default `pytest` invocation

### MCP stdio startup pattern

```python
async def _run():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

asyncio.run(_run())
```

`run_server()` does not exist in the installed MCP SDK — always use the context manager above.

### Running tests

```bash
# From inside any *-mcp/ directory:
VIRTUAL_ENV= .venv/bin/pytest tests/ -v               # unit tests
VIRTUAL_ENV= .venv/bin/pytest tests/ -v -m integration # integration tests
uv sync                                                # install dependencies
```

---

## When You Finish Work

Update the documents so the next person (or session) starts with accurate information:

- **`<server>/docs/HANDOVER.md`** — check off done items, add new gotchas, update status
- **`<server>/docs/PLAN.md`** — check off completed phase items, note changed decisions
- **`<server>/docs/requirements.md`** — update if behaviour or interfaces changed
- **`<server>/docs/architecture.md`** — update if implementation structure changed
- **`<server>/.github/copilot-instructions.md`** — update status and tool list
- **This file** — update server status markers in the table above
