# musicxml-abc-mcp Requirements

## Purpose

Convert between MusicXML and ABC notation. ABC is a compact, text-based music format that large language models can read and edit directly. This server enables AI-assisted score editing: MusicXML → ABC → Claude edits → ABC → MusicXML.

This server is a bridge tool rather than an end-user feature. It is used by the LLM client (Claude) to inspect and modify scores without handling verbose MusicXML directly.

---

## Functional Requirements

### FR-1 — MusicXML to ABC conversion

The server MUST convert a MusicXML document to ABC notation (standard v2.1).

- All parts MUST be included by default
- If a `part` filter is supplied (part ID, name or voice), only that part MUST appear in the output
- If the requested part matches no part, or several, the server MUST return `INVALID_PARAMETER` with the valid parts in `choices`
- The output MUST be valid ABC that music21 can parse back to a score

### FR-2 — ABC to MusicXML conversion

The server MUST convert an ABC notation string to a MusicXML document.

- The output MUST be valid MusicXML parseable by music21

### FR-3 — ABC validation

The server MUST accept an ABC string and return whether it is syntactically valid, along with any parse errors or warnings.

- Validation MUST NOT require a MusicXML reference
- Errors MUST include line number where available

### FR-3a — Score references (UX Wave 2)

Scores MAY be passed and returned as file paths instead of inline text
([conventions: Score References](../../docs/conventions.md#score-references)).

- `musicxml_to_abc` MUST accept exactly one of `musicxml` (text) and `musicxml_path` (a `.musicxml`,
  `.xml` or `.mxl` file). Both or neither MUST return `INVALID_PARAMETER`.
- A path MUST be read only inside the read roots (`SHEET_MUSIC_OUTPUT_ROOT`, the client's MCP roots,
  `SHEET_MUSIC_INPUT_ROOTS`); a path outside them MUST return `INVALID_PARAMETER` without revealing
  whether the file exists or echoing any of its content.
- `abc_to_musicxml` MUST take `return: "auto" | "path" | "inline"` (default `auto`). `auto` returns
  the text when it is at most `SHEET_MUSIC_INLINE_MAX_BYTES` (default 8192) UTF-8 bytes and
  otherwise writes `<output root>/scores/from-abc-<timestamp>.musicxml`, returning `musicxml_path`
  and a `score_summary` instead of `musicxml`, plus a resource link to the file. Inline output MUST
  be byte-identical to the pre-Wave-2 output.
- The server MUST expose the shared `describe_score` tool (title, key, time, tempo, parts with
  `P1`… IDs, ranges, measures, duration) taking `musicxml` or `musicxml_path`.

### FR-3b — Measure ranges (UX Wave 3)

`musicxml_to_abc` MAY export only part of a score
([conventions: Measure Ranges](../../docs/conventions.md#measure-ranges)).

- `measures: [start, end]` MUST select the bars whose **printed** numbers are in the inclusive
  range (a pickup is 0, `"12a"` belongs to 12), in written order, in every part.
- The score MUST be cut with `sheet_music_mcp_core.measures.select_measures` before music21 parses
  it, so each tune's `K:`, `M:` and `Q:` are the key, time and tempo in force at `start`.
- A reversed range, a range outside the score or one holding no bar MUST return
  `INVALID_PARAMETER` with a `hint` naming the score's first and last bar numbers
  (`"This score has measures 1–32."`).
- Without `measures` the output MUST be unchanged.

### FR-4 — Capability reporting

The server MUST expose a tool that returns:

- Server name and version
- Supported input and output formats
- Backend name and version
- ABC standard version (2.1)
- List of available tools

---

## Non-Functional Requirements

### NFR-1 — Round-trip fidelity

A MusicXML → ABC → MusicXML round-trip MUST preserve note pitches and durations. The note count in the output MUST be within ±2% of the input note count.

The following are NOT required to survive a round-trip:
- Dynamic markings (forte, piano, crescendo, etc.)
- Complex articulations (trills, ornaments, fingerings)
- Lyrics
- Rehearsal marks

These losses MUST be documented in the tool response via the `warnings` field and in the README.

### NFR-2 — Compactness

The ABC output for a typical 4-part SATB score MUST be substantially shorter than the MusicXML input. This is the key property that makes the format useful for LLM editing.

### NFR-3 — ABC standard

ABC output MUST conform to ABC standard v2.1 octave conventions:
- `C` (uppercase) = C4 (middle C)
- `c` (lowercase) = C5
- Apostrophe raises one octave: `c'` = C6
- Comma lowers one octave: `C,` = C3

### NFR-4 — No system dependencies

All conversion MUST use pure Python libraries. No external tools or processes are required.

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

### IR-2 — Tool: `musicxml_to_abc`

```
Input:
  musicxml       string  one of   MusicXML document as a string
  musicxml_path  string  one of   path to a .musicxml, .xml or .mxl file (preferred)
  part       string  optional  filter output to this part: ID, name or voice (e.g. "P1", "Soprano", "S")
  part_id    string  optional  deprecated alias of `part` (removed next minor)
  measures   [int, int]  optional  inclusive [start, end] printed bar numbers (pickup 0); omit for all

Output:
  abc              string        ABC notation string
  parts_included   list[string]  MusicXML score-part ids of the parts included (e.g. "P1")
  warnings         list[string]  known lossy conversions (e.g. dynamics dropped)
```

### IR-3 — Tool: `abc_to_musicxml`

```
Input:
  abc     string  required  ABC notation string
  return  string  optional  "auto" (default) | "path" | "inline"

Output (inline: "inline", or "auto" with at most 8192 bytes of MusicXML):
  musicxml  string        MusicXML document as a string
  warnings  list[string]

Output (path: "path", or "auto" above the limit):
  musicxml_path  string        absolute path of <output root>/scores/from-abc-<timestamp>.musicxml
  warnings       list[string]
  score_summary  object        {title, parts: [{id, name, range}], measures, key, time, tempo_bpm}
  content[1]     ResourceLink  the written file (application/vnd.recordare.musicxml+xml)
```

The annotation preset is `WRITES_FILE` (it writes in `auto` mode; plan decision W2-5).

### IR-4 — Tool: `validate_abc`

```
Input:
  abc  string  required  ABC notation string to validate

Output:
  valid     boolean
  errors    list[string]  parse errors with line numbers where available
  warnings  list[string]  non-fatal issues (e.g. missing recommended headers)
```

### IR-5 — Tool: `list_capabilities`

```
Output:
  server           string
  version          string
  input_formats    list[string]   ["musicxml", "mxl", "abc"]
  output_formats   list[string]   ["abc", "musicxml"]
  input_parameters list[string]   ["musicxml", "musicxml_path", "measures"]
  tools            list[string]   includes "describe_score"
  backend          string         "music21"
  backend_version  string
  abc_standard     string         "2.1"
```

### IR-5a — Tool: `describe_score`

The shared tool from `sheet_music_mcp_core.references` (`READ_ONLY`, title "Describe score").

```
Input:
  musicxml       string  one of  MusicXML text
  musicxml_path  string  one of  path to a .musicxml, .xml or .mxl file

Output:
  title, composer, key, time, tempo_bpm,
  parts: [{id, name, abbreviation, clef, range: {low, high}}],
  measures, has_lyrics, duration_quarters, duration_seconds
```

### IR-5b — MCP Apps: ABC Workbench (`structuredContent`)

`musicxml_to_abc`, `abc_to_musicxml` and `validate_abc` declare an `output_schema` and return
`structuredContent` next to the unchanged `content` (`tests/test_content_golden.py` pins `content`).
Errors keep the `{error, error_code}` content, set `isError: true` and carry no `structuredContent`.
Shapes (`presenter.py`):

```
musicxml_to_abc (ABC_OUTPUT_SCHEMA):
  abc_id, abc, parts_included[], warnings[]
  abc_id is new on every call, even for identical input (AC-A2); it is not in `content`.
abc_to_musicxml (CONVERSION_OUTPUT_SCHEMA):
  warnings[], delivery "inline"|"path", musicxml_bytes
  The score itself is never in structuredContent (proposal 6.3 rule 4): the model gets it in
  `content`, as before.
validate_abc (VALIDATION_OUTPUT_SCHEMA): the result `content` already carries
  valid, errors[], warnings[]
```

`musicxml_to_abc` and `abc_to_musicxml` link `ui://abc/workbench` (`_meta.ui.resourceUri`) only while
`src/musicxml_abc_mcp/ui/assets/abc-workbench.html` is packaged; otherwise they carry no `_meta.ui`
and the resource is not listed. `validate_abc` stays model-visible and is the call the app debounces.

**`get_abc`** (app-only, `_meta.ui.visibility: ["app"]`, listed only to clients that support MCP
Apps; `tools/call` still finds it). Input `{abc_id?}` and nothing else (no paths,
`additionalProperties: false`); omitted `abc_id` means the latest export. Output is
`ABC_OUTPUT_SCHEMA`. Ids live in an in-process `AbcStore` (32 entries, 1 h TTL, oldest evicted,
lost on restart); an unknown, expired or non-string id, or an empty store, is `INVALID_PARAMETER`
with a hint, and the id is not echoed. `content` is a one-line note, not the ABC.

### IR-6 — Error response format

```json
{"error": "<human-readable message>", "error_code": "<CODE>"}
```

| Code | Condition |
|------|-----------|
| `INVALID_INPUT` | MusicXML parse error; ABC parse error; a score file that is not well-formed MusicXML or a bad `.mxl` |
| `INVALID_PARAMETER` | Requested part not found, or ambiguous (`choices` lists the parts); both or neither of `musicxml` / `musicxml_path`; a score path outside the read roots or with the wrong suffix; unknown `return` mode; `measures` reversed, malformed or outside the score (`hint` names the score's bars) |
| `FILE_NOT_FOUND` | `musicxml_path` inside the roots does not exist |
| `FILE_TOO_LARGE` | `musicxml_path` larger than `SHEET_MUSIC_MAX_SCORE_BYTES` (default 16 MiB) |
| `PROCESSING_FAILED` | music21 conversion failure |

---

## Constraints

- Language: Python 3.11+
- Package manager: uv; install dev extras with `uv sync --extra dev` (not `--group dev`)
- Score parsing and ABC→MusicXML: music21
- ABC output: custom serializer (music21 9.x has no ABC write support — `ConverterABC.registerOutputExtensions` is empty)
- Part IDs are the MusicXML `<score-part id>` (e.g. "P1"), never music21's `part.id` (which is the part name, repeated for same-named parts, or a per-parse integer for unnamed parts); see [conventions: Part Selection](../../docs/conventions.md#part-selection)

---

## Testing Requirements

### TR-1 — Unit tests

Unit tests MUST cover:

- MusicXML parse error path
- ABC parse error path
- Unknown part error with `choices`; selection by ID, name and voice, same-named and unnamed parts (`tests/test_part_selection.py`)
- `validate_abc` with valid and invalid ABC strings
- `list_capabilities` response schema
- ABC octave encoding (middle C = `C`)
- Score references (`tests/test_score_references.py`): path equals inline, `.mxl`, both/neither,
  paths outside the roots (no content leak), `return` modes of `abc_to_musicxml`, round trip of the
  written file, `describe_score`

- ABC Workbench (`tests/test_abc_workbench.py`, `tests/test_abc_store.py`,
  `tests/test_content_golden.py`): tool linking with and without a UI build, resource list/read,
  output schemas, no score in `structuredContent`, fresh `abc_id` per call, app-only `get_abc`
  visibility per client kind, no paths accepted, error envelope without `structuredContent`,
  store TTL and bound

Unit tests MUST mock music21 `converter.parse`.

### TR-2 — Integration tests

Integration tests MUST:

- Be marked `@pytest.mark.integration`
- Perform a real MusicXML → ABC → MusicXML round-trip on a simple fixture
- Assert note count in the output is within ±2% of the input
- Perform the same round-trip on a 4-part SATB fixture
- Assert all four parts appear in the output MusicXML
- Assert the `warnings` field is populated when dynamic markings are present in the input

### TR-3 — Test fixtures

A simple MusicXML fixture and a 4-part SATB MXL fixture MUST be committed to `tests/fixtures/`.
