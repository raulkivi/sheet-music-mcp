# pitch-mcp — Copilot Instructions

## What This Server Does

Real-time pitch detection from microphone input compared against a reference MusicXML score.
Reports current score position (measure + beat), pitch accuracy in cents, and sharp/flat/on-pitch
status while a singer sings. This is the most complex server in the project — it is stateful.

**Status:** Phase A (offline analysis) + Phase B (real-time, audio-driven position tracking)
complete, plus UX Wave 2 (score references: `musicxml_path`, `describe_score`) and UX Wave 3
(`measures` ranges, `start_practice`, `highlights`). 292 unit
(+2 skipped) + 4 integration tests pass (`-m integration`); 2 manual mic tests (`-m manual`)
require real hardware.

---

## Before You Write Any Code

Read these documents in order:
1. **`docs/HANDOVER.md`** — current status, remaining work, pre-flight checks, known gotchas, definition of done
2. **`docs/PLAN.md`** — architecture decisions and technology rationale
3. **`docs/requirements.md`** — functional and non-functional requirements, error codes
4. **`docs/architecture.md`** — component diagram, data-flow, module responsibilities

---

## Project Structure

```
pitch-mcp/
├── pyproject.toml
├── .python-version          # "llm311"
├── src/pitch_mcp/
│   ├── server.py            # MCP tool definitions and async handlers
│   ├── engine.py            # Session management, offline/real-time orchestration — NO mcp imports
│   ├── pitch_detector.py    # librosa pYIN backend (+ optional crepe)
│   ├── aligner.py           # DTW (dtaidistance) alignment, accuracy classification
│   └── utils.py             # Note sequence extraction, metronome map, Hz↔note conversion
├── tests/
│   ├── conftest.py          # skips @integration/@manual unless requested via -m
│   ├── test_server.py       # protocol tests
│   ├── test_engine.py       # unit tests
│   ├── test_aligner.py      # unit tests
│   ├── test_pitch_detector.py  # unit tests
│   ├── test_utils.py        # unit tests
│   ├── test_score_references.py  # musicxml_path, read confinement, describe_score (Wave 2)
│   ├── test_practice.py     # measures, start_practice, <sound tempo> (Wave 3; fake sounddevice)
│   ├── test_highlights.py   # aligner.highlights and summaries (Wave 3)
│   ├── test_integration.py  # @pytest.mark.integration, runs against the fixture pair
│   ├── test_manual.py       # @pytest.mark.manual, requires a real microphone
│   └── fixtures/
│       ├── soprano_phrase.wav   # synthetic sine-tone proxy — not a real recording, see fixtures/README.md
│       ├── reference.musicxml   # matching score
│       └── README.md
└── docs/
    ├── requirements.md
    └── architecture.md
```

MXL test fixtures are in `../omr-mcp/test_samples/pdmx_satb_samples/mxl/` — 10 SATB files.

---

## Implemented Tools

| Tool | Phase | Description |
|------|-------|-------------|
| `analyze_recording` | A | Pre-recorded WAV + MusicXML (`musicxml` or `musicxml_path`, optional `measures`) → per-note pitch accuracy report + `highlights` |
| `load_score` | B | Load MusicXML (`musicxml` or `musicxml_path`, optional `measures`) into session, return session_id |
| `start_practice` | W3 | `load_score` + `start_monitoring` in one call (`part`, `tempo_bpm`, `measures`); no orphan session if the mic fails |
| `describe_score` | W2 | Shared core tool: title, key, tempo, parts with IDs and ranges |
| `start_monitoring` | B | Open mic stream for a session |
| `get_current_position` | B | Current measure/beat/pitch/accuracy from active session |
| `stop_monitoring` | B | Stop stream, return summary (with `highlights`), clean up session |
| `list_sessions` | B | Open sessions: part, state (`loaded`/`monitoring`), idle seconds |
| `list_capabilities` | — | Server metadata, pitch backend and version |
| `health_check` | — | Runtime dependency status |

---

## Environment

- **Primary pitch backend:** `librosa.pyin` — pure Python, no system deps, excellent for voice
- **Real-time (Phase B):** `sounddevice` + YIN autocorrelation in worker thread
- **System dep for Phase B:** `libportaudio2` — must be present for real-time streams
  Phase A (`analyze_recording`) has no system dependencies
- **`crepe`:** fails to build under uv — do not add to default deps; keep as manual opt-in only
- **`aubio`:** no Python 3.13 wheel — do not use; use librosa instead

---

## Coding Standards

