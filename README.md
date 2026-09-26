# sheet-music-mcp

[![Tests](https://github.com/raulkivi/sheet-music-mcp/actions/workflows/tests.yml/badge.svg)](https://github.com/raulkivi/sheet-music-mcp/actions/workflows/tests.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/raulkivi/sheet-music-mcp/badge)](https://scorecard.dev/viewer/?uri=github.com/raulkivi/sheet-music-mcp)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Six MCP servers that let an AI assistant work with sheet music: read a photo of a score, render it, play single voice parts, edit it as text, compare editions and follow a singer in real time. Built for choir rehearsal.

> "Here is a photo of page 1. Convert it to MusicXML and play me the alto part at 80% tempo."

The assistant calls `omr-mcp` to recognise the page, then `synth-mcp` to render the alto line to a WAV file.

## Servers

Each server is a separate PyPI package, listed in the [MCP Registry](https://registry.modelcontextprotocol.io/v0/servers?search=io.github.raulkivi) as `io.github.raulkivi/<server>`.

| Server | What it does | Run | Needs |
|---|---|---|---|
| [omr-mcp](omr-mcp/) | Photo or scan of printed sheet music → MusicXML (oemer, or Audiveris for SATB scores) | `uvx omr-mcp` | ~100 MB model download on first use |
| [render-mcp](render-mcp/) | MusicXML → PDF, PNG or SVG | `uvx render-mcp` | Cairo (`libcairo2`) |
| [synth-mcp](synth-mcp/) | MusicXML → WAV, selected voice parts, adjustable tempo | `uvx synth-mcp` | FluidSynth, an SF2 soundfont |
| [musicxml-abc-mcp](musicxml-abc-mcp/) | MusicXML ↔ ABC notation, so the model can read and edit the score as text | `uvx musicxml-abc-mcp` | |
| [pitch-mcp](pitch-mcp/) | Follows a singer through a score from the microphone; reports position and pitch accuracy | `uvx pitch-mcp` | Python 3.12+, PortAudio, a microphone |
| [comparer-mcp](comparer-mcp/) | Music-aware diff of two MusicXML files: editions, arrangements, OMR output against a reference | `uvx comparer-mcp` | |

All servers use stdio and need Python 3.11+ (3.12+ for `pitch-mcp`) and [uv](https://docs.astral.sh/uv/).

## Quick start

Add the servers you need to your MCP client configuration (`claude_desktop_config.json`, Cursor's `mcp.json` and similar):

```json
{
  "mcpServers": {
    "omr": { "command": "uvx", "args": ["omr-mcp"] },
    "render": { "command": "uvx", "args": ["render-mcp"] },
    "synth": {
      "command": "uvx",
      "args": ["synth-mcp"],
      "env": { "SYNTH_SOUNDFONT_PATH": "/path/to/soundfont.sf2" }
    }
  }
}
```

Claude Code:

```sh
claude mcp add omr -- uvx omr-mcp
```

Each server's `SETUP.md` walks through installation for non-developers, and `examples/` has ready-made configs for Claude Desktop, Cursor, Windsurf, Continue and Zed. Every server has a `health_check` tool that reports missing system libraries or files.

## Security

- PyPI releases use [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) from GitHub Actions and carry PEP 740 attestations; no API tokens are stored.
- Workflow actions are pinned to commit SHAs; Dependabot keeps them and the Python dependencies current.
- Pull requests run CodeQL, a Claude security review and [unicode-smuggling-guard](https://github.com/raulkivi/unicode-smuggling-guard), which blocks hidden Unicode in code, docs and agent files.
- Secret scanning and push protection are on.
- Report vulnerabilities privately: see [SECURITY.md](SECURITY.md).

---

## Background

The project started as a choir assistant: help singers digitize, practice with, and navigate sheet music on their phones.

### Goals

1. Digitize paper sheet music (photograph → digital score)
2. Export sheet music as a PDF
3. Play sheet music in individual voices (Soprano, Alto, Tenor, Bass) or combined
4. Show the current position in the score while singing (tempo tracking)
5. Show pitch accuracy in real time (too high / too low / on pitch)
6. Identify where in a score a singer currently is based on a hummed or sung melody
7. Compare two scores (editions, arrangements, OMR output vs. reference) and report structured diffs

### Delivery phases

| Phase | Description | Status |
|-------|-------------|--------|
| **Phase 1 — MCP servers** | Six independent MCP servers, each covering one capability | ✅ All six released on PyPI; see known limitation below |
| **Phase 2 — Web PoC** | Web app orchestrating the MCP servers for full UX validation | Planned |
| **Phase 3 — Android app** | Native Kotlin app for rehearsal use on phones | Planned |

Known limitation: `omr-mcp`'s default engine (oemer) flattens multi-staff SATB scores into one part. Pass `engine="audiveris"` for choir scores; it needs 300+ DPI images.

### Data flow

```
Paper score
    │  (photo)
    ▼
[omr-mcp]
    │  MusicXML
    ├──────────────────────────► [render-mcp] ──► PDF / PNG         (goal 2)
    │
    ├──────────────────────────► [synth-mcp]                        (goal 3)
    │                                │  voice selection + tempo
    │                                ▼
    │                            Audio file
    │
    ├──────────────────────────► [musicxml-abc-mcp]
    │                                │  ABC text
    │                                ▼
    │                            Claude (reads / edits)
    │                                │  ABC text (edited)
    │                                ▼
    │                            [musicxml-abc-mcp]
    │                                │  MusicXML (AI-edited)
    │                                ▼
    │                            (back into pipeline)
    │
    ├──────────────────────────► [pitch-mcp]
    │                                │  loads reference score
    │                                ▲  microphone audio stream
    │                                │
    │                            score position + pitch accuracy    (goals 4, 5, 6)
    │
    └──────────────────────────► [comparer-mcp]  (also compares against any MusicXML)
                                     │  reference score
                                     ▲  second MusicXML (edition / arrangement / OMR output)
                                     │
                                 structured diff                    (goal 7)
```

### Why ABC notation?

ABC is a compact, text-based music notation format that LLMs can read and edit directly (unlike the
verbose XML of MusicXML). The `musicxml-abc-mcp` server enables AI-assisted score editing:
MusicXML → ABC → Claude edits → ABC → MusicXML.

---

## Technology stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Language | Python 3.11+ (3.12+ for pitch-mcp) | Best library ecosystem for music, audio, and ML |
| Package manager | uv | Fast, reproducible builds |
| MCP framework | `mcp` Python SDK 2.x | Official SDK; stdio transport for local deployment |
| OMR | oemer on ONNX Runtime; Audiveris (opt-in) | Sheet music recognition; Audiveris keeps SATB parts apart |
| Rendering | Verovio + cairosvg + pypdf | No external CLI dependency |
| Synthesis | pyfluidsynth + music21 | In-process, no subprocess |
| Pitch detection | librosa pYIN + sounddevice | Pure Python, excellent for singing voice |
| Comparison | music21 | Structural / musical diffing of scores |
| Testing | pytest + pytest-asyncio | Standard async-capable testing |

---

## Development

Each server has its own virtual environment managed by [uv](https://docs.astral.sh/uv/). Never share venvs between servers, and use `uv sync` / `uv add` rather than `pip install`.

```bash
cd synth-mcp
uv sync --extra dev
uv run pytest -m "not integration"   # what CI runs, on Python 3.12 and 3.13
uv run pytest -m integration         # needs the real OMR/audio backends
```

System libraries for local development:

| Library | Package (Debian/Ubuntu) | Used by |
|---------|-------------------------|---------|
| FluidSynth | `libfluidsynth3` | synth-mcp |
| Cairo | `libcairo2` | render-mcp |
| PortAudio | `libportaudio2` | pitch-mcp |

Free SF2 soundfonts are listed in [synth-mcp/README.md](synth-mcp/README.md).

Releases: bump the version in `pyproject.toml`, `__init__.py`, `uv.lock` and `server.json`, then push a `<server>/vX.Y.Z` tag. [publish.yml](.github/workflows/publish.yml) publishes to PyPI and the MCP Registry.

---

## Documentation

- [docs/conventions.md](docs/conventions.md) — coding and structural conventions shared across all servers
- [docs/sources.md](docs/sources.md) — references and sources
- [docs/SETUP_UX_PLAN.md](docs/SETUP_UX_PLAN.md) — end-user packaging plan (PyPI, installers, setup docs)
- Each server has its own `docs/` folder with `PLAN.md`, `HANDOVER.md`, `requirements.md`, and `architecture.md`

## License

[MIT](LICENSE)
