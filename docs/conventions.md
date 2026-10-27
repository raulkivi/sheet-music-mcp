# MCP Server Conventions

Shared standards for all MCP servers in this project. Every server must follow these conventions
so they compose cleanly in Phase 2 and are consistent for contributors.

---

## Directory Structure

Each MCP server lives in its own top-level directory and is independently deployable.

```
<name>-mcp/
├── pyproject.toml              # Package config and dependencies
├── README.md                   # Installation, usage, tool reference
├── .python-version             # Pins Python version (3.11)
├── src/
│   └── <name>_mcp/
│       ├── __init__.py
│       ├── server.py           # MCP server entry point, tool registration
│       ├── engine.py           # Core business logic (no MCP dependency)
│       └── utils.py            # Validation, format helpers, shared utilities
├── tests/
│   ├── __init__.py
│   ├── test_server.py          # Tool schema and MCP protocol tests
│   ├── test_engine.py          # Unit tests for engine.py (mocked I/O)
│   ├── test_utils.py           # Unit tests for utils.py
│   └── fixtures/               # Static test data (images, XML files, audio)
│       └── README.md           # Documents what fixtures are available and why
├── test_samples/               # Larger real-world samples (not committed if >10MB)
├── docs/
│   ├── HANDOVER.md             # Status, remaining work, definition of done
│   ├── PLAN.md                 # Architecture decisions and rationale
│   ├── requirements.md         # Functional and non-functional requirements
│   └── architecture.md         # Component diagram and data-flow
└── examples/
    └── claude_desktop_config.json  # Ready-to-use Claude Desktop config snippet
```

### Naming

- Directory: `<name>-mcp/` (kebab-case)
- Python package: `<name>_mcp` (snake_case)
- Entry point command: `<name>-mcp` (matches directory name)

---

## pyproject.toml Template