- **Package manager:** `uv` only — never `pip install`
- **`engine.py` must not import from `mcp`** — keeps it independently unit-testable
- **All tool handlers must be `async def`**
- **All error responses:** `{"error": "human description", "error_code": "SCREAMING_SNAKE"}`
- **Standard error codes:** `FILE_NOT_FOUND`, `UNSUPPORTED_FORMAT`, `INVALID_INPUT`, `PROCESSING_FAILED`, `INVALID_PARAMETER`, `SESSION_NOT_FOUND`
- **Integration tests** → `@pytest.mark.integration`; real-mic tests → `@pytest.mark.manual`
- **Audio callback must never do I/O or locking** — queue audio chunks to `queue.Queue` only
- **Python 3.12+**; `asyncio_mode = "auto"` in pytest config

---

## Running Tests

```bash
# Unit tests only (fast, no mic needed) — integration/manual are skipped by default
VIRTUAL_ENV= .venv/bin/pytest tests/ -v

# Integration tests only (offline analysis against the committed fixture pair)
VIRTUAL_ENV= .venv/bin/pytest tests/ -v -m integration

# Manual tests (real mic — skip in CI)
VIRTUAL_ENV= .venv/bin/pytest tests/ -v -m manual

# Install dependencies
uv sync
```

---

## MCP Server Startup Pattern

```python
import asyncio
import mcp.server.stdio

async def _run():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

asyncio.run(_run())
```

`mcp.server.stdio.run_server()` does not exist — always use the context manager above.

---

## Known Gotchas

- **`crepe` fails to build under uv** (missing `pkg_resources`) — do not add to dependencies.
- **`aubio` has no Python 3.13 wheel** — use `librosa` for all pitch detection.
- **sounddevice streams require `libportaudio2`** at runtime. Phase A works without it.
- **This is the only stateful server.** Sessions live in a module-level dict in `engine.py`.
  Protect shared state with `threading.Lock` — both the audio callback thread and MCP handlers
  access session state.
- **Audio callback constraint:** never do I/O, locking, or heavy computation inside the
  sounddevice callback. Only write chunks to a `queue.Queue`.
- **Score paths go through the core** (`sheet_music_mcp_core.references.load_score()`, imported as
  `read_score`), confined to the read roots; never open a score path yourself. `audio_path` is not
  confined (Wave 2 decision W2-3).
- **`analyze_recording` accepts 16-bit PCM WAV only.** Reject MP3/FLAC with `UNSUPPORTED_FORMAT`.
- **`measures` cuts the score in the engine** (`_select` / `ScoreSession.__init__`: core
  `select_measures(text, measures)` before `extract_part_notes`). The timeline starts at
  0 s at `start`; measures keep printed numbers; `measure_count` counts from `start` (bar 1 without
  `measures`). The server passes `measures` only when given (`_measures(arguments)`), so existing
  engine calls and fakes are untouched.
- **Cut scores carry the tempo as a bare `<sound tempo>`.** music21 reads that as a MetronomeMark
  with `number=None` and `numberSounding` set; `_build_metronome_map` uses `number`, else
  `numberSounding`, else 120. Without that, a cut score (or any score with only `<sound tempo>`)
  silently ran at 120 BPM.
- **`start_practice` must not leave an orphan.** If `start_monitoring` raises, `_discard` removes
  the session and calls `stop()` (which also closes a stream that opened but failed to start).
  Tests fake `sounddevice` via `sys.modules` (`tests/test_practice.py`); never open a real mic.
- **Highlights take both result shapes.** Offline results use `expected`, live history
  `expected_note` and has one entry per frame; `aligner.highlights` merges consecutive entries
  with the same (measure, beat, pitch) into one note with the median cents.
- **Accuracy thresholds:** on_pitch = ±25 cents; sharp = >+25 cents; flat = <−25 cents.
- **Session cleanup:** `stop_monitoring` must delete the session — a second call must return
  `SESSION_NOT_FOUND`.
- **DTW always assigns every note ≥1 frame.** `aligner.align`'s `dtaidistance.dtw.warping_path`
  call is full-coverage, so a note the singer never attempted still gets forced onto some frame —
  compensated with a temporal-plausibility gate afterward. Don't remove that gate without keeping
  `no_signal` behavior for unsung notes.
- **Phase B position is audio-driven, not wall-clock.** `ScoreSession._process_pitch_frame` /
  `_find_best_note_index` pick the current note by pitch match within a forward lookahead, not
  purely by elapsed time. `_note_idx` must never move backward.

---

## When You Finish Work

Update these documents so the next session starts with accurate information:
- **`docs/HANDOVER.md`** — check off done items, add new gotchas, update status
- **`docs/PLAN.md`** — check off completed phase items, note changed decisions
- **`docs/requirements.md`** — update if behaviour or interfaces changed
- **`docs/architecture.md`** — update if implementation structure changed
