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

The server MUST write the WAV file to the specified output path. If no path is provided, the server MUST auto-generate a new, unused path `audio/output-<timestamp>.wav` inside the output root (the artifact store only accepts files there).

**Behaviour change (MCP Apps):** the default output moved from `/tmp/synth-mcp-<uid>/output_*.wav` to `<output root>/audio/output-<timestamp>.wav`, where the output root is `SHEET_MUSIC_OUTPUT_ROOT` (default: the working directory). Callers that read the default location must use the `audio_path` in the result. Each render is written to a temporary file beside the target and renamed onto it, so a path always gets a new inode and an `audio_id` of an earlier WAV there can never read the new bytes.

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

### FR-5c — Practice tracks (UX Wave 3)

`synthesize` MUST accept these optional practice options
([conventions: Practice Audio](../../docs/conventions.md#practice-audio),
[Measure Ranges](../../docs/conventions.md#measure-ranges)). Each default MUST give the same MIDI
as without the option: no CC7, no program change, no clicks, the whole score.

- **`measures: [start, end]`** (B2): inclusive printed bar numbers (pickup = 0). The score is cut
  with core `select_measures` before music21 parses it, keeping the key, time, clef and tempo in
  force at `start`. Out of range or reversed → `INVALID_PARAMETER` with the score's range as hint.
- **`repeat`** 1–20 (C9): the selected bars are played this many times; ties are cut at the joins.
- **`count_in_bars`** 0–4 and **`metronome`** (C10): wood-block clicks on MIDI channel 10, GM 76
  on beat 1 and 77 on other beats, beats as music21 counts them (6/8 has two). The count-in uses
  the time signature and scaled tempo in force at the first played bar and moves the music later
  by its length; `metronome` clicks every beat of the music too. No melodic track uses channel 10.
- **`timbre`** `score | piano | choir | organ` (C11): GM program 0, 52 or 19, one program change
  at tick 0 on every melodic channel; `score` keeps the score's instruments.
- **`part_gains`**, **`preset`** and **`focus_part`** (C8): one CC7 at tick 0 per selected part,
  `round(127 × gain / 2)`. Presets: learning focus 1.5 / others 0.5, karaoke focus 0 / others 1.0,
  equal 1.0; `part_gains` entries (part ID, name or voice, 0.0–2.0) override them, other parts get
  1.0. With gains each melodic part gets its own MIDI channel (at most 15 pitched parts).
  `learning` / `karaoke` without `focus_part`, an unknown `focus_part` or `part_gains` key, or
  `focus_part` without a preset → `INVALID_PARAMETER` (with the part `choices` where a part is
  missing or unknown).
- `tempo_factor` also scales a tempo given only as `<sound tempo>` (music21 `numberSounding`),
  which is how `select_measures` carries the tempo into a cut score.

### FR-5d — Starting pitches (UX Wave 3 C13)

`starting_pitches` MUST return each selected part's first sounding note as text
(`"S: D5, A: A4, T: F#4, B: D3"`, from core `scores.first_pitches`, parts without notes left out)
and, when FluidSynth and a soundfont work, a piano clip: each note for 1 s in score order, then
the chord for 2 s, velocity 80, written as mono 16 kHz 16-bit WAV. The render is cut 0.25 s after
the chord (faded out), dropping FluidSynth's long release tail. Without audio the result MUST
still succeed, with `"audio_path": null` and `"audio_unavailable"` (decision W3-6).

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
                                        auto-generated as <output root>/audio/output-<timestamp>.wav if omitted
                                        (behaviour change: earlier releases used /tmp/synth-mcp-<uid>/)
  measures      [int, int]    optional  inclusive printed bar numbers; default: whole score
  repeat        integer       optional  1–20; default: 1
  count_in_bars integer       optional  0–4; default: 0
  metronome     boolean       optional  default: false
  timbre        string        optional  score | piano | choir | organ; default: score
  part_gains    object        optional  part (ID, name or voice) → number 0.0–2.0
  preset        string        optional  learning | karaoke | equal
  focus_part    string        optional  part (ID, name or voice); required by learning/karaoke

Output:
  audio_path        string   path of written WAV file
  format            string   "wav"
  duration_seconds  float
  parts_included    list[string]
  tempo_factor      float
  <practice option> as given  each practice option the caller passed, echoed back
```

Content blocks: `content[0]` is the JSON text above. On success it is followed by a
`resource_link` to the WAV file (`file://` URI of the resolved path, MIME type `audio/wav`;
[conventions](../../docs/conventions.md#result-content)). Errors return only the error JSON.

### IR-3c — MCP Apps: Practice Player (`structuredContent`)

`synthesize` and `get_parts` declare an `output_schema` and return `structuredContent` next to the
unchanged `content` (`tests/test_content_golden.py` pins `content`, AC-S4). Errors keep the
`{error, error_code}` content, set `isError: true` and carry no `structuredContent`. Shapes
(`presenter.py`):

```
synthesize (SYNTH_OUTPUT_SCHEMA):
  audio_id          opaque handle of the stored WAV (kind audio/wav); never a path
  duration_seconds  as in content (rounded to 0.01)
  sample_rate, channels, byte_length   read from the written WAV file
  parts[]           every part of the score, in score order:
                    {id, name, included, gain}
                    included = the engine rendered it; gain = the volume it used (1.0 without
                    part_gains/preset; preset and part_gains resolved as for the MIDI). A part left
                    out reports gain 0.0.
  tempo_factor      number (1.0 when not given)
get_parts: {parts: [{id, name, measure_count}]}, the same data as content
```

`synthesize` links `ui://synth/practice-player` (`_meta.ui.resourceUri`) only while
`src/synth_mcp/ui/assets/practice-player.html` is packaged; otherwise it carries no `_meta.ui` and the
resource is not listed. After the WAV is written, `synthesize` stores it (`artifact_store.put`) and
remembers the score the audio was made from (the `measures` cut, if any) in `ScoreBook`.

**`read_audio_chunk`** (app-only, `_meta.ui.visibility: ["app"]`, listed only to clients that support
MCP Apps; `tools/call` still finds it). Input `{audio_id, offset >= 0, length 1..1 MiB}` and nothing
else (`additionalProperties: false`, no paths). Output `chunk_payload(...)`:
`{artifact_id, offset, length, byte_length, eof, data_b64}`; chunks over `[0, byte_length)` reassemble
to the WAV (AC-S3). `content` is one short line, never the base64. Unknown or expired id, or a WAV that
vanished: `INVALID_PARAMETER` (AC-S2).

**`get_score_xml`** (app-only). Input `{audio_id}`; output `{audio_id, musicxml}`. Unknown or expired
id: `INVALID_PARAMETER`. `content` is a one-line note, not the document.

Ids and scores live for one hour (`DEFAULT_TTL_SECONDS`), at most 64 at a time, and are lost on restart.

### IR-3b — Tool: `starting_pitches`

Title "Play starting pitches", `WRITES_FILE`.

```
Input (exactly one of musicxml / musicxml_path, JSON Schema oneOf):
  musicxml       string        MusicXML document as a string
  musicxml_path  string        path to a .musicxml, .xml or .mxl file inside the read roots
  parts          list[string]  optional  parts as IDs, names or voices; default: all parts
  output_path    string        optional  .wav inside SHEET_MUSIC_OUTPUT_ROOT; default:
                                         <output root>/audio/starting-pitches-<timestamp>.wav

Output (content[0]):
  text               string         "S: D5, A: A4, T: F#4, B: D3"
  parts              list[{id, name, label, pitch}]   pitch null for a part without notes
  audio_path         string | null
  duration_seconds   number | null
  audio_unavailable  string         only when there is no audio: the reason
```

Then, with audio: an `audio` block (`audio/wav`) when the WAV is at most 200 KB (a 4-part clip
is 6.25 s, about 200,000 bytes; 5 or more parts are only linked), and a `resource_link` to the WAV. Without audio: no other blocks, not an error.

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
  input_parameters     list[string]   ["musicxml", "musicxml_path"] (give exactly one), then
                                      synthesize's practice options: measures, repeat,
                                      count_in_bars, metronome, timbre, part_gains, preset,
                                      focus_part
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
| `INVALID_PARAMETER` | Unknown part ID; tempo_factor out of range; a practice option out of range or inconsistent (see FR-5c); `measures` outside the score (with a `hint`); both or neither of `musicxml` / `musicxml_path`; path outside the read roots or with another suffix |
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
- Practice tracks at MIDI level with `music21.midi.MidiFile` (`tests/test_practice_midi.py`,
  `tests/test_practice_server.py`): gains and presets (CC7), measures, repeat, count-in and
  metronome clicks, timbre, defaults byte-identical
- `starting_pitches` (`tests/test_starting_pitches.py`): text, clip MIDI, downmix, inline audio vs
  link, no-soundfont result

Unit tests MUST mock pyfluidsynth. They MUST NOT synthesize real audio.

- Practice Player (`tests/test_practice_player.py`, `tests/test_scorebook.py`, `tests/test_content_golden.py`): tool linking with and
  without a packaged page, resource list/read, `structuredContent` against the schemas, the app-only tools (no paths,
  unknown/expired id), chunk reassembly, `content` identical to the pre-Apps golden file

### TR-2 — Integration tests

Integration tests MUST:

- Be marked `@pytest.mark.integration`
- Require `SYNTH_SOUNDFONT_PATH` to be set; skip automatically if unset
- Synthesize a real WAV from an MXL fixture
- Assert the output WAV file exists and has non-zero size
- Assert `duration_seconds > 0` in the response

### TR-3 — Test fixtures

MXL fixtures SHOULD be shared from `../omr-mcp/test_samples/pdmx_satb_samples/mxl/`. Do not duplicate them.
