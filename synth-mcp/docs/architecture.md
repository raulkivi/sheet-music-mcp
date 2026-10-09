# synth-mcp — Technical Architecture

## Overview

synth-mcp is a stateless MCP server that synthesizes WAV audio from MusicXML. It uses music21 to parse the score and extract MIDI, then pyfluidsynth to render MIDI to a WAV file using a soundfont. Every tool call is independent; no session state is retained.

---

## Component Diagram

```
┌───────────────────────────────────────────────────────────┐
│                      MCP Client                           │
└──────────────────────────┬────────────────────────────────┘
                           │  stdio (JSON-RPC)
┌──────────────────────────▼────────────────────────────────┐
│                       server.py                           │
│                                                           │
│  list_tools()   → 3 tool definitions                      │
│  call_tool()    → dispatches to engine                    │
│  _error()       → error JSON helper                       │
└──────────┬────────────────────────────────────────────────┘
           │
┌──────────▼──────────────┐  ┌──────────────────────────────┐
│       engine.py         │  │          utils.py            │
│                         │  │                              │
│  parse_parts()          │  │  validate_musicxml()         │
│  extract_midi()         │  │  validate_tempo_factor()     │
│  synthesize_midi()      │  │  generate_output_path()      │
│  _get_wav_duration()    │  └──────────────────────────────┘
│  ProcessingError        │
└──────────┬──────────────┘
           │
     ┌─────┴──────────────┐
     │                    │
┌────▼───────┐  ┌─────────▼──────────┐
│  music21   │  │   pyfluidsynth     │
│            │  │                    │
│  parseData │  │  Synth()           │
│  converter │  │  sfload()          │
│  MIDI      │  │  play_midi_file()  │
│  export    │  │  fluid_player_join │
└────────────┘  └─────────┬──────────┘
                          │
                ┌─────────▼──────────┐
                │  libfluidsynth.so.3│
                │  (system library)  │
                └────────────────────┘
```

---

## Module Responsibilities

### `server.py`

MCP protocol layer. Contains no business logic.

- Registers three tools: `get_parts`, `synthesize`, `list_capabilities`
- Validates parameters (delegates to `utils.py`) before calling engine
- Converts engine results and `ProcessingError` exceptions to `TextContent` JSON
- Checks `SYNTH_SOUNDFONT_PATH` at `list_capabilities` time to report soundfont status
- Entry point via `mcp.server.stdio.stdio_server()`

### `engine.py`

Core synthesis logic. No MCP imports.

| Function | Description |
|----------|-------------|
| `parse_parts(musicxml_str)` | Parse MusicXML with music21; return list of `{id, name, measure_count}` |
| `extract_midi(musicxml_str, part_ids, tempo_factor)` | Filter parts, apply tempo, export to MIDI bytes |
| `synthesize_midi(midi_bytes, output_path)` | Write MIDI to temp file; render to WAV via pyfluidsynth |
| `_get_wav_duration(wav_path)` | Read WAV header; return duration in seconds |
| `ProcessingError(message, error_code)` | Structured exception for all engine errors |

### `utils.py`

Input validation and path generation.

| Function | Description |
|----------|-------------|
| `validate_musicxml(xml_str)` | Check non-empty; parse with music21 |
| `validate_tempo_factor(value)` | Check 0.25 ≤ value ≤ 4.0 |
| `generate_output_path(path)` | Return caller-supplied path or auto-generate in `/tmp/synth-mcp/` |

---

## Data Flow

### `synthesize` tool

```
call_tool("synthesize", {musicxml, part_ids, tempo_factor, output_path})
  │
  ├─ utils: validate_musicxml
  ├─ utils: validate_tempo_factor (if provided)
  ├─ utils: generate_output_path
  │
  ├─ engine: extract_midi(musicxml, part_ids, tempo_factor)
  │     ├─ music21.converter.parseData(musicxml)
  │     ├─ validate & filter parts by part_ids
  │     │     └─ error if unknown part_id
  │     ├─ deep-copy selected parts into new Score
  │     ├─ if the selected parts have no MetronomeMarks: copy the score's marks
  │     │     (usually only in the top part) into the first selected part, at their offsets
  │     ├─ apply tempo_factor to all MetronomeMarks
  │     │     └─ mark.number *= tempo_factor
  │     │     └─ if no marks: insert MetronomeMark(120 * tempo_factor) at measure 1
  │     ├─ music21.midi.translate.streamToMidiFile(score)
  │     └─ return MIDI bytes
  │
  ├─ engine: synthesize_midi(midi_bytes, output_path)
  │     ├─ write MIDI bytes to /tmp/synth_XXXXX.mid
  │     ├─ check SYNTH_SOUNDFONT_PATH
  │     ├─ pyfluidsynth.Synth(
  │     │     gain=1.0,
  │     │     samplerate=44100.0
  │     │  )
  │     ├─ fs.setting("audio.driver", "file")
  │     ├─ fs.setting("audio.file.name", output_path)
  │     ├─ fs.setting("audio.file.type", "wav")
  │     ├─ fs.setting("player.timing-source", "sample")
  │     ├─ sfid = fs.sfload(soundfont_path)
  │     ├─ fs.program_select(chan=0, sfid, bank=0, preset=52)  [choir aahs]
  │     ├─ fs.start(driver="file")
  │     ├─ fs.play_midi_file(tmp_midi_path)
  │     ├─ fluidsynth.fluid_player_join(fs.player)  ← BLOCKING
  │     ├─ fs.delete()
  │     └─ return _get_wav_duration(output_path)
  │
  └─ return {audio_path, format, duration_seconds, parts_included, tempo_factor}
```