```toml
[project]
name = "<name>-mcp"
version = "0.1.0"
description = "<One sentence description>"
requires-python = ">=3.11"
dependencies = [
    "jsonschema>=4.20.0",
    "mcp>=2.2.0,<3.0.0",
    # add server-specific dependencies here
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
]

[project.scripts]
<name>-mcp = "<name>_mcp.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

---

## Required Tool: `list_capabilities`

Every MCP server must expose a `list_capabilities` tool. This is the discovery contract between
servers and the orchestration layer (Phase 2 web app).

**Returns:**
```json
{
  "server": "<name>-mcp",
  "version": "0.1.0",
  "input_formats": ["<format>", ...],
  "output_formats": ["<format>", ...],
  "tools": ["tool_name_1", "tool_name_2", "list_capabilities"],
  "backend": "<library or engine name>",
  "backend_version": "<version string>"
}
```

---

## Error Response Format

All tools must return errors in this consistent structure (never raise unhandled exceptions to the
MCP client):

```json
{
  "error": "Human-readable description of what went wrong",
  "error_code": "SCREAMING_SNAKE_CASE_CODE"
}
```

### Standard error codes

| Code | When to use |
|------|-------------|
| `FILE_NOT_FOUND` | Input file path does not exist |
| `UNSUPPORTED_FORMAT` | File extension or MIME type not supported |
| `FILE_TOO_LARGE` | Input exceeds size limit |
| `INVALID_INPUT` | Input is present but malformed (bad XML, corrupt image, etc.) |
| `PROCESSING_FAILED` | Backend engine error during processing |
| `INVALID_PARAMETER` | A tool parameter value is out of range or logically invalid |
| `SESSION_NOT_FOUND` | Referenced session ID does not exist (for stateful tools) |

### Optional fields: `hint` and `choices`

An error may add two optional fields, so the model can recover in one step without a lookup call:

| Field | Type | When to use |
|-------|------|-------------|
| `hint` | string | The fix, written as an instruction: "Re-run with engine='audiveris'", "Scan at 300+ DPI". |
| `choices` | list of strings | The valid values when a parameter did not match: part names, engines. |

```json
{
  "error": "Part 'Sopran' not found",
  "error_code": "INVALID_PARAMETER",
  "hint": "Pass one of the listed part names or IDs",
  "choices": ["Soprano (P1)", "Alto (P2)", "Tenor (P3)", "Bass (P4)"]
}
```

Build errors with `sheet_music_mcp_core.errors.error_payload()` or
`sheet_music_mcp_core.content.error_content()` (see [Shared core library](#shared-core-library)),
never by hand.

---

## Part Selection

Every parameter that names a voice part uses the shared resolver in `sheet_music_mcp_core.parts`.

**Part IDs.** A part's ID is its MusicXML `<score-part id>` (`P1`, `P2`, …), never music21's
`part.id`. music21 replaces `part.id` with the part name, repeats it for same-named parts, and
gives unnamed parts a new integer on every parse. Build the part list with
`music21_part_infos(score.parts)` and select parts **by position** against that list. Staves of one
multi-staff part (a piano) keep music21's staff IDs (`P3-Staff1`, `P3-Staff2`). Report the same IDs
from tools that list parts (`get_parts`).

A requested string is matched in tiers, and the first tier that matches wins:

1. **Exact part ID**, case-sensitive (`P2`).
2. **Part name, abbreviation or ID** after normalising: casefold, strip punctuation, collapse
   spaces, and turn Roman numerals `I`/`II`/`III`/`IV` into `1`/`2`/`3`/`4`. So `"alto ii"`
   matches `Alto 2`, `"q"` matches a part abbreviated `Q.` and `"p2"` matches `P2`.
3. **Voice role**, from the alias table below. A role matches every part whose normalised name is
   one of the role's aliases, optionally followed by a divisi number.

| Role | Aliases (normalised) |
|------|----------------------|
| soprano | `s`, `sop`, `soprano`, `soprani`, `sopran`, `cantus`, `canto`, `tr`, `treble`, `trebles` |
| mezzo-soprano | `ms`, `mez`, `mezzo`, `mezzo soprano`, `mezzosoprano` |
| alto | `a`, `alt`, `alto`, `alti`, `contralto`, `altus` |
| countertenor | `ct`, `countertenor`, `counter tenor`, `countertenors`, `contratenor`, `contra tenor` |
| tenor | `t`, `ten`, `tenor`, `tenori` |
| baritone | `bar`, `bari`, `bariton`, `baritone`, `baritono` |
| bass | `b`, `bas`, `bass`, `bassi`, `basso`, `bassus` |

- Mezzo-soprano, countertenor and baritone are roles of their own: `"Alto"` never selects a mezzo
  or countertenor part, and `"Bass"` never selects a baritone part. Treble is a soprano alias.
- A divisi request (`A1`, `Alto 1`, `Alt I`) matches only that division. A role without a
  number (`Alto`) matches every division (`Alto 1`, `Alto 2`).
- Tools that take several parts call `resolve_parts` and get the IDs in request order, without
  duplicates. Tools that take one part call `resolve_part`, which rejects a request matching
  more than one part.
- No match, or an ambiguous single-part match, returns `INVALID_PARAMETER` with `choices` listing
  `"<name> (<id>)"` for the candidate parts.

### Parameter names

| Meaning | Name | Type |
|---------|------|------|
| One part | `part` | string |
| Several parts | `parts` | array of strings |

Describe them in tool schemas as "part ID, name or voice (e.g. 'P1', 'Soprano', 'S')".

---

## Deprecated Parameter Names

When a parameter is renamed, the old name stays as an alias for **one minor release** and is then
removed. Use `sheet_music_mcp_core.params.aliased`:

- List both names in the schema. Start the old name's description with
  "(Deprecated: use `<new>`)". If the parameter is required, use
  `anyOf: [{"required": ["<new>"]}, {"required": ["<old>"]}]`.
- If only the old name is passed, accept it and log one deprecation warning per process.
- If neither is passed, `make_handlers` reports "one of these parameters is required: '<new>',
  '<old>'" and never echoes the arguments (which would put a whole score into the model's context).
- If both are passed with equal values, accept. If they differ, return `INVALID_PARAMETER`.
- Note the removal in the changelog of the release that removes it.

---

## Tool Annotations and Titles

Every tool sets a human-readable `title` and `annotations` from one of the presets in
`sheet_music_mcp_core.annotations`. Hosts use these to auto-approve read-only tools and to
label tools in their UI. They are hints, not security: path confinement and the no-overwrite
rule still apply.

| Preset | `readOnlyHint` | `destructiveHint` | `idempotentHint` | `openWorldHint` | Use for |
|--------|----------------|-------------------|------------------|-----------------|---------|
| `READ_ONLY` | true | – | – | false | Queries, conversions returned as text, comparisons, `list_capabilities`, `health_check` |
| `READ_ONLY_DOWNLOADS` | true | – | – | true | Read-only tools that may download models or engines on first use |
| `WRITES_FILE` | false | false | false | false | Tools that write an output file (they never overwrite) |
| `WRITES_FILE_DOWNLOADS` | false | false | false | true | The same, with a first-use download |
| `SESSION_STATE` | false | false | false | false | Tools that create, change or end server-side sessions, or open a device |

A tool that opens the microphone or another device is never `READ_ONLY`, so hosts still ask
before using it.

---

## Result Content

- `content[0]` is the JSON text response described in each server's requirements. Never change or
  reorder it. Extra blocks are only appended after it.
- A tool that writes a file appends a `ResourceLink` with a `file://` URI and the file's MIME type,
  using `sheet_music_mcp_core.content.file_link`.
