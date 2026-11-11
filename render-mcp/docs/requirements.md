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

### FR-3a — Score references

The render tools MUST accept the score either inline (`musicxml`) or as a file path
(`musicxml_path`, `.musicxml`, `.xml` or `.mxl`), exactly one of them
([conventions: Score References](../../docs/conventions.md#score-references)).

- Paths are read through `sheet_music_mcp_core.references.load_score()`, confined to the read
  roots: the output root (`SHEET_MUSIC_OUTPUT_ROOT`), the client's MCP roots and
  `SHEET_MUSIC_INPUT_ROOTS`. Relative paths resolve against the output root.
- A path call MUST give the same result as the inline call with the same score.
- Errors MUST NOT echo the content of the file read.

### FR-3b — Score description

The server MUST expose the shared `describe_score` tool, which returns title, composer, key,
time, tempo, parts (ID, name, abbreviation, clef, range), measures, lyrics presence and duration
without rendering.

### FR-4 — Capability reporting

The server MUST expose a tool that returns:

- Server name and version
- Supported input and output formats
- Active rendering backend name and version
- List of available tools

### FR-5 — Score Viewer UI resource (MCP Apps)

The server MUST serve the Score Viewer as the `ui://` resource `ui://render/score-viewer`
(MIME type `text/html;profile=mcp-app`) when its HTML is packaged
(`render_mcp/ui/assets/score-viewer.html`, built in `ui/`, decision D1):

- `resources/list` lists it, and `resources/read` returns one text item with the HTML.
- `render_to_pdf` and `render_to_image` carry `_meta.ui.resourceUri = "ui://render/score-viewer"`.
- Without the HTML (a source checkout without a UI build) the resource is not listed, the tools
  carry no `_meta.ui`, and `resources/read` fails with `UI_ASSET_MISSING` naming
  `npm run build` in `ui/`.
- The page is self-contained: no `<script src>` or `<link href>` off-origin (AC-R1).
- What a text-only client sees MUST NOT change: the tools' `content` stays byte-identical.

### FR-6 — Server-side page rendering for the viewer

The viewer renders with Verovio WebAssembly in the page. The MCP Apps default CSP has no
`'wasm-unsafe-eval'` and a server cannot request it, so the server MUST also offer the app-only
tool `render_page_svg` (IR-7), which renders one page as SVG with the same layout as the viewer.
It MUST be hidden from `tools/list` for clients that do not advertise MCP Apps, and MUST NOT
accept a file path.

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

### FR-3b — Measure ranges

`render_to_pdf` and `render_to_image` MUST accept an optional `measures: [start, end]`
(inclusive printed measure numbers, pickup bar 0; UX Wave 3, B2,
[conventions: Measure Ranges](../../docs/conventions.md#measure-ranges)).

- The engine cuts the score once with `sheet_music_mcp_core.measures.select_measures()` before
  backend dispatch, so MuseScore and Verovio receive the same cut score (key, time, clef,
  divisions and tempo in force at `start` are carried into the first kept bar). The backends
  know nothing of ranges.
- `page` counts pages of the cut score.
- A reversed range, a range outside the score or a range holding no bar is `INVALID_PARAMETER`
  with `hint` naming the score's first and last bar numbers ("This score has measures 1–6.").
- Without `measures` the call is unchanged.

Every tool sets a human-readable `title` and an annotation preset from `sheet-music-mcp-core`
(see [conventions: Tool Annotations and Titles](../../docs/conventions.md#tool-annotations-and-titles)).
The per-tool table of titles and presets is `tests/test_tool_metadata.py`. The server sends
`instructions` at initialize ([conventions: Server Instructions](../../docs/conventions.md#server-instructions)).

### IR-2 — Tool: `render_to_pdf`

```
Input (exactly one of musicxml / musicxml_path, schema `oneOf`):
  musicxml       string  MusicXML document as a string
  musicxml_path  string  path to a .musicxml, .xml or .mxl file inside the read roots (preferred)
  measures       [int, int]  optional  inclusive printed bar range, e.g. [17, 24]; whole score if omitted
  output_path    string  optional  path to write PDF; auto-generated if omitted

Output:
  pdf_path    string   path of written PDF file
  page_count  integer
  backend     string   e.g. "verovio"
```

Content blocks: `content[0]` is the JSON text above. On success it is followed by a
`resource_link` to the PDF (`file://` URI of the resolved path, MIME type `application/pdf`).
Errors return only the error JSON, as an `isError` result.

`structuredContent` (IR-6): the output above. `_meta.ui.resourceUri`: `ui://render/score-viewer`
when the viewer is packaged (FR-5).

### IR-3 — Tool: `render_to_image`

```
Input (exactly one of musicxml / musicxml_path, schema `oneOf`):
  musicxml       string   MusicXML document as a string
  musicxml_path  string   path to a .musicxml, .xml or .mxl file inside the read roots (preferred)
  measures     [int, int]  optional  inclusive printed bar range; whole score if omitted
  page         integer  optional  1-indexed page number (of the cut score); default: 1
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

Content blocks: `content[0]` is the JSON text above. On success, extra blocks follow
([conventions](../../docs/conventions.md#result-content)):

| `format` | `content[1]` | `content[2]` |
|----------|--------------|--------------|
| `png`, file ≤ 1 MB | `image` (base64 PNG, `image/png`) | `resource_link` (`file://`, `image/png`) |
| `png`, file > 1 MB | `resource_link` (`file://`, `image/png`) | — |
| `svg` | `resource_link` (`file://`, `image/svg+xml`) | — |

SVG gets no image block because many hosts cannot display SVG. Errors return only the error JSON,
as an `isError` result.

`structuredContent` (IR-6): the output above (`width_px` / `height_px` only for PNG).
`_meta.ui.resourceUri`: `ui://render/score-viewer` when the viewer is packaged (FR-5).

### IR-3a — Tool: `describe_score`

The shared tool from `sheet_music_mcp_core.references` (`DESCRIBE_SCORE_TOOL`, title "Describe
score", `READ_ONLY`). Takes exactly one of `musicxml` / `musicxml_path`.

```
Output:
  title, composer, key, time, tempo_bpm
  parts              list[{id, name, abbreviation, clef, range: {low, high}}]   ids P1 …
  measures           integer
  has_lyrics         boolean
  duration_quarters  number
  duration_seconds   number | null
```

### IR-4 — Tool: `list_capabilities`

```
Output:
  server            string
  version           string
  input_formats     list[string]   ["musicxml", "mxl"]
  input_parameters  list[string]   ["musicxml", "musicxml_path", "measures"]
  output_formats    list[string]   ["pdf", "png", "svg"]
  tools             list[string]
  backend           string         active backend, e.g. "verovio"
  backend_version   string
  verovio_available boolean
```

### IR-5 — Error response format

```json
{"error": "<human-readable message>", "error_code": "<CODE>", "hint": "<optional>"}
```

| Code | Condition |
|------|-----------|
| `INVALID_INPUT` | MusicXML cannot be parsed (inline or read from `musicxml_path`) |
| `INVALID_PARAMETER` | Page out of range; unsupported format; DPI out of range; `measures` reversed, outside the score or holding no bar (with `hint`); both or neither of `musicxml` / `musicxml_path`; `musicxml_path` outside the read roots or with another suffix; `output_path` outside the output root |
| `FILE_NOT_FOUND` | `musicxml_path` inside the roots does not exist |
| `FILE_TOO_LARGE` | `musicxml_path` larger than `SHEET_MUSIC_MAX_SCORE_BYTES` (default 16 MiB) |
| `PROCESSING_FAILED` | No backend available; rendering error |
| `UI_ASSET_MISSING` | `resources/read` of the Score Viewer without a UI build (JSON-RPC `-32603`, envelope in `data`) |
| `RESOURCE_NOT_FOUND` | `resources/read` of an unknown URI (JSON-RPC `-32602`, envelope in `data`) |

### IR-6 — Structured content

`render_to_pdf`, `render_to_image` and `render_page_svg` declare an `output_schema`
(`presenter.py`) and return `structuredContent` that validates against it. For the two render
tools it holds the same data as the JSON text in `content[0]`. Error results are `isError`, keep
the `{error, error_code}` content and carry no `structuredContent`, so clients do not validate
them against the schema.

### IR-7 — Tool: `render_page_svg` (app-only)

Title "Render score page as SVG", annotation preset `READ_ONLY`.
`_meta.ui = {resourceUri: "ui://render/score-viewer", visibility: ["app"]}`; without a UI build
only `{visibility: ["app"]}`. Listed only for clients whose `initialize` capabilities advertise
the `io.modelcontextprotocol/ui` extension with the `text/html;profile=mcp-app` MIME type;
`tools/call` works for any client.

```
Input (all required; no other properties, so never a path):
  musicxml  string   MusicXML document as a string
  page      integer  ≥ 1; page of the layout below
  width_px  integer  1–10000; viewer width in CSS pixels
  zoom      number   0.1–10; 1 = 100 %

structuredContent:
  svg         string   the page as an SVG document
  page        integer
  page_count  integer  pages at this width and zoom

content: one text block, e.g. "Page 2 of 5 rendered as SVG (84 kB) for the Score Viewer."
```

Layout: Verovio `scale`, `pageWidth`, `pageHeight` from `engine.page_layout(width_px, zoom)`,
which mirrors the UI's `paging.ts` `layoutFor()`, plus `adjustPageHeight`, `breaks: "auto"` and
`footer: "none"`. The last score is kept parsed (by SHA-256), so paging re-renders without
re-parsing and a new width or zoom only re-flows.

Errors: not MusicXML → `INVALID_INPUT`; a page past the end → `INVALID_PARAMETER`, message
"Page N is out of range.", hint "This score has pages 1–M at this width and zoom."; schema
failures → `INVALID_PARAMETER`.

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
- Score references (`tests/test_score_references.py`): path call equals inline call (all
  content blocks), `.mxl` paths, both/neither through the protocol, paths outside the roots
  (absolute, `../`, symlink) with no file content in the error, `describe_score`

- MCP Apps: `_meta.ui` with and without a UI build, `resources/list` and `resources/read`,
  `structuredContent` against the output schemas, `content` unchanged (golden file),
  `render_page_svg` visibility for UI and non-UI clients, its contract and errors

Unit tests MUST mock Verovio and cairosvg for the file-writing tools. They MUST NOT produce real
output files. The `render_page_svg` engine tests (`tests/test_page_svg.py`) run real Verovio in
process, since the contract is Verovio's page count and re-flow; they write no files and take
well under a second.

### TR-2 — Integration tests

Integration tests MUST:

- Run real Verovio rendering on an MXL fixture (Verovio runs in-process; no marks or skips needed)
- Produce a non-empty PDF file and verify it is readable by pypdf
- Produce a non-empty PNG file and verify its dimensions are plausible (width > 100, height > 100)
- Test multi-page output (score with 2+ pages)
- Check the built wheel ships `render_mcp/ui/assets/score-viewer.html` with no off-origin
  references (`tests/test_packaging.py`; skipped with the build command when the UI is not built)

### TR-3 — Test fixtures

MXL fixtures SHOULD be shared from `../omr-mcp/test_samples/pdmx_satb_samples/mxl/`.
