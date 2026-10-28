# render-mcp — Technical Architecture

## Overview

render-mcp is a stateless MCP server that renders MusicXML scores to PDF or PNG/SVG images. It uses Verovio for music engraving (MusicXML → SVG) and a cairosvg + pypdf pipeline for PDF and PNG output. All rendering runs in-process; no external tools are required.

Hosts that support MCP Apps also get the **Score Viewer** (`ui://render/score-viewer`), an HTML
page built in `ui/` and packaged with the server. It pages and zooms the score inline. It renders
with Verovio WebAssembly in the page where the host allows it, and otherwise asks the app-only
`render_page_svg` tool for each page ([Score Viewer](#score-viewer-mcp-apps)). The only server
state is that tool's cache of the last score it parsed.

---

## Component Diagram

```
┌───────────────────────────────────────────────────────────┐
│                      MCP Client                           │
└──────────────────────────┬────────────────────────────────┘
                           │  stdio (JSON-RPC)
┌──────────────────────────▼────────────────────────────────┐   ┌──────────────────────────┐
│                       server.py                           │   │ sheet_music_mcp_core     │
│                                                           │   │                          │
│  list_tools()        → 6 tools (render_page_svg app-only) │──►│ wiring.make_handlers()   │
│  call_tool_result()  → load_score(), engine, presenter    │   │  hides app-only tools    │
│  call_tool()         → the same result's content only     │   │  from non-UI clients     │
│  ui_registry         → ui://render/score-viewer           │──►│ wiring.make_resource_    │
│  resources/list, resources/read                           │   │  handlers()              │
└──────┬─────────────────────────┬──────────────────────────┘   │ ui.UiRegistry,           │
       │                         │                              │  PackageAssetSource      │
       │                 ┌───────▼─────────┐                    └────────────┬─────────────┘
       │                 │  presenter.py   │                                 │ reads
       │                 │                 │                    ┌────────────▼─────────────┐
       │                 │ present_pdf()   │                    │ render_mcp/ui/assets/    │
       │                 │ present_image() │                    │   score-viewer.html      │
       │                 │ present_page_   │                    │ built in ui/, gitignored,│
       │                 │   svg()         │                    │ packaged by hatch        │
       │                 │ *_OUTPUT_SCHEMA │                    │ artifacts                │
       │                 └─────────────────┘                    └──────────────────────────┘
┌──────▼──────────────────┐  ┌──────────────────────────────┐
│       engine.py         │  │          utils.py            │
│                         │  │                              │
│  detect_backend()       │  │  validate_musicxml()         │
│  render_to_pdf()        │  │  validate_dpi()              │
│  render_to_image()      │  │  validate_page()             │
│  page_layout()          │  │  validate_image_format()     │
│  SvgPageRenderer        │  │  generate_pdf_path()         │
│  _render_pdf_verovio()  │  │  generate_image_path()       │
│  _render_image_verovio()│  └──────────────────────────────┘
│  _render_pdf_musescore()│
│  _render_image_musescore│
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

- Registers six tools: `render_to_pdf`, `render_to_image`, `list_capabilities`, `health_check`,
  the shared `describe_score` (`sheet_music_mcp_core.references.DESCRIBE_SCORE_TOOL`) and the
  app-only `render_page_svg`
- Registers the Score Viewer (`SCORE_VIEWER`) in `ui_registry`, a `UiRegistry` over
  `PackageAssetSource("render_mcp")` (tests swap in `InMemoryAssetSource`). `render_to_pdf` and
  `render_to_image` carry `meta=ui_registry.meta_for(SCORE_VIEWER)`, so `_meta.ui.resourceUri`
  appears only when the HTML is packaged. `resources/list` and `resources/read` come from the
  core `make_resource_handlers`, through a small delegate that reads `ui_registry` per request
- Gets the score with `references.load_score(arguments, ctx)`: inline `musicxml` as is, or
  `musicxml_path` confined to the read roots and read (`.mxl` too). The handlers are wired with
  `make_handlers(..., pass_context=True)` so `load_score` can ask the client for its roots.
  Everything after that is unchanged, so a path call and an inline call give the same result
- Validates all parameters (via `utils.py`) before calling the engine; passes `measures` on
  only when the caller gave it (`_measures_argument`), so default calls are unchanged
- Returns a raised `ProcessingError` with `processing_error_content`, keeping its `hint`
- `call_tool_result()` is what the server wires: the render tools return a `CallToolResult`
  whose `content` and `structuredContent` come from `presenter.py`; render errors are `isError`
  results with only the error JSON (clients skip output-schema checks for them). `call_tool()`
  returns the same result's `content`, which is byte-identical to before MCP Apps
  (`tests/test_content_golden.py`)
- Entry point via `mcp.server.stdio.stdio_server()`

### `presenter.py`

Engine result → `(content, structured_content)`. `content[0]` is the JSON text, followed on
success by the file blocks from `sheet_music_mcp_core.content`: a PNG of at most 1 MB as an inline
`image` block (`png_block`), then a `resource_link` with a `file://` URI and MIME type
(`file_link`); SVG and PDF get only the link. `structuredContent` is the same data as the JSON
text. `present_page_svg` returns a one-line text (no SVG, so the markup never reaches a model)
and `{svg, page, page_count}`. The module also holds the three tools' `output_schema`s.

### `engine.py`

All rendering logic. No MCP imports.

| Function | Description |
|----------|-------------|
| `detect_backend()` | Return `"musescore"` if MuseScore CLI is in PATH, else `"verovio"` |
| `musescore_available()` | True if MuseScore CLI found |
| `verovio_available()` | True if verovio importable |
| `render_to_pdf(musicxml, output_path, measures=None)` | Cut to `measures` (`select_measures`), then dispatch to MuseScore or Verovio PDF pipeline |
| `render_to_image(musicxml, page, fmt, dpi, output_path, measures=None)` | Cut to `measures`, then dispatch to MuseScore or Verovio image pipeline |
| `page_layout(container_width, zoom)` | Verovio `scale`, `pageWidth`, `pageHeight` for a viewer width and zoom; mirrors `ui/packages/kit/src/score/paging.ts` `layoutFor()` (JavaScript rounding) |
| `SvgPageRenderer.render(musicxml, page, width_px, zoom)` | One page as SVG for the Score Viewer; keeps the last score parsed (see below) |
| `_render_pdf_verovio(musicxml, output_path)` | Verovio → SVG per page → cairosvg PDF → pypdf merge |
| `_render_image_verovio(musicxml, page, fmt, dpi, output_path)` | Verovio → SVG → PNG or SVG file |
| `_render_pdf_musescore(musicxml, output_path)` | MuseScore CLI subprocess → PDF |
| `_render_image_musescore(musicxml, page, fmt, dpi, output_path)` | MuseScore CLI subprocess → PNG |
| `_get_pdf_page_count(pdf_path)` | Count pages via pypdf.PdfReader |
| `_get_image_dimensions(image_path)` | Get width/height via PIL Image.size |

Backend is detected once at module import time; it cannot change while the server is running.

**Measure ranges (UX Wave 3, B2).** The two public functions apply
`sheet_music_mcp_core.measures.select_measures(musicxml, measures)` once, before backend
dispatch. The `_render_*` backend functions never see a range: MuseScore and Verovio get the
same cut score, which keeps the key, time, clef, divisions and tempo in force at `start`.
`measures=None` returns the text unchanged. A bad range raises `MeasureRangeError`
(`INVALID_PARAMETER`, hint "This score has measures A–B.") before any backend runs.

**Viewer pages (`SvgPageRenderer`).** `server.page_renderer` keeps one Verovio toolkit and the
SHA-256 of the score it loaded. A call with the same score and layout only renders; a new width
or zoom re-applies the options and calls `redoLayout()`; a new score loads afresh (a failed load
clears the cache). The options are `ScoreView`'s: `page_layout()` plus `adjustPageHeight`,
`breaks: "auto"`, `footer: "none"`. A page past the end raises `INVALID_PARAMETER` with the hint
"This score has pages 1–N at this width and zoom."

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
call_tool("render_to_pdf", {musicxml | musicxml_path, output_path, measures?})
  │
  ├─ references: load_score (inline text, or the confined file)
  ├─ utils: validate_musicxml, generate_pdf_path
  ├─ engine: render_to_pdf → select_measures(musicxml, measures)   ← no-op without measures
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

## Score Viewer (MCP Apps)

```
 Host (Claude, VS Code, …)                      render-mcp
 ─────────────────────────                      ──────────
 tools/list ──────────────────────────────────► render_to_pdf / render_to_image
                                                  _meta.ui.resourceUri = ui://render/score-viewer
                                                render_page_svg  (only for UI clients;
                                                  _meta.ui.visibility = ["app"])
 resources/read ui://render/score-viewer ─────► score-viewer.html (text/html;profile=mcp-app)
 tools/call render_to_pdf {musicxml} ─────────► content (unchanged) + structuredContent
        │
        ▼  sandboxed iframe: tool-input = {musicxml}, tool-result = structuredContent
 ┌────────────────────────────────────────────────────────────────────────────────┐
 │ Score Viewer   openScore(): first renderer that starts and loads wins         │
 │                                                                                │
 │  1. ScoreView (Verovio WASM in the page)                                       │
 │       needs 'wasm-unsafe-eval' in the host CSP                                 │
 │            │ CompileError (CSP refused) / RendererUnavailable                  │
 │            ▼                                                                   │
 │  2. ServerScoreRenderer ── tools/call render_page_svg ─────────────────────────┼──► SvgPageRenderer
 │       {musicxml, page, width_px, zoom}  ◄── {svg, page, page_count} ───────────┼─── (cache by hash)
 │            │ RendererUnavailable                                               │
 │            ▼                                                                   │
 │  3. notice: "could not start the notation engine" + saved file path            │
 │                                                                                │
 │  #engine line under the score: data-engine="wasm" | "server"                   │
 └────────────────────────────────────────────────────────────────────────────────┘
```

**Why two paths.** The MCP Apps spec's default CSP for a resource without `_meta.ui.csp` has no
`'wasm-unsafe-eval'`, and `McpUiResourceCsp` only lets a server declare domains, so a server cannot
ask for it. Verovio's npm package ships only a WASM build. A host that enforces the default
therefore refuses to compile Verovio; the viewer then pages through server-rendered SVG. Both
paths use the same layout (`layoutFor` / `page_layout`, checked against
`ui/packages/kit/src/score/layout-cases.json` by Vitest and pytest), so pages look alike.

**Visibility.** `render_page_svg` carries `_meta.ui.visibility: ["app"]` (with the resource URI
when the HTML is packaged, without it otherwise). The core's `make_handlers` drops it from
`tools/list` for clients that do not advertise the `io.modelcontextprotocol/ui` extension, so the
model in Claude Code CLI or Cursor never sees it; `tools/call` still validates and runs it. It
takes inline MusicXML only (`additionalProperties: false`), never a path.

**Text font limitation.** Tempo-mark notes (♩ = 90) are glyphs from Verovio's SMuFL text font.
No `smuflTextFont` mode renders them under the default CSP: `embedded` (the default) is a
`data:` font, blocked because the policy has no `font-src`; `linked` imports a stylesheet from
verovio.org; `none` needs the font installed. Both paths keep `embedded`, so hosts that allow
`data:` fonts show the glyph, and pages match. Under the strict default the note vanishes and
"= 90" remains. Showing the SVG as `<img src="data:image/svg+xml,…">` would render it (an image
document loads its own fonts outside the page's CSP) but loses the SVG DOM that voice
highlighting needs; this is left for the findings report.

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
| `measures` reversed / outside the score / holding no bar | `INVALID_PARAMETER` with `hint` |
| Both or neither of `musicxml` / `musicxml_path` | `INVALID_PARAMETER` |
| `musicxml_path` outside the read roots, or wrong suffix | `INVALID_PARAMETER` (never echoes file content) |
| `musicxml_path` missing / too large / not MusicXML | `FILE_NOT_FOUND` / `FILE_TOO_LARGE` / `INVALID_INPUT` |
| No backend available | `PROCESSING_FAILED` |
| Verovio rendering error | `PROCESSING_FAILED` |
| MuseScore subprocess failure | `PROCESSING_FAILED` |
| `render_page_svg` page past the end of the layout | `INVALID_PARAMETER` with `hint` (page range) |
| `render_page_svg` with a path or unknown argument | `INVALID_PARAMETER` (schema) |
| `resources/read` of the viewer without a UI build | JSON-RPC `-32603`, `data.error_code` `UI_ASSET_MISSING` |
| `resources/read` of an unknown URI | JSON-RPC `-32602`, `data.error_code` `RESOURCE_NOT_FOUND` |

Render-tool errors are `isError` results; their `content` is the error JSON and they carry no
`structuredContent`.

---

## Key Dependencies

| Package | Role |
|---------|------|
| `verovio` ≥3.0 | MusicXML engraving → SVG (pure Python C++ binding, in-process) |
| `cairosvg` ≥2.7 | SVG → PNG / SVG → PDF conversion |
| `pypdf` ≥4.0 | PDF page count reading, multi-page PDF assembly |
| `Pillow` | PNG dimension reading |
| `mcp` | MCP protocol SDK |
| `sheet-music-mcp-core` ≥0.3 | Shared error envelope, `ProcessingError`, handler wiring (input validation, error results, app-only tool visibility), MCP Apps UI resources (`ui`, `make_resource_handlers`; 0.3.1), score references (`load_score`, `describe_score`) and output path confinement; see [docs/conventions.md](../../docs/conventions.md#shared-core-library) |

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
│       ├── server.py     ← MCP layer (tool registration, dispatch, UI registry)
│       ├── presenter.py  ← content + structuredContent, output schemas
│       ├── engine.py     ← Rendering logic (Verovio, cairosvg, pypdf, MuseScore, viewer pages)
│       ├── utils.py      ← Validation, path generation
│       └── ui/assets/score-viewer.html   ← built by ui/ (npm run copy-assets), gitignored
└── tests/
    ├── conftest.py                ← swaps ui_registry for in-memory assets (unbuilt by default)
    ├── test_server.py
    ├── test_engine.py
    ├── test_utils.py
    ├── test_score_references.py   ← musicxml_path, describe_score
    ├── test_measures.py           ← measures: backend spies, errors, a real Verovio cut
    ├── test_content_golden.py     ← render tools' content byte for byte (golden/render_content.json)
    ├── test_presenter.py
    ├── test_score_viewer.py       ← _meta.ui, resources, structuredContent
    ├── test_page_svg.py           ← page_layout parity, SvgPageRenderer cache (real Verovio)
    ├── test_render_page_svg.py    ← app-only tool: visibility, contract, errors
    ├── test_packaging.py          ← integration: wheel ships the viewer, AC-R1
    └── fixtures/
```