- A tool that writes a PNG appends an `ImageContent` block when the file is at most 1 MB, using
  `sheet_music_mcp_core.content.png_block`. SVG gets no image block.

---

## Server Instructions

Each server passes `instructions` to `Server(...)`: 3–6 lines the client gives the model at
initialize. Use them for routing knowledge the model would otherwise learn only by failing. For
example: which engine suits choir scores, the call order of a stateful flow, and accepted part
formats. Keep `list_capabilities` as the machine-readable discovery contract.

---

## Shared Core Library

`sheet-music-mcp-core` (directory `sheet-music-mcp-core/`, import `sheet_music_mcp_core`) holds the
code every server needs, so it is written and tested once.

| Module | Purpose | Imports `mcp`? |
|--------|---------|----------------|
| `errors` | `ProcessingError` (with optional `hint` and `choices`), `error_payload()` dict | no |
| `parts` | `PartInfo`, `music21_part_infos()`, `resolve_parts()`, `resolve_part()`, `PartSelectionError` (music21 objects are duck-typed, not imported) | no |
| `params` | `aliased()` for deprecated parameter names | no |
| `annotations` | Annotation presets | no |
| `content` | `error_content()`, `processing_error_content()`, `file_link()`, `png_block()` | yes |
| `wiring` | `make_handlers()`: input-schema validation and error results for `Server(...)`; pass the server's own `logger=`. Schema failures (`INVALID_PARAMETER`) and exceptions a tool did not handle (`PROCESSING_FAILED`, or a `ProcessingError`'s own code, hint and choices) come back as `isError` results in the `{error, error_code}` envelope | yes |

- Engines may import only the modules without `mcp`. This keeps `engine.py` free of MCP imports.
- Servers depend on `sheet-music-mcp-core>=X.Y,<X.(Y+1)` while the core is 0.x. For development,
  they point uv at the local copy, which `uv build` leaves out of published wheels:

  ```toml
  [tool.uv.sources]
  sheet-music-mcp-core = { path = "../sheet-music-mcp-core", editable = true }
  ```

- The core is released before any server release that needs a new core version.

---

## Tooling Standards

| Concern | Standard |
|---------|----------|
| Python version | 3.11+ (pin in `.python-version`) |
| Package manager | `uv` — use `uv sync` to install, `uv run pytest` to test |
| MCP transport | `stdio` — local deployment, compatible with Claude Desktop |
| Async | All MCP tool handlers must be `async def` |
| Logging | Use Python `logging` module; logger name = package name |

### Common commands

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest tests/ -v

# Start the server (for manual testing with Claude Desktop)
uv run <name>-mcp
```

---

## Testing Requirements

Each server must have tests in three categories before it is considered complete:

| Category | Location | Coverage required |
|----------|----------|------------------|
| Unit tests | `tests/test_engine.py`, `tests/test_utils.py` | All validation logic, all error paths, metadata extraction |
| Protocol tests | `tests/test_server.py` | Tool schemas, `list_capabilities` response, error propagation |
| Integration tests | `tests/test_engine.py` (marked `@pytest.mark.integration`) | At least one real end-to-end test with a fixture file |

Integration tests should be skipped by default and opt-in via a marker:

```bash
# Unit tests only (default, fast)
uv run pytest tests/ -v

# Include integration tests (slow, requires real backends)
uv run pytest tests/ -v -m integration
```

---

## Separation of Concerns

Keep MCP protocol logic out of the engine:

| File | Responsibility | Must NOT contain |
|------|---------------|-----------------|
| `server.py` | MCP tool definitions, parameter parsing, calling engine, formatting responses | Business logic, file I/O beyond path resolution |
| `engine.py` | Core processing logic (OMR, synthesis, rendering, etc.) | MCP SDK imports |
| `utils.py` | Input validation, format conversion helpers, file size formatting | Business logic |

This separation makes `engine.py` independently testable without any MCP infrastructure.

---

## Claude Desktop Config Snippet

Every server's `examples/claude_desktop_config.json` must use this format:

```json
{
  "mcpServers": {
    "<name>": {
      "command": "uv",
      "args": ["--directory", "/path/to/<name>-mcp", "run", "<name>-mcp"],
      "env": {}
    }
  }
}
```

Users merge this into `~/.config/claude/claude_desktop_config.json`.
