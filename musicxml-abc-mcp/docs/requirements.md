# musicxml-abc-mcp Requirements

## Purpose

Convert between MusicXML and ABC notation. ABC is a compact, text-based music format that large language models can read and edit directly. This server enables AI-assisted score editing: MusicXML → ABC → Claude edits → ABC → MusicXML.

This server is a bridge tool rather than an end-user feature. It is used by the LLM client (Claude) to inspect and modify scores without handling verbose MusicXML directly.

---

## Functional Requirements

### FR-1 — MusicXML to ABC conversion

The server MUST convert a MusicXML document to ABC notation (standard v2.1).

- All parts MUST be included by default
- If a `part_name` filter is supplied, only that part MUST appear in the output
- If the requested part name does not exist in the score, the server MUST return an error listing valid part names
- The output MUST be valid ABC that music21 can parse back to a score

### FR-2 — ABC to MusicXML conversion

The server MUST convert an ABC notation string to a MusicXML document.

- The output MUST be valid MusicXML parseable by music21

### FR-3 — ABC validation

The server MUST accept an ABC string and return whether it is syntactically valid, along with any parse errors or warnings.

- Validation MUST NOT require a MusicXML reference
- Errors MUST include line number where available

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

### IR-2 — Tool: `musicxml_to_abc`

```
Input:
  musicxml   string  required  MusicXML document as a string
  part_name  string  optional  filter output to this part name (e.g. "Soprano")

Output:
  abc              string        ABC notation string
  parts_included   list[string]  part names included in the output
  warnings         list[string]  known lossy conversions (e.g. dynamics dropped)
```

### IR-3 — Tool: `abc_to_musicxml`

```
Input:
  abc  string  required  ABC notation string

Output:
  musicxml  string        MusicXML document as a string
  warnings  list[string]
```

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
  input_formats    list[string]   ["musicxml", "abc"]
  output_formats   list[string]   ["abc", "musicxml"]
  tools            list[string]
  backend          string         "music21"
  backend_version  string
  abc_standard     string         "2.1"
```

### IR-6 — Error response format

```json
{"error": "<human-readable message>", "error_code": "<CODE>"}
```

| Code | Condition |
|------|-----------|
| `INVALID_INPUT` | MusicXML parse error; ABC parse error |
| `INVALID_PARAMETER` | Requested part name not found in score |
| `PROCESSING_FAILED` | music21 conversion failure |

---

## Constraints

- Language: Python 3.11+
- Package manager: uv; install dev extras with `uv sync --extra dev` (not `--group dev`)
- Score parsing and ABC→MusicXML: music21
- ABC output: custom serializer (music21 9.x has no ABC write support — `ConverterABC.registerOutputExtensions` is empty)
- Part identification uses the part name (e.g. "Soprano"), extracted from `<part-name>` in MusicXML — not the XML `<part id>` attribute

---

## Testing Requirements

### TR-1 — Unit tests

Unit tests MUST cover:

- MusicXML parse error path
- ABC parse error path
- Unknown part name error
- `validate_abc` with valid and invalid ABC strings
- `list_capabilities` response schema
- ABC octave encoding (middle C = `C`)

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