### `get_parts` tool

```
call_tool("get_parts", {musicxml})
  │
  ├─ utils: validate_musicxml
  ├─ engine: parse_parts(musicxml)
  │     ├─ music21.converter.parseData(musicxml)
  │     └─ for each part:
  │           id = part.id          (music21 9.x: part.id is the part name, e.g. "Soprano")
  │           name = part.partName
  │           measure_count = len(part.getElementsByClass("Measure"))
  └─ return {parts: [{id, name, measure_count}, ...]}
```

---

## Tempo Factor Application

music21 represents tempo as `MetronomeMark` objects embedded in the score. The engine modifies them in-place on the deep-copied score before MIDI export:

```python
for mark in score.flatten().getElementsByClass(MetronomeMark):
    mark.number = mark.number * tempo_factor

if no marks found:
    score.parts[0].measure(1).insert(0, MetronomeMark(number=120 * tempo_factor))
```

This scales time uniformly. Pitch is not affected because the MIDI note numbers are unchanged.

MusicXML usually carries the tempo marking only in the top part. Before scaling, if none of the
selected parts has a `MetronomeMark`, `_carry_over_tempo_marks()` copies the full score's marks
(topmost part wins at a shared offset) into the first selected part at their original offsets.
So a lower part exported alone plays at the score tempo, not MIDI's 120 BPM default. The 120 BPM
fallback only applies when the whole score has no tempo marking.

---

## FluidSynth File Rendering

Rather than using FluidSynth's interactive audio driver, the engine uses `audio.driver=file` mode which writes directly to a WAV file without any audio hardware:

```
pyfluidsynth.Synth settings
  audio.driver      = "file"       ← write to file, not speakers
  audio.file.name   = output.wav   ← destination path
  audio.file.type   = "wav"
  player.timing-source = "sample"  ← sample-accurate timing

fs.start(driver="file")            ← starts file writer
fs.play_midi_file(midi_path)       ← queues MIDI
fluid_player_join(fs.player)       ← BLOCKS until MIDI playback complete
fs.delete()                        ← cleanup
```

`fluid_player_join` is a C-level blocking call. It blocks the Python thread (and therefore the MCP event loop) until synthesis is complete. This is acceptable for Phase 1.

---

## Part Identification (music21 9.x)

In music21 9.x, `part.id` returns the part's *name* (e.g. `"Soprano"`), not the XML attribute `<part id="P1">`. The engine uses this as the part identifier throughout. When a caller passes `part_ids=["Soprano"]`, the engine matches against `part.id` values.

This is a non-obvious music21 9.x behaviour documented in the project memory.

---

## Error Handling

Engine errors are raised as `ProcessingError(message, error_code)`. The server layer catches these and returns JSON error objects.

```json
{"error": "Invalid tempo_factor 5.0; must be between 0.25 and 4.0", "error_code": "INVALID_PARAMETER"}
```

| Scenario | Code |
|----------|------|
| MusicXML parse failure | `INVALID_INPUT` |
| No parts found in score | `INVALID_INPUT` |
| Unknown part ID | `INVALID_PARAMETER` |
| tempo_factor out of range | `INVALID_PARAMETER` |
| `SYNTH_SOUNDFONT_PATH` not set | `PROCESSING_FAILED` |
| Soundfont file not found | `PROCESSING_FAILED` |
| libfluidsynth not installed | `PROCESSING_FAILED` |
| FluidSynth synthesis error | `PROCESSING_FAILED` |

---

## Key Dependencies

| Package | Role |
|---------|------|
| `music21` ≥9.0 | MusicXML parsing, part/note model, MIDI export |
| `pyfluidsynth` ≥1.3 | Python bindings for libfluidsynth |
| `mcp` | MCP protocol SDK |

**System library:** `libfluidsynth.so.3` (Linux) / `libfluidsynth.dylib` (macOS) must be installed separately. pyfluidsynth loads it via ctypes at import time; if missing, import fails and the server exits.

---

## Output Files

Auto-generated WAV paths use a timestamp:

```
/tmp/synth-mcp/output_YYYYMMDD_HHMMSS_ffffff.wav
```

The directory is created if it does not exist.

---

## File Layout

```
synth-mcp/
├── pyproject.toml
├── src/
│   └── synth_mcp/
│       ├── __init__.py
│       ├── server.py     ← MCP layer (tool registration, dispatch)
│       ├── engine.py     ← Business logic (music21, pyfluidsynth)
│       └── utils.py      ← Validation, path generation
└── tests/
    ├── test_server.py
    ├── test_engine.py
    ├── test_utils.py
    └── fixtures/
```
