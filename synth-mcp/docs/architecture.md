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
│  list_tools()   → 6 tool definitions                      │
│  call_tool()    → load_score(), then dispatches to engine │
└──────────┬──────────────────────────────┬─────────────────┘
           │                              │ references.load_score()
           │                              │ references.describe_score_tool()
           │                  ┌───────────▼─────────────────┐
           │                  │ sheet_music_mcp_core        │
           │                  │ references → paths, scores  │
           │                  └─────────────────────────────┘
           │
┌──────────▼──────────────┐  ┌──────────────────────────────┐
│       engine.py         │  │          utils.py            │
│                         │  │                              │
│  parse_parts()          │  │  validate_musicxml()         │
│  extract_midi() ────────┼─▶│  validate_tempo_factor()     │
│  synthesize_midi()      │  │  generate_output_path()      │
│  _get_wav_duration()    │  └──────────────────────────────┘
│  ProcessingError        │  practice.py: gains, repeat, clicks, timbre, tune_midi()
└──────────┬──────────────┘  clip.py: starting_pitches(), clip_midi(), render_clip(),
           │                          downmix_wav()  (both MCP-free)
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

- Registers six tools: `get_parts`, `synthesize`, `starting_pitches`, `describe_score` (shared,
  from `sheet_music_mcp_core.references`), `list_capabilities`, `health_check`
- Passes only the practice options the caller gave (`PRACTICE_PARAMETERS`) to `extract_midi` and
  echoes them in the result, so a call without them is unchanged
- Takes the score as `musicxml` or `musicxml_path` (`oneOf`). `references.load_score()` returns
  the inline text as is, or reads a confined path (`.musicxml`, `.xml`, `.mxl`); the handlers then
  run the same validation and engine calls either way. `make_handlers(..., pass_context=True)`
  passes the request context so `load_score` can use the client's MCP roots
- Validates parameters (delegates to `utils.py`) before calling engine
- Converts engine results and `ProcessingError` exceptions to `TextContent` JSON (always `content[0]`)
- After a successful `synthesize`, appends a `resource_link` to the written WAV (`file://` URI,
  `audio/wav`) via `sheet_music_mcp_core.content.file_link`
- Checks `SYNTH_SOUNDFONT_PATH` at `list_capabilities` time to report soundfont status
- Entry point via `mcp.server.stdio.stdio_server()`

### `engine.py`

Core synthesis logic. No MCP imports.

| Function | Description |
|----------|-------------|
| `parse_parts(musicxml_str)` | Parse MusicXML with music21; return list of `{id, name, measure_count}` |
| `resolve_part_ids(musicxml_str, requested)` | Resolve part IDs, names or voices to stable MusicXML part IDs |
| `extract_midi(musicxml_str, part_ids, tempo_factor, *, measures, repeat, count_in_bars, metronome, timbre, part_gains, preset, focus_part)` | Cut bars, filter parts, practice steps, apply tempo, export to MIDI bytes |
| `synthesize_midi(midi_bytes, output_path)` | Write MIDI to temp file; render to WAV via pyfluidsynth |
| `_get_wav_duration(wav_path)` | Read WAV header; return duration in seconds |
| `ProcessingError(message, error_code)` | Structured exception for all engine errors |

### `practice.py`

