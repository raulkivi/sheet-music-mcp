# omr-mcp Requirements

## Purpose

Convert photographs or scans of printed sheet music into MusicXML documents. This is the entry point of the sheet-music-mcp pipeline — its output feeds every other server.

Covers **Goal 1**: Digitize paper sheet music (photograph → digital score).

---

## Functional Requirements

### FR-1 — Single image recognition

The server MUST accept a single sheet music image and return a valid MusicXML string.

- Accepted input forms: absolute file path to a PNG or JPEG file; base64-encoded image data with MIME type
- The returned MusicXML MUST be a complete `<score-partwise>` document
- Processing time MUST be under 30 seconds for a typical single-page score on CPU hardware

### FR-2 — Save result to file

The server MUST accept an output file path and write the MusicXML to disk, returning the written path.

### FR-3 — Multi-page recognition

The server MUST accept a list of image paths (one per page) and merge the results into a single MusicXML document.

- Pages MUST be merged in the order supplied
- The merged document MUST be a single `<score-partwise>` with all pages' measures appended

### FR-4 — Capability reporting

The server MUST expose a tool that returns:

- Server name and version
- Supported input formats (PNG, JPEG)
- Output format (MusicXML)
- OMR engine name and version (primary/default engine)
- Availability status of each selectable OMR engine (see FR-6)
- List of available tools

### FR-6 — Engine selection

`recognize_sheet`, `recognize_sheet_to_file`, and `recognize_sheets` MUST accept an optional
`engine` parameter selecting the OMR backend:

- `"oemer"` (default) — fast, in-process; flattens multi-staff (SATB) scores into a single
  sequential part instead of separate simultaneous parts (see docs/HANDOVER.md for the confirmed
  root cause) — real data loss for choir scores, not a benign modeling difference.
- `"audiveris"` — correctly separates multi-staff scores into simultaneous parts. Requires 300+ DPI
  source images (unlike oemer, which is DPI-insensitive — see docs/HANDOVER.md); downloads a
  larger engine (~80 MB) on first use; runs as a subprocess rather than in-process.

An unrecognized `engine` value MUST return `{"error": ..., "error_code": "INVALID_PARAMETER"}`.

### FR-5 — Input validation

The server MUST reject input that fails the following checks and return a descriptive error:

| Check | Condition |
|-------|-----------|
| File existence | File path must point to an existing file |
| File format | File extension and MIME type must be PNG or JPEG |
| Base64 validity | Base64 string must decode without error |
| Image readability | Pillow must be able to open the decoded image |

---

## Non-Functional Requirements

### NFR-1 — Accuracy

The OMR engine MUST correctly recognize standard Western staff notation including: noteheads, stems, beams, rests, clefs, key signatures, time signatures, bar lines, and accidentals.

Accuracy on clean, printed scores (300+ DPI) MUST be sufficient for practical choir practice use. Handwritten scores and low-quality scans may produce degraded output; this is acceptable but SHOULD be documented.

This 300+ DPI floor is a hard requirement for `engine="audiveris"` specifically — it explicitly
rejects sheets whose staff-line spacing implies lower resolution rather than degrading gracefully
(surfaces as `PROCESSING_FAILED`, not a garbled result). `engine="oemer"` (default) is DPI-insensitive
in practice: it normalizes every input to a fixed internal pixel budget before recognition, so
source resolution below 300 DPI doesn't measurably change its output (confirmed empirically —
see docs/HANDOVER.md).

### NFR-2 — Offline operation

All processing MUST run locally. No network requests to external APIs or cloud services are permitted during recognition.

### NFR-3 — Model bootstrapping

On first run, the server MAY download model checkpoints (~100 MB for oemer; ~80 MB for Audiveris,
only on first use of `engine="audiveris"`). Subsequent runs MUST use the cached models/binaries.
Download MUST be automatic and require no manual intervention beyond internet access.

### NFR-4 — Output correctness

The returned MusicXML MAY not pass strict schema validation, but MUST be functionally correct and parseable by music21, MuseScore, and Finale.

### NFR-5 — Determinism tolerance

oemer output may vary slightly between runs on the same image. Callers MUST NOT assert byte-identical output across runs.

### NFR-6 — Transport

The server MUST communicate via MCP stdio transport. It MUST NOT require any network port or GUI.

