# musicxml-abc-mcp

<!-- mcp-name: io.github.raulkivi/musicxml-abc-mcp -->

MCP server that converts between MusicXML and ABC notation.

## What it does

Bridges MusicXML (the standard but verbose XML format) and ABC notation (a compact, human-readable text format). The primary use case is enabling LLM-assisted score editing: MusicXML → ABC → Claude edits → ABC → MusicXML.

ABC is ideal for LLM editing because it is concise enough to fit in a context window and expressive enough to represent most choral music.

## Tools

| Tool | Description |
|------|-------------|
| `musicxml_to_abc` | Convert MusicXML to ABC notation; optionally filter to a single part |
| `abc_to_musicxml` | Convert ABC notation back to MusicXML |
| `validate_abc` | Parse an ABC string and return errors or warnings |
| `list_capabilities` | Return server metadata: backend version, ABC standard |
| `health_check` | Run a MusicXML → ABC → MusicXML round-trip smoke test and report status |

## Installation

```bash
cd musicxml-abc-mcp
uv sync --extra dev
```

Note: use `--extra dev` (not `--group dev`) to install pytest.

For a guided setup (installs `uv` if needed, then syncs dependencies), run `./install.sh` —
see [SETUP.md](SETUP.md) for step-by-step instructions. Ready-made client configs (Claude
Desktop, Cursor, Windsurf, Continue, Zed) are in [examples/](examples/). If something doesn't
work, check [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Running

```bash
uv run musicxml-abc-mcp
```

No environment variables required.

## Usage examples

All tools take and return strings directly (no file paths) — the MCP client is responsible for
reading/writing files if needed.

```json
// Convert full score to ABC
{
  "tool": "musicxml_to_abc",
  "arguments": {"musicxml": "<score-partwise>...</score-partwise>"}
}
// → {"abc": "X:1\nT:...\n...", "parts_included": ["Soprano", "Alto", "Tenor", "Bass"], "warnings": []}

// Extract just the Soprano part
{
  "tool": "musicxml_to_abc",
  "arguments": {"musicxml": "<score-partwise>...</score-partwise>", "part_id": "Soprano"}
}

// Convert edited ABC back to MusicXML
{
  "tool": "abc_to_musicxml",
  "arguments": {"abc": "X:1\nT:My Song\n..."}
}
// → {"musicxml": "<?xml version=\"1.0\"?>...", "warnings": []}

// Validate ABC before converting
{
  "tool": "validate_abc",
  "arguments": {"abc": "X:1\nT:My Song\n..."}
}
```

## ABC notation basics

This server uses ABC standard v2.1:

- `c` (lowercase) = C4 (middle C)
- `C` (uppercase) = C3 (one octave below middle C)
- Apostrophe raises an octave: `c'` = C5
- Comma lowers an octave: `C,` = C2

Round-trips preserve notes within ±2%. Dynamics and complex articulations are not preserved.

## Testing

```bash
# All tests including integration (round-trip SATB conversion)
VIRTUAL_ENV= .venv/bin/pytest tests/ -v
```

## Dependencies

- [music21](https://web.mit.edu/music21/) — score parsing; ABC output uses a custom serializer (music21 9.x has no ABC writer)
- [mcp](https://github.com/modelcontextprotocol/python-sdk) — MCP protocol

## System requirements

- Python 3.11+
- No system libraries required
