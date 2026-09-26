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
