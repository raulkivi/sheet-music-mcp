# pitch-mcp — Claude Code Instructions

## What This Server Does

Real-time pitch detection from microphone input compared against a reference MusicXML score.
Reports current score position (measure + beat), pitch accuracy in cents, and sharp/flat/on-pitch
status while a singer sings.

**Status:** Phase A (offline analysis) + Phase B (real-time, audio-driven position tracking)
complete, plus UX Wave 2 (score references: `musicxml_path`, `describe_score`) and UX Wave 3
(`measures` ranges, `start_practice`, `highlights`). 331 unit
(+6 skipped) + 4 integration tests pass (`-m integration`); 2 manual mic tests (`-m manual`)
require real hardware.

---

## Running Tests

```bash
# From this directory
VIRTUAL_ENV= .venv/bin/pytest tests/ -v                 # 331 unit tests (integration/manual skipped by default)
VIRTUAL_ENV= .venv/bin/pytest tests/ -v -m integration   # offline analysis against the committed fixture pair
VIRTUAL_ENV= .venv/bin/pytest tests/ -v -m manual        # real mic tests — skip in CI
```

Install dependencies: `uv sync`

---

## Key Files

| File | Purpose |
|------|---------|
| `src/pitch_mcp/server.py` | MCP tool definitions and handlers |
| `src/pitch_mcp/presenter.py` | `structuredContent` + output schemas for the Practice Coach tools |
| `src/pitch_mcp/engine.py` | Session management, offline/real-time orchestration (no MCP imports) |
| `src/pitch_mcp/pitch_detector.py` | librosa pYIN backend (+ optional crepe) |
| `src/pitch_mcp/aligner.py` | DTW (dtaidistance) alignment, accuracy classification |
| `src/pitch_mcp/utils.py` | Note sequence extraction, metronome map, Hz↔note conversion |
| `docs/HANDOVER.md` | Status, remaining work, definition of done |
| `docs/PLAN.md` | Architecture decisions and rationale |
| `docs/requirements.md` | Functional/non-functional requirements |
| `docs/architecture.md` | Component diagram and data-flow |

---

## Implemented Tools

| Tool | Phase | Description |
|------|-------|-------------|
| `analyze_recording` | A | Pre-recorded WAV + MusicXML (`musicxml` or `musicxml_path`, optional `measures`) → per-note accuracy report + `highlights` |
| `load_score` | B | Load MusicXML (`musicxml` or `musicxml_path`, optional `measures`) into a session, return session_id |
| `start_practice` | W3 | `load_score` + `start_monitoring` in one call (`part`, `tempo_bpm`, `measures`); no orphan session if the mic fails |
| `describe_score` | W2 | Shared core tool: title, key, tempo, parts with IDs and ranges, without loading a session |
| `start_monitoring` | B | Open mic stream for a session |
| `get_current_position` | B | Current measure/beat/pitch/accuracy from active session |
| `stop_monitoring` | B | Stop stream, return summary (with `highlights`), clean up session (`timed_out: true` if the idle timeout closed it) |
| `list_sessions` | B | Open sessions: part, state (`loaded`/`monitoring`), idle seconds |
| `get_score_for_session` | Apps | App-only: the session's MusicXML for the Practice Coach (`session_id` only, no paths) |
| `list_capabilities` | — | Server metadata, pitch backend version |
| `health_check` | — | Runtime dependency status |

---

## Environment

- **Primary pitch backend:** `librosa.pyin` — pure Python, no system deps, excellent for voice
- **Real-time (Phase B):** `sounddevice` + YIN autocorrelation in worker thread
- **System dep:** `libportaudio2` required at runtime for real-time streams (Phase B only)
  Offline analysis (Phase A / `analyze_recording`) has no system deps.
- **MXL fixtures:** `../omr-mcp/test_samples/pdmx_satb_samples/mxl/` (10 SATB files)

---

## Hard Rules

- **Never `pip install`** — use `uv sync` or `uv add`
- **`engine.py` must not import from `mcp`** — keeps it unit-testable
- **All tool handlers must be `async def`**
- **All errors** → `{"error": "...", "error_code": "..."}` (codes: `FILE_NOT_FOUND`, `UNSUPPORTED_FORMAT`, `INVALID_INPUT`, `PROCESSING_FAILED`, `INVALID_PARAMETER`, `SESSION_NOT_FOUND`)
- **Integration tests** must be `@pytest.mark.integration`; manual mic tests `@pytest.mark.manual`
- **Audio callback must never do I/O or locking** — queue chunks to a `queue.Queue` only

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

`run_server()` does not exist in the installed MCP SDK — use the context manager above.

---

## Known Gotchas

- **`crepe` fails to build under uv** (missing `pkg_resources`) — keep as manual opt-in only;
  do not add it to default dependencies.
- **`aubio` has no Python 3.13 wheel** and requires `libportaudio2` + `libsamplerate` — use
  `librosa` instead for all pitch detection.
- **`sounddevice` streams fail at runtime** if `libportaudio2` is absent. Phase B real-time
  features simply won't work on machines without it; Phase A is unaffected.
- **This is the only stateful server.** Sessions are held in the module-level `SessionRegistry`
  (`engine._registry`), which has its own lock. Use `threading.Lock` to protect shared state accessed
  by the worker thread and tool handlers. Never do I/O or take a lock inside the audio callback —
  only queue chunks.
- **Idle sessions are reaped.** A `Reaper` daemon thread (started by the first `load_score`) calls
  `registry.reap(clock())` every 30 s and closes sessions idle longer than
  `PITCH_SESSION_IDLE_MINUTES` (default 10, `0` = off, read once at import). Activity = creation,
  `start_monitoring`, `get_current_position`. Timed-out summaries are kept 1 h for
  `stop_monitoring` (`timed_out: true`). Test with an injected fake clock and `reap(now)`, never
  with real waits; `tests/conftest.py` stops the reaper thread at the end of the run.
- **Score paths go through the core.** `server._reference_score()` calls
  `sheet_music_mcp_core.references.load_score()` (read roots: `SHEET_MUSIC_OUTPUT_ROOT`, client
  MCP roots, `SHEET_MUSIC_INPUT_ROOTS`), then the same `validate_musicxml()` inline text gets.
  Never open a score path yourself. The core function is imported as `read_score` because
  `engine.load_score` (the session tool) has the same name. `audio_path` is deliberately not
  confined (Wave 2 decision W2-3). The schemas carry both `anyOf` (`part` / `part_id`) and
  `oneOf` (`musicxml` / `musicxml_path`) at the top level.
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

---

## Claude Desktop Config

```json
{
  "mcpServers": {
    "pitch": {
      "command": "uv",
      "args": ["--directory", "/path/to/pitch-mcp", "run", "pitch-mcp"]
    }
  }
}
```

---

## Document Update Policy

When you finish work or reach a milestone, update:
1. `docs/HANDOVER.md` — check off done items, add new gotchas
2. `docs/PLAN.md` — check off phase items, note changed decisions
3. `docs/requirements.md` — update if behaviour changed
4. `docs/architecture.md` — update if implementation changed
