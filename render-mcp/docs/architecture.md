# render-mcp — Technical Architecture

## Overview

render-mcp is a stateless MCP server that renders MusicXML scores to PDF or PNG/SVG images. It uses Verovio for music engraving (MusicXML → SVG) and a cairosvg + pypdf pipeline for PDF and PNG output. All rendering runs in-process; no external tools are required.

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
│  list_tools()   → 5 tool definitions                      │
│  call_tool()    → load_score(), then dispatches to engine │
└──────────┬────────────────────────────────────────────────┘
           │
┌──────────▼──────────────┐  ┌──────────────────────────────┐
│       engine.py         │  │          utils.py            │
│                         │  │                              │
│  detect_backend()       │  │  validate_musicxml()         │
│  render_to_pdf()        │  │  validate_dpi()              │
│  render_to_image()      │  │  validate_page()             │
│  _render_pdf_verovio()  │  │  validate_image_format()     │
│  _render_image_verovio()│  │  generate_pdf_path()         │
│  _render_pdf_musescore()│  │  generate_image_path()       │
│  _render_image_musescore│  └──────────────────────────────┘
│  _get_pdf_page_count()  │
│  _get_image_dimensions()│
└──────────┬──────────────┘
           │
    ┌──────┴────────────────────────────────────┐
    │                                           │
┌───▼──────────┐  ┌────────────┐  ┌────────────▼──┐
│   verovio    │  │  cairosvg  │  │    pypdf      │
│              │  │            │  │               │
│  toolkit()   │  │  svg2pdf() │  │  PdfReader()  │
│  loadData()  │  │  svg2png() │  │  PdfWriter()  │
│  renderToSVG │  │  (scale=)  │  │  merge pages  │
└──────────────┘  └─────┬──────┘  └───────────────┘
                        │
               ┌────────▼────────┐
               │  libcairo.so.2  │
               │ (system library)│
               └─────────────────┘
```

---

## Module Responsibilities

### `server.py`

MCP protocol layer. Contains no rendering logic.

- Registers five tools: `render_to_pdf`, `render_to_image`, `list_capabilities`, `health_check`
  and the shared `describe_score` (`sheet_music_mcp_core.references.DESCRIBE_SCORE_TOOL`)
- Gets the score with `references.load_score(arguments, ctx)`: inline `musicxml` as is, or
  `musicxml_path` confined to the read roots and read (`.mxl` too). The handlers are wired with
  `make_handlers(..., pass_context=True)` so `load_score` can ask the client for its roots.
  Everything after that is unchanged, so a path call and an inline call give the same result
- Validates all parameters (via `utils.py`) before calling the engine
- Converts engine results and exceptions to `TextContent` JSON (always `content[0]`)
- On success appends result blocks for the written file via `sheet_music_mcp_core.content`
  (`_file_blocks`): a PNG of at most 1 MB as an inline `image` block (`png_block`), then a
  `resource_link` with a `file://` URI and MIME type (`file_link`). SVG and PDF get only the link.
- Entry point via `mcp.server.stdio.stdio_server()`

### `engine.py`

All rendering logic. No MCP imports.

| Function | Description |
|----------|-------------|
| `detect_backend()` | Return `"musescore"` if MuseScore CLI is in PATH, else `"verovio"` |
| `musescore_available()` | True if MuseScore CLI found |
| `verovio_available()` | True if verovio importable |
| `render_to_pdf(musicxml, output_path)` | Dispatch to MuseScore or Verovio PDF pipeline |
| `render_to_image(musicxml, page, fmt, dpi, output_path)` | Dispatch to MuseScore or Verovio image pipeline |
| `_render_pdf_verovio(musicxml, output_path)` | Verovio → SVG per page → cairosvg PDF → pypdf merge |
| `_render_image_verovio(musicxml, page, fmt, dpi, output_path)` | Verovio → SVG → PNG or SVG file |
| `_render_pdf_musescore(musicxml, output_path)` | MuseScore CLI subprocess → PDF |
| `_render_image_musescore(musicxml, page, fmt, dpi, output_path)` | MuseScore CLI subprocess → PNG |
| `_get_pdf_page_count(pdf_path)` | Count pages via pypdf.PdfReader |
| `_get_image_dimensions(image_path)` | Get width/height via PIL Image.size |

