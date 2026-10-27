# render-mcp Requirements

## Purpose

Render a MusicXML score to a printable PDF or a screen-ready PNG/SVG image. Produces output for printing (Goal 2) and for displaying score pages in the web and Android apps.

Covers **Goal 2**: Export sheet music as a PDF file.

---

## Functional Requirements

### FR-1 — Full-score PDF rendering

The server MUST render a complete MusicXML score to a multi-page PDF file.

- Every measure in the score MUST appear in the PDF
- Page layout (staff spacing, margins) MUST be consistent across pages
- The output MUST be a valid PDF that can be opened and printed by standard PDF viewers

### FR-2 — Single-page image rendering

The server MUST render a single page of a score to a PNG or SVG file.

- The caller specifies a 1-indexed page number
- Page numbers outside the valid range MUST be rejected with a clear error stating the valid range
- PNG output MUST respect the requested DPI (range 72–600; default 150)
- SVG output is resolution-independent

### FR-3 — Output path

The server MUST write the output file to the specified path. If no path is provided, the server MUST auto-generate a path in the system temporary directory.

The response MUST include the final output path.

### FR-4 — Capability reporting

The server MUST expose a tool that returns:

- Server name and version
- Supported input and output formats
- Active rendering backend name and version
- List of available tools

---

## Non-Functional Requirements

### NFR-1 — Rendering quality

Output MUST be of sufficient quality for choir use:

- Standard Western notation symbols MUST be correctly positioned and proportioned
- Time signatures, key signatures, clef symbols, noteheads, stems, beams, and bar lines MUST be legible
- PNG output at 150 DPI MUST be suitable for on-screen display; at 300 DPI MUST be suitable for printing

### NFR-2 — Performance

Rendering a typical 4-page SATB score to PDF MUST complete within 15 seconds.

### NFR-3 — Offline operation

All rendering MUST run locally using in-process libraries. No network access or external processes are permitted.

### NFR-4 — No GUI dependency

The server MUST run in headless environments. No display server (X11, Wayland, Quartz) is required.

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

### IR-2 — Tool: `render_to_pdf`

```
Input:
  musicxml     string  required  MusicXML document as a string
  output_path  string  optional  path to write PDF; auto-generated if omitted

Output:
  pdf_path    string   path of written PDF file
  page_count  integer
  backend     string   e.g. "verovio"
```

### IR-3 — Tool: `render_to_image`

```
Input:
  musicxml     string   required  MusicXML document as a string
  page         integer  optional  1-indexed page number; default: 1
  format       string   optional  "png" or "svg"; default: "png"
  dpi          integer  optional  72–600; default: 150; only applies to PNG
  output_path  string   optional  path to write image; auto-generated if omitted

Output:
  image_path   string   path of written file
  format       string
  width_px     integer  (PNG only)
  height_px    integer  (PNG only)
  page         integer
  total_pages  integer
  backend      string
```

### IR-4 — Tool: `list_capabilities`

```
Output:
  server            string
  version           string
  input_formats     list[string]   ["musicxml"]
  output_formats    list[string]   ["pdf", "png", "svg"]
  tools             list[string]
  backend           string         active backend, e.g. "verovio"
  backend_version   string
  verovio_available boolean
```

### IR-5 — Error response format

```json
{"error": "<human-readable message>", "error_code": "<CODE>"}
```

| Code | Condition |
|------|-----------|
| `INVALID_INPUT` | MusicXML cannot be parsed |
| `INVALID_PARAMETER` | Page out of range; unsupported format; DPI out of range |
| `PROCESSING_FAILED` | No backend available; rendering error |

---

## Rendering Pipeline

### Primary backend: Verovio + cairosvg + pypdf

1. Verovio renders each page to SVG in-process
2. cairosvg converts each SVG to PNG (for image output) or to a single-page PDF
3. pypdf merges single-page PDFs into a multi-page document

DPI mapping: Verovio SVGs have fixed pixel dimensions. Use `scale = dpi / 96.0` in cairosvg (not `dpi=`), as 96 px/in is the CSS reference resolution.

For single-page scores, the pypdf merge step is skipped.

---

## Constraints

- Language: Python 3.11+
- Package manager: uv
- Primary backend: Verovio (in-process Python bindings)
- PDF pipeline: cairosvg per page → pypdf merge
- No MuseScore CLI dependency in Phase 1
- System library: `libcairo2` must be installed (standard on Ubuntu desktop; available without sudo)

---

## Testing Requirements

### TR-1 — Unit tests

Unit tests MUST cover:

- DPI validation (boundary values: 71, 72, 600, 601)
- Page validation (out-of-range page numbers)
- Format validation (unsupported format string)
- MusicXML parse error path
- `list_capabilities` response schema
- Output path auto-generation

Unit tests MUST mock Verovio and cairosvg. They MUST NOT produce real output files.

### TR-2 — Integration tests

Integration tests MUST:

- Run real Verovio rendering on an MXL fixture (Verovio runs in-process; no marks or skips needed)
- Produce a non-empty PDF file and verify it is readable by pypdf
- Produce a non-empty PNG file and verify its dimensions are plausible (width > 100, height > 100)
- Test multi-page output (score with 2+ pages)

### TR-3 — Test fixtures

MXL fixtures SHOULD be shared from `../omr-mcp/test_samples/pdmx_satb_samples/mxl/`.
