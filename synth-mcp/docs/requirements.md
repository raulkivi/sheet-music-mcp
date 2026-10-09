# synth-mcp Requirements

## Purpose

Synthesize audio from a MusicXML score. Enable choir singers to hear their individual voice part (Soprano, Alto, Tenor, Bass) or any combination, at an adjustable tempo.

Covers **Goal 3**: Play sheet music in individual voices or combined.

---

## Functional Requirements

### FR-1 — Part listing

The server MUST parse a MusicXML document and return a list of all voice parts it contains.

Each part entry MUST include:

- Part ID (as used by `synthesize`)
- Part name (e.g. "Soprano")
- Number of measures

### FR-2 — Full-score synthesis

The server MUST synthesize a WAV file from a MusicXML score using all parts when no part selection is specified.

### FR-3 — Part selection

The server MUST accept a list of part IDs and synthesize only those parts.

- If a supplied part ID does not exist in the score, the server MUST return an error identifying the invalid ID and listing valid IDs.

### FR-4 — Tempo control

The server MUST accept a `tempo_factor` parameter and scale the score tempo accordingly.

- Range: 0.25–4.0 (inclusive)
- Default: 1.0 (score tempo)
- The score tempo applies to every part selection, including a lower part exported alone when
  the tempo marking is written only in the top part
- Values below 1.0 slow down the playback; values above 1.0 speed it up
- Pitch MUST NOT be affected by tempo changes
- Values outside the valid range MUST be rejected with a clear error

### FR-5 — Output path

The server MUST write the WAV file to the specified output path. If no path is provided, the server MUST auto-generate a path in the system temporary directory.

The response MUST include the final output path.

### FR-6 — Capability reporting

The server MUST expose a tool that returns:

- Server name and version
- Supported input and output formats
- FluidSynth availability flag and version
- Soundfont load status and path
- List of available tools

---

## Non-Functional Requirements

### NFR-1 — Output format

Audio output MUST be WAV (PCM, 44100 Hz sample rate). MP3 output is out of scope; callers may convert using ffmpeg.

### NFR-2 — Audio quality

Output audio MUST be usable for choir practice. The synthesized notes MUST correspond to the correct pitches at the correct durations. Loss of dynamics and complex articulations is acceptable.

### NFR-3 — Performance

Synthesis of a typical 32-measure SATB score MUST complete within 30 seconds on standard hardware.

### NFR-4 — Offline operation

All synthesis MUST run locally using the locally-installed FluidSynth library and the soundfont file at `SYNTH_SOUNDFONT_PATH`. No network access is permitted.

### NFR-5 — Transport

The server MUST communicate via MCP stdio transport.

---

## Interface Requirements

### IR-1 — MCP protocol

The server MUST implement MCP using `mcp.server.stdio.stdio_server()`.

### IR-2 — Tool: `get_parts`

```
Input:
  musicxml  string  required  MusicXML document as a string

Output:
  parts  list[object]
    id             string   part identifier (use this in synthesize.part_ids)
    name           string   e.g. "Soprano"
    measure_count  integer
```

### IR-3 — Tool: `synthesize`

```
Input:
  musicxml      string        required  MusicXML document as a string
  part_ids      list[string]  optional  parts to include; default: all parts
  tempo_factor  float         optional  0.25–4.0; default: 1.0
  output_path   string        optional  path to write WAV; auto-generated if omitted

Output:
  audio_path        string   path of written WAV file
  format            string   "wav"
  duration_seconds  float
  parts_included    list[string]
  tempo_factor      float
```

### IR-4 — Tool: `list_capabilities`

```
Output:
  server               string
  version              string
  input_formats        list[string]   ["musicxml"]
  output_formats       list[string]   ["wav"]
  tools                list[string]
  backend              string         "fluidsynth"
  backend_version      string
  fluidsynth_available boolean
  soundfont_loaded     boolean
  soundfont_path       string | null
```

### IR-5 — Environment variable

| Variable | Required | Description |
|----------|----------|-------------|
| `SYNTH_SOUNDFONT_PATH` | Yes | Absolute path to an SF2 soundfont file |

If `SYNTH_SOUNDFONT_PATH` is unset or points to a non-existent file, the server MUST start successfully but MUST return a `PROCESSING_FAILED` error with download instructions when `synthesize` is called.

### IR-6 — Error response format

```json
{"error": "<human-readable message>", "error_code": "<CODE>"}
```

| Code | Condition |
|------|-----------|
| `INVALID_INPUT` | MusicXML cannot be parsed; no parts found |
| `INVALID_PARAMETER` | Unknown part ID; tempo_factor out of range |
| `PROCESSING_FAILED` | FluidSynth not installed; soundfont not found; synthesis error |

---

## Constraints

- Language: Python 3.11+
- Package manager: uv
- Score parsing: music21
- Synthesis: pyfluidsynth (Python bindings for libfluidsynth)
- No subprocess calls to a FluidSynth CLI binary; synthesis runs in-process via pyfluidsynth
- `audio.driver=file` mode + `fluid_player_join()` for file rendering (not raw PCM streaming)
- music21 part identification uses `part.id` (the part name) not the XML `<part id>` attribute

---

## Testing Requirements

### TR-1 — Unit tests

Unit tests MUST cover:

- Part extraction from a SATB MusicXML fixture
- `tempo_factor` validation (boundary values: 0.24, 0.25, 4.0, 4.01)
- Unknown `part_id` error path
- Missing soundfont error path
- `list_capabilities` response schema
- Output path auto-generation

Unit tests MUST mock pyfluidsynth. They MUST NOT synthesize real audio.

### TR-2 — Integration tests

Integration tests MUST:

- Be marked `@pytest.mark.integration`
- Require `SYNTH_SOUNDFONT_PATH` to be set; skip automatically if unset
- Synthesize a real WAV from an MXL fixture
- Assert the output WAV file exists and has non-zero size
- Assert `duration_seconds > 0` in the response

### TR-3 — Test fixtures

MXL fixtures SHOULD be shared from `../omr-mcp/test_samples/pdmx_satb_samples/mxl/`. Do not duplicate them.
