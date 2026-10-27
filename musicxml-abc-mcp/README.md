# musicxml-abc-mcp

<!-- mcp-name: io.github.raulkivi/musicxml-abc-mcp -->

MCP server that converts between MusicXML and ABC notation.

## What it does

Bridges MusicXML (the standard but verbose XML format) and ABC notation (a compact, human-readable text format). The primary use case is enabling LLM-assisted score editing: MusicXML → ABC → Claude edits → ABC → MusicXML.

ABC is ideal for LLM editing because it is concise enough to fit in a context window and expressive enough to represent most choral music.

## Tools

| Tool | Description |
|------|-------------|
| `musicxml_to_abc` | Convert MusicXML (`musicxml` text or `musicxml_path`) to ABC notation; optionally filter to a single part and a range of printed bars (`measures`) |
| `abc_to_musicxml` | Convert ABC notation back to MusicXML; large scores are written to a file (`return`: `auto` / `path` / `inline`) |
| `validate_abc` | Parse an ABC string and return errors or warnings |
| `list_capabilities` | Return server metadata: backend version, ABC standard |
| `health_check` | Run a MusicXML → ABC → MusicXML round-trip smoke test and report status |
| `describe_score` | Summarize a score cheaply: parts (IDs `P1`…), key, time, tempo, ranges, measures |

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

No environment variables required. Optional: `SHEET_MUSIC_OUTPUT_ROOT` (where large scores are
written and paths are read; default the working directory), `SHEET_MUSIC_INPUT_ROOTS` (extra
folders to read scores from) and `SHEET_MUSIC_INLINE_MAX_BYTES` (default 8192). See
[Score References](../docs/conventions.md#score-references).

## Usage examples

Scores can be passed as text (`musicxml`) or as a file path (`musicxml_path`: `.musicxml`, `.xml`
or `.mxl` inside the allowed folders). `abc_to_musicxml` returns small scores as text and writes
large ones to `<output root>/scores/`, returning `musicxml_path` plus a short `score_summary`;
pass `"return": "inline"` to always get the text.

```json
// Convert full score to ABC
{
  "tool": "musicxml_to_abc",
  "arguments": {"musicxml": "<score-partwise>...</score-partwise>"}
}
// → {"abc": "X:1\nT:...\n...", "parts_included": ["P1", "P2", "P3", "P4"], "warnings": []}

// Extract just the Soprano part
{
  "tool": "musicxml_to_abc",
  "arguments": {"musicxml": "<score-partwise>...</score-partwise>", "part": "Soprano"}
}
// `part` takes a part ID ("P1"), name ("soprano", any case) or voice ("S"); an unknown part
// returns the valid choices. `part_id` is a deprecated alias for one minor release.

// Just bars 17–24 of the Alto part
{
  "tool": "musicxml_to_abc",
  "arguments": {"musicxml_path": "scores/anthem.musicxml", "part": "Alto", "measures": [17, 24]}
}
// `measures` are the printed bar numbers, inclusive (a pickup bar is 0). The ABC headers (K:, M:,
// Q:) are the key, time and tempo in force at bar 17. A range outside the score returns
// INVALID_PARAMETER with a hint such as "This score has measures 1–32."

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

- `C` (uppercase) = C4 (middle C)
- `c` (lowercase) = C5 (one octave above middle C)
- Apostrophe raises an octave: `c'` = C6
- Comma lowers an octave: `C,` = C3

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
