# synth-mcp

<!-- mcp-name: io.github.raulkivi/synth-mcp -->

MCP server that synthesizes audio from MusicXML. Supports voice part selection (Soprano, Alto, Tenor, Bass) and tempo control.

## What it does

Takes a MusicXML score, optionally filters to one or more voice parts, and renders a WAV audio file using FluidSynth. Useful for choir singers who want to practice a specific voice part.

## Tools

| Tool | Description |
|------|-------------|
| `get_parts` | List all voice parts in a score — returns part name, ID, and measure count |
| `synthesize` | Render the score (or selected parts) to a WAV file, with optional tempo adjustment |
| `list_capabilities` | Return server metadata: backend version, soundfont status, FluidSynth availability |
| `health_check` | Check that the soundfont, FluidSynth, and music21 are all available and ready |

## Installation

```bash
cd synth-mcp
uv sync
```

System library required:

```bash
# Ubuntu / Debian
sudo apt install libfluidsynth-dev

# macOS
brew install fluid-synth
```

A soundfont (SF2) file is also required. Free options:

| Soundfont | Size | Notes |
|-----------|------|-------|
| TimGM6mb | ~6 MB | Ships with Ubuntu (`/usr/share/sounds/sf2/TimGM6mb.sf2`) |
| MuseScore General | ~200 MB | Better quality; download from musescore.org |
| GeneralUser GS | ~30 MB | Download from schristiancollins.com |

### Quick install

Prefer not to do the above by hand? Run `./install.sh` — it installs `uv`, the system
`libfluidsynth` package, and a soundfont automatically. See [SETUP.md](SETUP.md) for a
non-technical walkthrough, and [TROUBLESHOOTING.md](TROUBLESHOOTING.md) if something goes wrong.
Ready-made client configs (Claude Desktop, Cursor, Windsurf, Continue, Zed) are in
[`examples/`](examples/).

## Running

```bash
SYNTH_SOUNDFONT_PATH=/usr/share/sounds/sf2/TimGM6mb.sf2 uv run synth-mcp
```

## Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `SYNTH_SOUNDFONT_PATH` | Yes | Path to an SF2 soundfont file |

## Claude Desktop configuration

```json
{
  "mcpServers": {
    "synth": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/synth-mcp", "run", "synth-mcp"],
      "env": {
        "SYNTH_SOUNDFONT_PATH": "/absolute/path/to/soundfont.sf2"
      }
    }
  }
}
```

## Usage examples

```json
// List parts in a score
{"tool": "get_parts", "arguments": {"musicxml": "<score-partwise>...</score-partwise>"}}

// Synthesize the full score
{
  "tool": "synthesize",
  "arguments": {
    "musicxml": "<score-partwise>...</score-partwise>",
    "output_path": "/tmp/full.wav"
  }
}

// Synthesize Soprano part only at 80% tempo
{
  "tool": "synthesize",
  "arguments": {
    "musicxml": "<score-partwise>...</score-partwise>",
    "output_path": "/tmp/soprano.wav",
    "part_ids": ["Soprano"],
    "tempo_factor": 0.8
  }
}
```

Note: `part_ids` are the part **names** returned by `get_parts` (e.g. `"Soprano"`, `"Alto"`),
not XML `<part id>`-style values like `"P1"` — music21 uses the part name as its `id`.

`tempo_factor` range: 0.25–4.0. Values below 1.0 slow down; above 1.0 speed up. Does not affect pitch.

## Testing

```bash
# Unit tests (no soundfont required)
VIRTUAL_ENV= .venv/bin/pytest tests/ -v

# Integration tests (synthesizes real audio)
VIRTUAL_ENV= SYNTH_SOUNDFONT_PATH=/usr/share/sounds/sf2/TimGM6mb.sf2 \
  .venv/bin/pytest tests/ -v -m integration
```

## Dependencies

- [music21](https://web.mit.edu/music21/) — score parsing and MIDI export
- [pyfluidsynth](https://github.com/nwhitehead/pyfluidsynth) — Python bindings for FluidSynth
- [mcp](https://github.com/modelcontextprotocol/python-sdk) — MCP protocol

## Known limitations

- music21's MIDI export may drop some articulations and dynamics
- Audio output is always WAV; convert with `ffmpeg -i out.wav out.mp3` if needed
- Large scores (100+ measures) may take several seconds to synthesize

## System requirements

- Python 3.11+
- `libfluidsynth` shared library (`libfluidsynth.so.3` on Linux)
- An SF2 soundfont file