Backend is detected once at module import time; it cannot change while the server is running.

### `utils.py`

Input validation and path helpers.

| Function | Description |
|----------|-------------|
| `validate_musicxml(xml)` | Check non-empty; check for `<score-partwise>` or `<score-timewise>` root |
| `validate_dpi(dpi)` | Check 72 ≤ dpi ≤ 600 |
| `validate_page(page)` | Check page ≥ 1 (upper bound validated against actual page count in engine) |
| `validate_image_format(fmt)` | Check fmt ∈ `{"png", "svg"}` |
| `generate_pdf_path()` | Auto-generate timestamped path in `/tmp/render-mcp/` |
| `generate_image_path(fmt)` | Auto-generate timestamped path with correct extension |
| `confine_output_path(path, suffixes)` | Re-export of `sheet_music_mcp_core.paths.confine_output_path` (raises `PathPolicyError`, a `ValueError`) |

---

## Data Flow

### PDF rendering (Verovio path)

```
call_tool("render_to_pdf", {musicxml | musicxml_path, output_path})
  │
  ├─ references: load_score (inline text, or the confined file)
  ├─ utils: validate_musicxml, generate_pdf_path
  │
  └─ engine: _render_pdf_verovio(musicxml, output_path)
        │
        ├─ tk = verovio.toolkit()
        ├─ tk.loadData(musicxml)
        ├─ page_count = tk.getPageCount()
        ├─ page_pdfs = []
        │
        ├─ for page in 1..page_count:
        │     svg_str = tk.renderToSVG(page)        ← Verovio: MusicXML → SVG
        │     pdf_bytes = cairosvg.svg2pdf(          ← cairosvg: SVG → single-page PDF
        │         bytestring=svg_str.encode(),
        │         scale=1.0                          ← no DPI scaling for PDF
        │     )
        │     page_pdfs.append(pdf_bytes)
        │
        ├─ writer = pypdf.PdfWriter()
        ├─ for pdf_bytes in page_pdfs:
        │     reader = pypdf.PdfReader(BytesIO(pdf_bytes))
        │     writer.add_page(reader.pages[0])
        │
        ├─ writer.write(output_path)
        └─ return (output_path, page_count)
```

### Image rendering (Verovio path)

```
call_tool("render_to_image", {musicxml, page=2, format="png", dpi=150})
  │
  ├─ utils: validate_musicxml, validate_dpi, validate_page, validate_image_format
  │
  └─ engine: _render_image_verovio(musicxml, page=2, fmt="png", dpi=150, output_path)
        │
        ├─ tk = verovio.toolkit()
        ├─ tk.loadData(musicxml)
        ├─ total_pages = tk.getPageCount()
        ├─ check page ≤ total_pages (error if out of range)
        │
        ├─ svg_str = tk.renderToSVG(2)
        │
        ├─ if fmt == "png":
        │     scale = dpi / 96.0              ← DPI scaling (96 px/in = CSS reference)
        │     png_bytes = cairosvg.svg2png(
        │         bytestring=svg_str.encode(),
        │         scale=scale                 ← scale parameter, not dpi parameter
        │     )
        │     write png_bytes to output_path
        │     width, height = PIL.Image.open(output_path).size
        │
        └─ return {image_path, format, width_px, height_px, page, total_pages, backend}
```

---

## DPI Scaling

Verovio SVGs have fixed pixel dimensions (e.g. 1800×2546 px) regardless of DPI. cairosvg honours the SVG's intrinsic dimensions unless told to scale.

The correct way to control output resolution is via the `scale` parameter, not `dpi`:

```
scale = dpi / 96.0
```

96 px/in is the CSS reference resolution. At 150 DPI:
- scale = 150 / 96.0 = 1.5625
- Output image is 1.5625× the SVG's intrinsic pixel size

Using `dpi=` in cairosvg does **not** correctly apply to SVGs with fixed pixel dimensions.

---

## PDF Pipeline Detail