---

## Interface Requirements

### IR-1 — MCP protocol

The server MUST implement the Model Context Protocol using `mcp.server.stdio.stdio_server()`. Tools MUST be registered with correct input schemas.

### IR-2 — Tool: `recognize_sheet`

```
Input:
  image   string  required  file path or base64-encoded image data
  format  string  (optional) "path" or "base64" hint; auto-detected if omitted
  engine  string  (optional) "oemer" (default) or "audiveris" — see FR-6

Output:
  musicxml     string  MusicXML document
  metadata     object
    source              string   original image path
    staves_detected     integer
    measures            integer
    processing_time_ms  integer
    engine              string   "oemer" | "audiveris"
```

### IR-3 — Tool: `recognize_sheet_to_file`

```
Input:
  input_path   string  required  path to input PNG/JPEG
  output_path  string  optional  path to write MusicXML (auto-generated if omitted)
  engine       string  optional  "oemer" (default) or "audiveris" — see FR-6

Output:
  output_path  string  path of written file
  metadata     object  same structure as recognize_sheet
```

### IR-4 — Tool: `recognize_sheets`

```
Input:
  image_paths  list[string]  required  ordered list of image paths
  engine       string        optional  "oemer" (default) or "audiveris" — see FR-6

Output:
  musicxml     string  merged MusicXML document
  page_count   integer
  metadata     object
```

### IR-5 — Tool: `list_capabilities`

```
Output:
  server          string
  version         string
  input_formats   list[string]   ["png", "jpeg"]
  output_formats  list[string]   ["musicxml"]
  tools           list[string]
  backend         string         "oemer" (primary/default engine)
  backend_version string
  engines         object         per-engine availability, keyed "oemer" | "audiveris":
                                    status  string  "ok" | "not_installed"
                                    note    string  human-readable description
```

(Corrected 2026-08-16: this previously documented `engine`/`engine_version` fields that never
matched the actual implementation, which has always used `backend`/`backend_version` — unrelated
drift found while adding the `engines` field for FR-6.)

### IR-6 — Error response format

All error responses MUST follow this structure:

```json
{"error": "<human-readable message>", "error_code": "<CODE>"}
```

| Code | Condition |
|------|-----------|
| `FILE_NOT_FOUND` | Input file does not exist |
| `UNSUPPORTED_FORMAT` | File extension is not PNG/JPEG |
| `FILE_TOO_LARGE` | Image exceeds the maximum allowed size |
| `INVALID_INPUT` | Image cannot be decoded or opened |
| `INVALID_PARAMETER` | A tool argument is malformed (e.g. `images` is not a list) |
| `PROCESSING_FAILED` | OMR engine error |

---

## Constraints

- Language: Python 3.11+
- Package manager: uv
- OMR engines: oemer (default, in-process) and Audiveris (opt-in via `engine="audiveris"`,
  implemented 2026-08-16 — see FR-6). oemer flattens multi-staff scores into one part; Audiveris
  correctly separates them but requires 300+ DPI input and runs as a subprocess.
- Audiveris is invoked via subprocess (a self-contained JVM bundle, downloaded lazily on first
  use — see docs/HANDOVER.md); oemer remains in-process. Not a blanket "no subprocess" rule.
- No shared state between tool calls; each call is independent

---

## Testing Requirements

### TR-1 — Unit tests

Unit tests MUST cover:

- Input validation (invalid path, bad format, bad base64, missing required fields)
- Error response format and error codes
- `list_capabilities` response schema
- MusicXML string return path vs file write path

Unit tests MUST mock the oemer engine and MUST NOT perform real OMR.

### TR-2 — Integration tests

Integration tests MUST:

- Be marked `@pytest.mark.integration`
- Be skipped by default (`pytest tests/ -v` skips them)
- Run a real oemer recognition on at least one fixture PNG from `test_samples/pdmx_satb_samples/png/`
- Assert that the returned MusicXML contains `<score-partwise>`
- Assert that music21 can parse the returned MusicXML without error

Integration tests MAY be slow (up to 10 minutes per page on CPU). This is acceptable.

### TR-3 — Test fixtures

Test fixtures MUST be committed to the repository. The primary fixture source is `test_samples/pdmx_satb_samples/` (SATB a cappella scores from the PDMX dataset).
