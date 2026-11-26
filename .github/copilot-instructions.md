# Copilot Instructions

**Last changed:** 2026-11-26 · **Source:** https://github.com/raulkivi/sheet-music-mcp

## Project Overview

Choir Music Assistant — a collection of independent MCP (Model Context Protocol) servers that
together enable choir singers to digitize, practice with, and navigate sheet music.

See [README.md](../README.md) for goals, phases, and data flow.
See [docs/conventions.md](../docs/conventions.md) for coding standards all servers must follow.

---

## Working on an MCP Server

Each server has its own local instruction file — **read it before writing any code:**

| Server | Instructions | Status |
|--------|-------------|--------|
| omr-mcp | [omr-mcp/.github/copilot-instructions.md](../omr-mcp/.github/copilot-instructions.md) | ✅ Phase 1-4 complete; Recognition Review page built |
| synth-mcp | [synth-mcp/.github/copilot-instructions.md](../synth-mcp/.github/copilot-instructions.md) | ✅ Phase 1 COMPLETE; Practice Player page built |
| render-mcp | [render-mcp/.github/copilot-instructions.md](../render-mcp/.github/copilot-instructions.md) | ✅ Phase 1 COMPLETE; Score Viewer page built |
| musicxml-abc-mcp | [musicxml-abc-mcp/.github/copilot-instructions.md](../musicxml-abc-mcp/.github/copilot-instructions.md) | ✅ Phase 1 COMPLETE; ABC Workbench page built |
| pitch-mcp | [pitch-mcp/.github/copilot-instructions.md](../pitch-mcp/.github/copilot-instructions.md) | ✅ Phase A+B COMPLETE; Practice Coach page built |
| comparer-mcp | [comparer-mcp/.github/copilot-instructions.md](../comparer-mcp/.github/copilot-instructions.md) | ✅ Phase 4 COMPLETE; `compare_scores`; Diff Viewer page built |

The per-server files contain: status, key files, implemented tools, environment setup, test
commands, known gotchas, and the definition of done.

Also read the server's `docs/HANDOVER.md`, `docs/PLAN.md`, `docs/requirements.md`, and `docs/architecture.md` (HANDOVER.md and PLAN.md are local and gitignored; pitch-mcp also has `docs/todo.md`)
before writing any code.

---

## Repository Structure

```
sheet-music-mcp/
├── docs/
│   ├── conventions.md          # Shared conventions for all MCP servers
│   └── sources.md              # Reference links (ABC notation, etc.)
├── omr-mcp/                    # Image → MusicXML          ✅ Phase 1-4 complete
├── synth-mcp/                  # MusicXML → Audio          ✅ Phase 1 COMPLETE
├── render-mcp/                 # MusicXML → PDF/PNG        ✅ Phase 1 COMPLETE
├── musicxml-abc-mcp/           # MusicXML ↔ ABC            ✅ Phase 1 COMPLETE
├── pitch-mcp/                  # Mic audio → score pos/accuracy  ✅ Phase A+B COMPLETE
├── comparer-mcp/               # Two MusicXML → structured diff  ✅ Phase 4 COMPLETE
├── ui/                         # MCP Apps UI workspace (TypeScript): seven pages (Score Viewer, Setup Doctor, Diff Viewer, Practice Coach, ABC Workbench, Practice Player, Recognition Review), registry `ui/apps.config.mjs`, built into the servers
└── sheet-music-mcp-core/       # Shared library (errors, parts, annotations, content, wiring, score references, measures) — not a server
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
- **Shared code** (errors, part selection, deprecated parameter names, tool annotations, result content, handler wiring, score references, `describe_score`, measure ranges) comes from `sheet-music-mcp-core/`, not from per-server copies. Engines may import only its MCP-free modules
- **Every tool** sets a `title` and an annotation preset; **every part parameter** (`part` / `parts`) uses the shared resolver. See [docs/conventions.md](../docs/conventions.md)
- **Every score input** has a path sibling (`musicxml_path`, exactly one of the pair required) read through `references.load_score()`; score producers return a path plus `score_summary` for large scores. See [docs/conventions.md](../docs/conventions.md#score-references)

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

- **`<server>/docs/HANDOVER.md`** — check off done items, add new gotchas, update status (local, gitignored)
- **`<server>/docs/PLAN.md`** — check off completed phase items, note changed decisions (local, gitignored)
- **`<server>/docs/requirements.md`** — update if behavior or interfaces changed
- **`<server>/docs/architecture.md`** — update if implementation structure changed
- **`<server>/.github/copilot-instructions.md`** — update status and tool list
- **This file** — update server status markers in the table above