For multi-page scores, one SVG is rendered per page, converted to a single-page PDF, and then all pages are merged:

```
MusicXML
  → verovio.toolkit.renderToSVG(1) → SVG page 1
  → verovio.toolkit.renderToSVG(2) → SVG page 2
  ...
  → cairosvg.svg2pdf(page_1_svg) → PDF bytes (1 page)
  → cairosvg.svg2pdf(page_2_svg) → PDF bytes (1 page)
  ...
  → pypdf.PdfWriter
       .add_page(page_1)
       .add_page(page_2)
       ...
  → writer.write(output.pdf)
```

For a single-page score, pypdf merge is still performed (a single-page PdfWriter.write is a valid PDF).

---

## Backend Detection

At module import time, `detect_backend()` is called once:

```python
def _find_musescore_cmd():
    for name in ["mscore4", "musescore4", "musescore"]:
        if shutil.which(name):
            return name
    return None

def detect_backend():
    if _find_musescore_cmd():
        return "musescore"
    if _check_verovio():
        return "verovio"
    return None
```

On the current development machine, MuseScore CLI is not installed. Verovio is the active backend.

---

## MuseScore CLI Path (available when installed)

If MuseScore is detected, rendering is delegated to it via subprocess:

```python
# PDF
subprocess.run([mscore_cmd, "-o", output_path, tmp_input_mxl])

# PNG at specified DPI
subprocess.run([mscore_cmd, "-o", tmp_out_base, tmp_input_mxl, "-r", str(dpi)])
```

MuseScore names output files as `render.png` (single page) or `render-N.png` for page N. The engine finds the correct file by pattern-matching.

---

## Error Handling

```json
{"error": "<message>", "error_code": "<CODE>"}
```

| Scenario | Code |
|----------|------|
| MusicXML parse failure | `INVALID_INPUT` |
| Page number out of range | `INVALID_PARAMETER` |
| Unsupported image format | `INVALID_PARAMETER` |
| DPI out of range | `INVALID_PARAMETER` |
| Both or neither of `musicxml` / `musicxml_path` | `INVALID_PARAMETER` |
| `musicxml_path` outside the read roots, or wrong suffix | `INVALID_PARAMETER` (never echoes file content) |
| `musicxml_path` missing / too large / not MusicXML | `FILE_NOT_FOUND` / `FILE_TOO_LARGE` / `INVALID_INPUT` |
| No backend available | `PROCESSING_FAILED` |
| Verovio rendering error | `PROCESSING_FAILED` |
| MuseScore subprocess failure | `PROCESSING_FAILED` |

---

## Key Dependencies

| Package | Role |
|---------|------|
| `verovio` ≥3.0 | MusicXML engraving → SVG (pure Python C++ binding, in-process) |
| `cairosvg` ≥2.7 | SVG → PNG / SVG → PDF conversion |
| `pypdf` ≥4.0 | PDF page count reading, multi-page PDF assembly |
| `Pillow` | PNG dimension reading |
| `mcp` | MCP protocol SDK |
| `sheet-music-mcp-core` ≥0.2 | Shared error envelope, `ProcessingError`, handler wiring (input validation, error results), score references (`load_score`, `describe_score`) and output path confinement; see [docs/conventions.md](../../docs/conventions.md#shared-core-library) |

**System library:** `libcairo2` must be installed. Standard on Ubuntu desktop; no sudo required.

---

## Output Files

Auto-generated paths use timestamps:

```
/tmp/render-mcp/score_YYYYMMDD_HHMMSS_ffffff.pdf
/tmp/render-mcp/score_YYYYMMDD_HHMMSS_ffffff.png
```

---

## File Layout

```
render-mcp/
├── pyproject.toml
├── src/
│   └── render_mcp/
│       ├── __init__.py
│       ├── server.py     ← MCP layer (tool registration, dispatch)
│       ├── engine.py     ← Rendering logic (Verovio, cairosvg, pypdf, MuseScore)
│       └── utils.py      ← Validation, path generation
└── tests/
    ├── test_server.py
    ├── test_engine.py
    ├── test_utils.py
    ├── test_score_references.py   ← musicxml_path, describe_score
    └── fixtures/
```
