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

### FR-5a — Score references

`get_parts`, `synthesize` and `describe_score` MUST accept the score either inline (`musicxml`) or
as a file path (`musicxml_path`: `.musicxml`, `.xml` or compressed `.mxl`). Exactly one of the two
is required. Paths are read through `sheet_music_mcp_core.references.load_score`, which confines
them to the read roots (output root, the client's MCP roots, `SHEET_MUSIC_INPUT_ROOTS`) and never
echoes file contents in errors ([conventions: Score References](../../docs/conventions.md#score-references)).
A path call MUST give the same result as the inline call with the same score.

### FR-5b — Score description

The server MUST expose the shared `describe_score` tool (`sheet_music_mcp_core.references`):
title, composer, key, time, tempo, parts (ID, name, abbreviation, clef, range), measures, lyrics
presence and duration, parsed without music21.

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

### IR-1a — Tool metadata and server instructions

Every tool sets a human-readable `title` and an annotation preset from `sheet-music-mcp-core`
(see [conventions: Tool Annotations and Titles](../../docs/conventions.md#tool-annotations-and-titles)).
The per-tool table of titles and presets is `tests/test_tool_metadata.py`. The server sends
`instructions` at initialize ([conventions: Server Instructions](../../docs/conventions.md#server-instructions)).

### IR-2 — Tool: `get_parts`

```
Input (exactly one of musicxml / musicxml_path, JSON Schema oneOf):
  musicxml       string  MusicXML document as a string
  musicxml_path  string  path to a .musicxml, .xml or .mxl file inside the read roots

Output:
  parts  list[object]
    id             string   MusicXML score-part id (e.g. "P1"), stable across calls
    name           string   e.g. "Soprano"
    measure_count  integer
```

### IR-3 — Tool: `synthesize`

```
Input (exactly one of musicxml / musicxml_path, JSON Schema oneOf):
  musicxml      string        MusicXML document as a string
  musicxml_path string        path to a .musicxml, .xml or .mxl file inside the read roots
  parts         list[string]  optional  parts to include as IDs, names or voices
                                        (e.g. "P1", "Soprano", "S"); default: all parts
  part_ids      list[string]  optional  deprecated alias of `parts` (removed next minor)
  tempo_factor  float         optional  0.25–4.0; default: 1.0
  output_path   string        optional  path to write WAV inside SHEET_MUSIC_OUTPUT_ROOT
                                        (.wav, .mid or .midi; always written as WAV);
                                        auto-generated in /tmp/synth-mcp-<uid>/ if omitted

Output:
  audio_path        string   path of written WAV file
  format            string   "wav"
  duration_seconds  float
  parts_included    list[string]
  tempo_factor      float
```

Content blocks: `content[0]` is the JSON text above. On success it is followed by a
`resource_link` to the WAV file (`file://` URI of the resolved path, MIME type `audio/wav`;
[conventions](../../docs/conventions.md#result-content)). Errors return only the error JSON.

### IR-3a — Tool: `describe_score`

The shared tool from `sheet_music_mcp_core.references` (`DESCRIBE_SCORE_TOOL`, title "Describe
score", `READ_ONLY`). Input: exactly one of `musicxml` / `musicxml_path`. Output:

```
  title, composer          string | null
  key, time                string | null   e.g. "D major", "3/4"
  tempo_bpm                number | null
  parts                    list[{id, name, abbreviation, clef, range: {low, high} | null}]
  measures                 integer
  has_lyrics               boolean
  duration_quarters        number
  duration_seconds         number | null
```

### IR-4 — Tool: `list_capabilities`

```
Output:
  server               string
  version              string
  input_formats        list[string]   ["musicxml", "mxl"]   (.mxl via musicxml_path only)
  input_parameters     list[string]   ["musicxml", "musicxml_path"]   (give exactly one)
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
| `SHEET_MUSIC_OUTPUT_ROOT` | No | Folder `output_path` must be inside, and the first read root for `musicxml_path` (default: working directory) |
| `SHEET_MUSIC_INPUT_ROOTS` | No | Extra folders `musicxml_path` may read from (`:`-separated; `;` on Windows) |
| `SHEET_MUSIC_MAX_SCORE_BYTES` | No | Largest score file read, including an `.mxl` member uncompressed (default 16 MiB) |

If `SYNTH_SOUNDFONT_PATH` is unset or points to a non-existent file, the server MUST start successfully but MUST return a `PROCESSING_FAILED` error with download instructions when `synthesize` is called.

### IR-6 — Error response format

```json
{"error": "<human-readable message>", "error_code": "<CODE>"}
```

| Code | Condition |
|------|-----------|
| `INVALID_INPUT` | MusicXML cannot be parsed; no parts found; bad `.mxl` |
| `INVALID_PARAMETER` | Unknown part ID; tempo_factor out of range; both or neither of `musicxml` / `musicxml_path`; path outside the read roots or with another suffix |
| `FILE_NOT_FOUND` | `musicxml_path` inside the roots does not exist |
| `FILE_TOO_LARGE` | `musicxml_path` larger than `SHEET_MUSIC_MAX_SCORE_BYTES` |
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
- Unknown part error path (`INVALID_PARAMETER` with `choices` and `hint`)
- Part selection by ID, name and voice, same-named and unnamed parts (`tests/test_part_selection.py`)
- Missing soundfont error path
- `list_capabilities` response schema
- Output path auto-generation
- Score references (`tests/test_score_references.py`): a `musicxml_path` call (`.musicxml` and
  `.mxl`) gives the same result as the inline call; both or neither → `INVALID_PARAMETER`; paths
  outside the roots → `INVALID_PARAMETER` without file content; `describe_score`

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
