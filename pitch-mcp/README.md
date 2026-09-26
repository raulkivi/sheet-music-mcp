# pitch-mcp

<!-- mcp-name: io.github.raulkivi/pitch-mcp -->

MCP server for real-time pitch detection and score alignment. Listens to a singer via microphone and reports their current position in a score and whether they are singing in tune.

## What it does

Covers three goals:
- **Goal 4** — Show the current measure/beat position while singing
- **Goal 5** — Report pitch accuracy (too high / too low / on pitch)
- **Goal 6** — Identify where in the score a singer is based on a hummed or sung phrase

Supports both offline analysis of pre-recorded audio and real-time microphone input.

## Tools

| Tool | Description |
|------|-------------|
| `analyze_recording` | Offline: analyse a WAV file against a reference MusicXML score |
| `load_score` | Load a MusicXML score into a named session; returns a `session_id` |
| `start_monitoring` | Open the microphone and begin real-time pitch detection |
| `get_current_position` | Poll the current score position and pitch accuracy |
| `stop_monitoring` | Stop the microphone and return a session summary |
| `list_capabilities` | Return server metadata: pitch backend, microphone availability |
| `health_check` | Check that runtime dependencies (librosa, sounddevice/portaudio) are available |

## Installation

```bash
cd pitch-mcp
uv sync
```

For real-time monitoring (`start_monitoring`), PortAudio is required:

```bash
# Ubuntu / Debian
sudo apt install libportaudio2
```

**Quick install:** on Ubuntu/Debian/Linux Mint, `bash install.sh` handles `uv` and the optional
`libportaudio2` install for you — see [SETUP.md](SETUP.md) for the full non-technical walkthrough.
Ready-made client configs (Claude Desktop, Cursor, Windsurf, Continue, Zed) are in
[`examples/`](examples/). If something goes wrong, check [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Running

```bash
uv run pitch-mcp
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `PITCH_BACKEND` | `librosa` | Pitch detection algorithm: `librosa` or `crepe` |

`crepe` requires a manual TensorFlow install (~500 MB) and downloads ~50 MB of model weights on first use. The default `librosa` backend (pYIN algorithm) works well for singing voice with no extra setup.

## Usage examples

```json
// Offline analysis of a recording
{
  "tool": "analyze_recording",
  "arguments": {
    "wav_path": "/path/to/recording.wav",
    "musicxml_path": "/path/to/score.mxl",
    "part_name": "Soprano"
  }
}

// Real-time session
{"tool": "load_score", "arguments": {"musicxml_path": "/path/to/score.mxl", "part_name": "Alto"}}
// → returns {"session_id": "abc123"}

{"tool": "start_monitoring", "arguments": {"session_id": "abc123"}}
{"tool": "get_current_position", "arguments": {"session_id": "abc123"}}
// → returns measure, beat, expected pitch, detected pitch, accuracy

{"tool": "stop_monitoring", "arguments": {"session_id": "abc123"}}
```

Audio must be 16-bit PCM WAV. MP3 and FLAC are not supported.

## Testing

```bash
# Unit tests (no microphone or audio required)
VIRTUAL_ENV= .venv/bin/pytest tests/ -v

# Integration tests (offline analysis against a committed fixture pair)
VIRTUAL_ENV= .venv/bin/pytest tests/ -v -m integration

# Manual tests (real microphone required — skip in CI)
VIRTUAL_ENV= .venv/bin/pytest tests/ -v -m manual
```

112 of the 118 total tests are unit tests, run against mocks and synthetic (in-memory) WAV data —
none require real audio hardware or pre-recorded fixtures. The other 6 are marked `integration`
(4 — offline analysis against the committed `tests/fixtures/` pair) or `manual` (2 — full
real-microphone session lifecycle) and are excluded from a plain `pytest tests/` run by
`tests/conftest.py`; select them explicitly with `-m integration` / `-m manual`.

## Dependencies

- [librosa](https://librosa.org/) — pYIN pitch detection (primary backend, pure Python)
- [music21](https://web.mit.edu/music21/) — score parsing and pitch calculations
- [sounddevice](https://python-sounddevice.readthedocs.io/) — real-time microphone input
- [numpy](https://numpy.org/), [scipy](https://scipy.org/) — numerics
- [mcp](https://github.com/modelcontextprotocol/python-sdk) — MCP protocol

## System requirements

- Python 3.12+
- `libportaudio2` — required for real-time microphone input (`start_monitoring`)
- No system libraries required for offline analysis

## Phase status

| Phase | Status |
|-------|--------|
| Phase A — offline analysis | Complete. DTW-based alignment (`dtaidistance`); 112 unit tests plus 4 `-m integration` tests against a committed fixture pair (`tests/fixtures/`) |
| Phase B — real-time monitoring | Complete. Position tracking is audio-driven (matches detected pitch, not just elapsed time); `tempo_bpm` override supported. Covered by unit tests with mocked `sounddevice`; full-lifecycle `-m manual` tests exist for real-microphone verification but require real hardware to run |