Practice-track steps for `extract_midi` (UX Wave 3, [conventions: Practice Audio](../../docs/conventions.md#practice-audio)).
No MCP imports; each step is a no-op at its default.

| Function | Description |
|----------|-------------|
| `validate_options(repeat, count_in_bars, metronome, timbre)` | Bounds for direct engine calls; returns the timbre's GM program (None for `score`) |
| `resolve_gains(parts, part_gains, preset, focus_part)` | One gain per selected part (preset base, `part_gains` overrides via `resolve_parts`), or None |
| `cc7_value(gain)` | `round(127 × gain / 2)` |
| `expand_repeats(score)` | Written repeats played out before clicks are laid (music21's export would do it anyway) |
| `repeat_music(score, times)` | Appends each part's bars `times − 1` more times; ties cut at the joins |
| `scale_tempo(score, factor)` | Scales `number` and `numberSounding` of every MetronomeMark; default 120 × factor when none |
| `add_clicks(score, count_in_bars, metronome)` | Shifts the music by the count-in, adds the wood-block click part (appended last) |
| `tune_midi(midi_file, *, percussion, gains, program, clicks)` | After export: click track on channel 10 (program 0), one channel per melodic part with gains, program changes for timbre, CC7 at tick 0 |

### `clip.py`

`starting_pitches` pieces (UX Wave 3 C13). No MCP imports.

| Function | Description |
|----------|-------------|
| `starting_pitches(musicxml, parts)` | Core `scores.first_pitches`, filtered with `resolve_parts` against the core's part list |
| `pitches_text(entries)` | `"S: D5, A: A4, T: F#4, B: D3"` (parts without notes left out) |
| `clip_midi(midi_numbers)` | Piano, 60 BPM: each note 1 quarter (1 s), then the chord for 2 s, velocity 80, no end delay |
| `clip_seconds(note_count)` | `note_count × 1 s + 2 s` (the chord) |
| `render_clip(midi_bytes, output_path, *, seconds)` | `synthesize_midi` into a temp WAV, then `downmix_wav(..., max_seconds=seconds + RELEASE_SECONDS)` to the target (new `audio/starting-pitches-<timestamp>.wav` only after rendering worked) |
| `downmix_wav(source, target, *, max_seconds)` | numpy: average channels, 63-tap windowed-sinc low-pass, linear resample to 16 kHz, cut at `max_seconds` with the last `RELEASE_SECONDS` (0.25 s) faded out, 16-bit mono via stdlib `wave`. FluidSynth renders about 2.6 s of release tail after the chord, which would push a 4-part clip to 275 KB |

### `presenter.py`

Turns results into `(content, structured_content)` for `get_parts`, `synthesize` and the two app-only
tools, and holds their output schemas. `content` of `get_parts`/`synthesize` is what the tools always
returned. No engine logic.

### `scorebook.py`

`ScoreBook`: MusicXML per `audio_id` for `get_score_xml`. It is kept in step with the artifact store by
construction: `get()` calls `store.info(id)` first (same TTL, same unknown-id error), `remember()` drops
entries the store has dropped and never holds more than the store's cap (64). It takes the store through a
getter, so tests can swap the store. No MCP imports.

### Practice Player flow

```
synthesize ──► synthesize_midi ──► WAV file ──► artifact_store.put ──► audio_id
          └──► describe_mix (engine) ──► parts[{id,name,included,gain}]
          └──► score_book.remember(audio_id, cut MusicXML)
app: read_audio_chunk(audio_id, offset, length) ──► chunk_payload(store) ──► base64 slice
app: get_score_xml(audio_id) ──► score_book.get ──► MusicXML
```

`server.py` registers `PRACTICE_PLAYER` (`ui://synth/practice-player`) in a `UiRegistry` over
`PackageAssetSource("synth_mcp")`; `meta_for()` drops the link while the HTML is not packaged.
`call_tool_result()` returns `CallToolResult` for the four structured tools (`_RESULT_TOOLS`);
`call_tool()` keeps returning the content blocks. `engine.describe_mix()` resolves part selection and
gains with the same functions as `extract_midi`, so the mixer shows what was rendered.

### `utils.py`

Input validation and path generation.

| Function | Description |
|----------|-------------|
| `validate_musicxml(xml_str)` | Check non-empty; parse with music21 |
| `validate_tempo_factor(value)` | Check 0.25 ≤ value ≤ 4.0 |
| `generate_output_path(path)` | Return the caller's path confined by `confine_output_path`, or a new `audio/output-<timestamp>.wav` in the output root (`paths.new_output_path`) |
| `confine_output_path(path, suffixes)` | Re-export of `sheet_music_mcp_core.paths.confine_output_path` (Wave 2) |

---

## Data Flow

### `synthesize` tool

```
call_tool("synthesize", {musicxml | musicxml_path, parts, tempo_factor, output_path})
  │
  ├─ references.load_score → MusicXML text (path: confined, size-checked, .mxl unzipped)
  ├─ utils: validate_musicxml
  ├─ utils: validate_tempo_factor (if provided)
  ├─ utils: generate_output_path
  │
  ├─ params.aliased(parts, part_ids)       (deprecated alias)
  ├─ engine: resolve_part_ids(musicxml, parts) → stable IDs ("P1", …)
  │     └─ PartSelectionError (INVALID_PARAMETER + choices) if a part matches nothing
  │
  ├─ engine: extract_midi(musicxml, part_ids, tempo_factor, **practice options given)
  │     ├─ practice.validate_options(repeat, count_in_bars, metronome, timbre)
  │     ├─ core measures.select_measures(musicxml, measures)   (B2)
  │     ├─ music21.converter.parseData(musicxml)
  │     ├─ select parts by position against music21_part_infos(score.parts)
  │     ├─ practice.resolve_gains(selected infos, part_gains, preset, focus_part)   (C8)
  │     ├─ deep-copy selected parts into new Score
  │     ├─ if the selected parts have no MetronomeMarks: copy the score's marks
  │     │     (usually only in the top part) into the first selected part, at their offsets
  │     ├─ if count-in or metronome: practice.expand_repeats(score)
  │     ├─ practice.repeat_music(score, repeat)                             (C9)
  │     ├─ practice.scale_tempo(score, tempo_factor)
  │     │     └─ mark.number and mark.numberSounding *= tempo_factor
  │     │     └─ if no marks: insert MetronomeMark(120 * tempo_factor) at measure 1
  │     ├─ practice.add_clicks(score, count_in_bars, metronome)             (C10)
  │     ├─ music21.midi.translate.streamToMidiFile(score)
  │     ├─ practice.tune_midi(...) if gains, timbre or clicks               (C8, C10, C11)
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

### `starting_pitches` tool

```
call_tool("starting_pitches", {musicxml | musicxml_path, parts, output_path})
  │
  ├─ references.load_score; utils: validate_musicxml; confine_output_path(output_path, .wav)
  ├─ clip.starting_pitches(musicxml, parts) → first_pitches entries (score order)
  ├─ payload = {text, parts, audio_path: null, duration_seconds: null}
  ├─ no pitched part → payload.audio_unavailable, return [json]
  ├─ clip.render_clip(clip.clip_midi(midis), output_path, seconds=clip.clip_seconds(len(midis)))
  │     └─ ProcessingError (no soundfont / FluidSynth / render failure)
  │           → payload.audio_unavailable = reason, return [json]   (not an error, W3-6)
  └─ return [json, audio_block(path) if ≤ 200 KB, file_link(path, "audio/wav")]
```

---

## Practice Track MIDI

- **Channels.** music21 gives parts with the same instrument one MIDI channel (keyed by program),
  so CC7 could not tell them apart. With gains, `tune_midi` moves every melodic track to its own
  channel (1–9, 11–16; more than 15 pitched parts → `INVALID_PARAMETER`). Score percussion stays on
  10. Without gains, a melodic track music21 put on channel 10 (it does when a score percussion
  part shares the "no program" key) moves to a free channel whenever `tune_midi` runs.
- **Track order.** Track 0 is music21's conductor track, then one per selected part in order,
  then the click part, which `add_clicks` appends last.
- **Count-in tempo.** music21's conductor track keeps a tempo or time signature only when met in
  ascending offset order, reading the first part first. The count-in's meter and tempo (the
  already scaled mark at the first bar) therefore go at offset 0 of the first part, not in the
  click part.
- **Clicks.** One click bar per music bar (after repeat expansion), beats from
  `TimeSignature.beatCount` / `beatDuration`; a pickup's missing start (`paddingLeft`) aligns its
  beats to the end of the bar. Notes 76 (beat 1) and 77; the track's program is set to 0.
- **Ties at repeat joins.** `repeat_music` drops the tie side that would cross a join (a
  `continue` becomes `start` or `stop`), so music21's `stripTies` never merges two passes.

### `get_parts` tool

```
call_tool("get_parts", {musicxml | musicxml_path})
  │
  ├─ references.load_score
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
    mark.number = mark.number * tempo_factor                  # when set
    mark.numberSounding = mark.numberSounding * tempo_factor  # when set

if no marks found:
    score.parts[0].measure(1).insert(0, MetronomeMark(number=120 * tempo_factor))
```

This scales time uniformly. Pitch is not affected because the MIDI note numbers are unchanged.
A bare `<sound tempo>` (how `select_measures` carries the tempo into a cut score) gives a mark with
`number` None and `numberSounding` set, and music21's MIDI export prefers `numberSounding`, so
both are scaled.

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

## Part Identification

music21 replaces `part.id` with the part's *name* (e.g. `"Soprano"`), repeats it for same-named
parts, and gives unnamed parts a new integer on every parse. The engine therefore never uses
`part.id`: `sheet_music_mcp_core.parts.music21_part_infos` gives each part its MusicXML
`<score-part id>` (`"P1"`), and parts are selected by position against that list.
`get_parts` reports these IDs. Requests are resolved with the shared resolver (ID, name or voice;
see [docs/conventions.md](../../docs/conventions.md#part-selection)).

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
| Practice option out of range or inconsistent; `measures` outside the score (with hint) | `INVALID_PARAMETER` |
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
| `sheet-music-mcp-core` | Shared error envelope, `ProcessingError` and handler wiring (input validation, error results); see [docs/conventions.md](../../docs/conventions.md#shared-core-library) |

**System library:** `libfluidsynth.so.3` (Linux) / `libfluidsynth.dylib` (macOS) must be installed separately. pyfluidsynth loads it via ctypes at import time; if missing, import fails and the server exits.

---

## Output Files

Auto-generated WAV paths use a timestamp, inside the output root (`SHEET_MUSIC_OUTPUT_ROOT`, default the
working directory), because the artifact store only accepts files there:

```
<output root>/audio/output-YYYYmmdd-HHMMSS-ffffff.wav
```

The folder is created (mode 0700) if needed; an existing name gets a counter, so a stored WAV is never
overwritten.

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
│       ├── practice.py   ← Practice-track steps (gains, repeat, clicks, timbre)
│       ├── clip.py       ← starting_pitches (text, clip MIDI, downmix)
│       ├── presenter.py  ← content + structuredContent, output schemas
│       ├── scorebook.py  ← MusicXML per audio_id, in step with the artifact store
│       ├── ui/assets/    ← practice-player.html, built by ui/ (gitignored, packaged)
│       └── utils.py      ← Validation, path generation
└── tests/
    ├── test_server.py
    ├── test_engine.py
    ├── test_utils.py
    ├── test_practice_midi.py, test_practice_server.py, test_starting_pitches.py
    ├── test_practice_player.py, test_scorebook.py, test_content_golden.py (+ golden/)
    ├── midi_helpers.py   ← MIDI bytes → events for assertions
    └── fixtures/         ← satb_4bars, six_eight, pickup_sound_tempo (.musicxml)
```
