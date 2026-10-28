# synth-mcp

<!-- mcp-name: io.github.raulkivi/synth-mcp -->

MCP server that synthesizes audio from MusicXML. Supports voice part selection (Soprano, Alto, Tenor, Bass) and tempo control.

## What it does

Takes a MusicXML score, optionally filters to one or more voice parts, and renders a WAV audio file using FluidSynth. Useful for choir singers who want to practice a specific voice part.

## Tools

| Tool | Description |
|------|-------------|
| `get_parts` | List all voice parts in a score — returns part name, ID, and measure count |
| `synthesize` | Render the score (or selected parts) to a WAV file, with optional tempo adjustment and practice options (bars, repeats, count-in, metronome, timbre, part volumes) |
| `starting_pitches` | Each part's first note as text (`"S: D5, A: A4, T: F#4, B: D3"`) and a short piano clip |
| `describe_score` | Summarize a score cheaply: title, key, time, tempo, parts (ID, clef, range), measures, duration |
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
| `SHEET_MUSIC_OUTPUT_ROOT` | No | Folder `output_path` must be inside; also readable by `musicxml_path` (default: working directory). Without `output_path`, `synthesize` writes `audio/output-<timestamp>.wav` here (earlier releases used `/tmp/synth-mcp-<uid>/`; use the returned `audio_path`) |
| `SHEET_MUSIC_INPUT_ROOTS` | No | Extra folders `musicxml_path` may read (`:`-separated; `;` on Windows) |

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

// The same, reading a file instead of copying the score into the conversation
{"tool": "get_parts", "arguments": {"musicxml_path": "scores/chorale.mxl"}}

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
    "parts": ["Soprano"],
    "tempo_factor": 0.8
  }
}

// Practice track: Alto loud, others soft, bars 17-24 three times, one bar of count-in
{
  "tool": "synthesize",
  "arguments": {
    "musicxml_path": "scores/chorale.mxl",
    "preset": "learning",
    "focus_part": "Alto",
    "measures": [17, 24],
    "repeat": 3,
    "count_in_bars": 1
  }
}

// Starting notes before singing
{"tool": "starting_pitches", "arguments": {"musicxml_path": "scores/chorale.mxl"}}
```

`parts` accepts part IDs from `get_parts` (`"P1"`), part names (`"Soprano"`, any case) or voices
(`"S"`, `"Alto"`, `"Alt"`, `"A1"` for divisi); an unknown part returns the valid choices.
`part_ids` still works as a deprecated alias for one minor release.

Every tool that takes `musicxml` also takes `musicxml_path` instead (exactly one of the two): a
`.musicxml`, `.xml` or compressed `.mxl` file inside the output root, a folder the client shares as
an MCP root, or a folder in `SHEET_MUSIC_INPUT_ROOTS`. Prefer it, and pass on paths other servers
return. `describe_score` reports part IDs, ranges and duration without returning the score.

`tempo_factor` range: 0.25–4.0. Values below 1.0 slow down; above 1.0 speed up. Does not affect pitch.

Practice options on `synthesize` (all optional; leaving them out gives the plain track):

| Option | Values | Effect |
|--------|--------|--------|
| `measures` | `[start, end]` | Only these printed bars (a pickup is 0) |
| `repeat` | 1–20 | Play the selection this many times |
| `count_in_bars` | 0–4 | Wood-block clicks before the music |
| `metronome` | true / false | Clicks on every beat of the music too |
| `timbre` | `score`, `piano`, `choir`, `organ` | Sound for every part (`score` keeps the score's instruments) |
| `preset` + `focus_part` | `learning` (focus 1.5, others 0.5), `karaoke` (focus muted), `equal` | Part volumes |
| `part_gains` | part → 0.0–2.0 | Per-part volume, overrides the preset |

`starting_pitches` returns the text always; the clip (mono 16 kHz WAV, inline when ≤ 200 KB) needs
the soundfont and FluidSynth. Without them the result says why in `audio_unavailable`.

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
