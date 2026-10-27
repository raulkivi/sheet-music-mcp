# omr-mcp — Technical Architecture

## Overview

omr-mcp is a stateless MCP server that converts sheet music images to MusicXML. Every tool call is independent; no state is retained between calls.

Two selectable OMR backends are supported via an `engine` parameter (default `"oemer"`):
- **oemer** — fast, in-process, deep-learning (UNet + SVM). Flattens multi-staff (SATB) choir
  scores into a single sequential part instead of separate simultaneous parts — an architectural
  limitation (`oemer/build_system.py`'s rhythm-alignment code hard-asserts at most 2 simultaneous
  tracks per staff-group), confirmed 2026-08-16, not fixable by a dependency pin.
- **audiveris** (opt-in, added 2026-08-16) — external JVM-based engine, invoked as a subprocess.
  Correctly separates SATB scores into simultaneous parts. Requires 300+ DPI source images; larger
  first-use download (~80 MB vs. oemer's ~100 MB, but self-contained — bundles its own JRE, so no
  system Java dependency).

---

## Component Diagram

```
┌───────────────────────────────────────────────────────────┐
│                      MCP Client                           │
│              (Claude Desktop / web app)                   │
└──────────────────────────┬────────────────────────────────┘
                           │  stdio (JSON-RPC)
┌──────────────────────────▼────────────────────────────────┐
│                       server.py                           │
│                                                           │
│  list_tools()          → Tool definitions (6 tools)       │
│  call_tool(name, args) → dispatches to engine functions   │
│  _detect_input_format  → "path" | "base64"                │
│  _run_with_progress    → runs engine call off the event   │
│                           loop, sends MCP progress pings   │
│  main()                → stdio_server() entry point       │
└────────────┬──────────────────────────┬───────────────────┘
             │                          │
┌────────────▼────────────┐  ┌──────────▼───────────────────┐
│      omr_engine.py      │  │         utils.py             │
│                         │  │                              │
│  recognize_image(       │  │  validate_image_path()       │
│    path, engine=)       │  │  decode_base64_image()       │
│  recognize_image_to_    │  │  get_image_info()            │
│    file(path, engine=)  │  │  format_file_size()          │
│  recognize_images(      │  └──────────────────────────────┘
│    paths, engine=)      │
│  _merge_musicxml_pages()│
│  _run_oemer()           │
│  _run_audiveris()       │
│  _ensure_audiveris_     │
│    installed()          │
│  _extract_musicxml_     │
│    metadata()           │
└──────┬───────────┬──────┘
       │           │
┌──────▼──────┐ ┌──▼──────────────────────┐
│ oemer library│ │  Audiveris (subprocess) │
│ (in-process) │ │  self-contained JVM     │
│ UNet + SVM   │ │  bundle, downloaded to  │
│ ONNX Runtime │ │  ~/.cache/omr-mcp/      │
│              │ │  audiveris/ on first use│
└──────────────┘ └─────────────────────────┘
```

---

## Module Responsibilities

### `server.py`

Entry point and MCP protocol layer. Contains no business logic.

- Registers six tools with their JSON schemas
- Dispatches `call_tool` to the appropriate engine function, threading the optional `engine`
  argument through unchanged (default `"oemer"` applied at the `omr_engine.py` layer, not here)
- Handles format detection: determines whether an input is a file path or base64 string via `_detect_input_format`
- Decodes base64 input to a temporary file before passing to the engine
- Runs the (blocking, multi-second-to-multi-minute) engine call via `_run_with_progress`, which
  offloads it to a worker thread (`asyncio.to_thread`) and — if the client supplied an MCP
  `progressToken` — sends periodic elapsed-time heartbeat notifications until it completes
- Converts engine results and exceptions into `TextContent` JSON responses
- Delivers `recognize_sheet` / `recognize_sheets` successes through the core's
  `references.deliver_score` (`_deliver_recognized`): inline `musicxml`, or for large results
  (`return="auto"`) and `return="path"` a file under `<SHEET_MUSIC_OUTPUT_ROOT>/scores/` returned as
  `musicxml_path` + `score_summary` with a `ResourceLink`. The engine's error dicts skip this and
  stay inline
- Adds `score_summary` to `recognize_sheet_to_file` results by reading the written file with the
  core's `scores.read_score_file` + `score_summary` (`_written_score_summary`; `null` on failure)
- Starts the server with `mcp.server.stdio.stdio_server()`

**Format detection heuristic in `_detect_input_format`:**
- If the string starts with `data:` → `"base64"`
- If the string is longer than 500 chars and contains no `/` or `\` path separators → `"base64"`
- Otherwise → `"path"`

### `omr_engine.py`

Core processing logic. No MCP imports.

| Function | Description |
|----------|-------------|
| `recognize_image(image_path, engine="oemer")` | Run the selected engine on a single image; return MusicXML string + metadata |
| `recognize_image_to_file(input_path, output_path, engine="oemer")` | Same as above but write MusicXML to disk |
| `recognize_images(image_paths, engine="oemer")` | Process multiple pages with the selected engine; merge into one MusicXML document |
| `_run_oemer(image_path)` | Call `oemer.ete.extract()` in-process; return path to output MusicXML file |
| `_run_audiveris(image_path)` | Invoke the Audiveris subprocess (`-batch -export`), unzip its `.mxl` output, return path to the extracted MusicXML |
| `_ensure_audiveris_installed()` | Lazily download + extract Audiveris (`dpkg-deb -x`, no root) into `~/.cache/omr-mcp/audiveris/` on first use |
| `_ENGINE_RUNNERS` | `{"oemer": _run_oemer, "audiveris": _run_audiveris}` — dispatch table `recognize_image*` looks up `engine` in; an unknown key returns `INVALID_PARAMETER` |
| `_merge_musicxml_pages(pages)` | Stitch per-page MusicXML documents into one |
| `_extract_musicxml_metadata(xml)` | Regex-based extraction of stave count and measure count — counts *distinct* measure numbers rather than taking `max()`, since Audiveris numbers measures from 0 while oemer numbers from 1 |

### `utils.py`

Input validation and helper utilities. No engine logic.

| Function | Description |
|----------|-------------|
| `validate_image_path(path)` | Check file exists, extension is PNG/JPG/JPEG, size ≤ 50 MB |
| `decode_base64_image(data, output_path)` | Decode base64 (strips `data:` prefix), write to temp file, verify with Pillow |
| `get_image_info(path)` | Return width, height, format, mode, file size via Pillow |
| `format_file_size(bytes)` | Human-readable string (KB / MB) |
| `confine_output_path(path, suffixes)` | Re-export of `sheet_music_mcp_core.paths.confine_output_path` (UX Wave 2); the engine uses it for a caller-chosen `output_path` |

---

## Data Flow

### Single image recognition

```
call_tool("recognize_sheet", {image_path: "/path/scan.png"})
  │
  ├─ server.py: _detect_input_format → "path"
  ├─ utils.py: validate_image_path ──→ error if invalid
  ├─ omr_engine.py: recognize_image
  │     ├─ _run_oemer(image_path) → oemer.generate → "/tmp/oemer_out/score.xml"
  │     ├─ read MusicXML from output file
  │     └─ _extract_musicxml_metadata → {staves_detected, measures}
  └─ return {"musicxml": "...", "metadata": {...}}
```

### Base64 image input

```
call_tool("recognize_sheet", {image_base64: "<data>", mime_type: "image/jpeg"})
  │
  ├─ server.py: _detect_input_format → "base64"
  ├─ utils.py: decode_base64_image → /tmp/omr_XXXXX.jpg
  └─ (same as above from validate_image_path onwards)
```

### Multi-page recognition

```
call_tool("recognize_sheets", {image_paths: ["/p1.png", "/p2.png"]})
  │
  ├─ omr_engine.py: recognize_images
  │     ├─ recognize_image("/p1.png") → musicxml_1
  │     ├─ recognize_image("/p2.png") → musicxml_2
  │     └─ _merge_musicxml_pages([musicxml_1, musicxml_2])
  │           ├─ Parse each page with defusedxml.ElementTree
  │           ├─ For each subsequent page:
  │           │     find max measure number in base document
  │           │     append page's measures, renumbering from (max + 1)
  │           └─ Return merged XML string
  └─ return {"musicxml": "...", "page_count": 2, "metadata": {...}}
```

---

## Multi-Page Merge Algorithm

Pages are merged by appending measures from each successive page to the corresponding part in the base document.

```
base_doc = parse(page_1_xml)
for page in pages[1:]:
    page_doc = parse(page_xml)
    for part_index, part in enumerate(page_doc.parts):
        base_part = base_doc.parts[part_index]   # matched by index
        last_num = max(m.number for m in base_part.measures)
        for measure in part.measures:
            measure.number += last_num            # renumber sequentially
            base_part.append(measure)
return serialize(base_doc)
```

Parts are matched by index (not by name), so the number of parts must be consistent across pages.

---

## OMR Engine Integration

Both engines are reached through the same `_ENGINE_RUNNERS` dispatch table — each entry is a
function taking an image path and returning a path to a MusicXML file on disk. `recognize_image()`
et al. don't otherwise care which engine produced it.

### oemer

`_run_oemer(image_path)` calls `oemer.ete.extract(args)` directly as a library function (not a
subprocess) — this is the real entry point; an earlier version of this wrapper called a
`oemer.generate()` API that never existed in the installed package (100%-blocking bug, fixed
2026-08-15, see docs/HANDOVER.md). oemer:

1. Runs staffline detection (UNet segmentation model)
2. Runs symbol segmentation (UNet model)
3. Classifies symbols (SVM)
4. Writes a MusicXML file to a subdirectory near the input image
5. Returns the path to that file

Model checkpoints are downloaded on first call (~100 MB) and cached inside oemer's own installed
package directory (not `~/.cache/oemer/`, despite that being a natural-seeming guess — see
`_oemer_checkpoint_path()`). Subsequent calls use the cached models.

**Known architectural limitation**: oemer's `build_system.py::MeasureContainer.align_symbols()`
hard-asserts at most 2 simultaneous tracks per staff-group. A 4–5 voice SATB score either gets
force-flattened to 1 track (`further_infer_track_nums()`) or crashes outright with
`AssertionError: <n>`. This is why `engine="audiveris"` exists.

### Audiveris

`_run_audiveris(image_path)` invokes the Audiveris binary as a subprocess:

```
Audiveris -batch -export -output <temp_dir> <image_path>
```

`_ensure_audiveris_installed()` lazily downloads a self-contained Ubuntu `.deb` release (bundles
its own JRE — no system Java dependency) on first use and extracts it directly with
`dpkg-deb -x` into `~/.cache/omr-mcp/audiveris/` (override via `OMR_AUDIVERIS_HOME`) — never a
system-wide `dpkg -i`/`apt install`, so it needs no root and never touches system package state.

Audiveris writes a compressed `.mxl` (zip containing one `.xml` entry) named after the input
file's stem into the output directory. `_run_audiveris()` unzips it, extracts the MusicXML, and
writes it back out as a plain `.musicxml` file so the rest of the pipeline (which expects a path
to a readable MusicXML file, matching oemer's return contract) doesn't need to know the
difference.

**Failure detection is output-based, not exit-code-based**: Audiveris can exit `0` while rejecting
every sheet in a batch (e.g. resolution too low for reliable staff-line detection) — a rejected
sheet's warning is `WARN ... too low interline value ... try 300 DPI`, but the process itself
still "succeeds." `_run_audiveris()` checks for the expected output `.mxl` file's existence rather
than trusting the subprocess return code.

**Resolution pre-check**: before dispatching to `_run_audiveris()`, `recognize_image`,
`recognize_image_to_file` and `recognize_images` call `utils.check_resolution(path)`, a pure
function that reads only the image header and classifies the longest side against
`RESOLUTION_MIN_LONG_SIDE_PX` (1500) and `RESOLUTION_RECOMMENDED_LONG_SIDE_PX` (2500) into
`ok` / `low` / `too_small`. `too_small` returns `INVALID_INPUT` with a `hint` in milliseconds,
where Audiveris would otherwise start a JVM and then reject the sheet; `low` adds a top-level
`warnings` entry. `recognize_images` checks every page first and fails fast, naming the page.
oemer is never checked, and an image Pillow can't read skips the check.

Verified 2026-08-16 against both a case oemer crashes on (`Ave_verum_corpus_-_William_Byrd`, 5
simultaneous tracks) and a case oemer silently flattens (a single-page PDMX SATB sample): Audiveris
correctly exported 4 separate parts in both, matching the ground-truth Soprano/Alto/Tenor/Bass
structure and measure ranges. Runs took ~7–15 seconds per page in testing — comparable to or
faster than oemer's ~90–100s, despite the larger subprocess/JVM-startup overhead per call.

Metadata (stave count, measure count) is extracted by scanning the returned MusicXML with regexes rather than a full parse, for speed — shared between both engines.

---

## Error Handling

All errors are returned as JSON text content rather than raising MCP protocol errors.

```json
{"error": "File not found: /path/scan.png", "error_code": "FILE_NOT_FOUND"}
```

| Scenario | Code |
|----------|------|
| File not found | `FILE_NOT_FOUND` |
| Unsupported image format | `UNSUPPORTED_FORMAT` |
| Unknown `engine` value | `INVALID_PARAMETER` |
| Image too large (> 50 MB) | `INVALID_INPUT` |
| Base64 decode failure | `INVALID_INPUT` |
| Pillow cannot open image | `INVALID_INPUT` |
| `engine="audiveris"` and the image's long side is < 1500 px (pre-check, with `hint`) | `INVALID_INPUT` |
| oemer processing error | `PROCESSING_FAILED` |
| Audiveris rejects the sheet (e.g. resolution too low) or any other Audiveris failure | `PROCESSING_FAILED` |

---

## Key Dependencies

| Package | Role |
|---------|------|
| `oemer` | Default OMR engine — UNet + SVM, ONNX Runtime |
| `Pillow` | Image validation and info extraction |
| `defusedxml` | Safe XML parsing (prevents XXE attacks) |
| `mcp` | MCP protocol SDK |
| `sheet-music-mcp-core` | Shared error envelope, `ProcessingError` and handler wiring (input validation, error results); see [docs/conventions.md](../../docs/conventions.md#shared-core-library) |

No system libraries are required for the default (`oemer`) path. ONNX Runtime is bundled with the
oemer pip package. `engine="audiveris"` is not a Python dependency — it's a self-contained binary
(bundling its own JRE) downloaded lazily into `~/.cache/omr-mcp/audiveris/` on first use of that
engine; `dpkg-deb` (part of `dpkg`, present on virtually all Debian/Ubuntu systems) is required to
extract it.

---

## Server Startup

```python
# server.py main()
async def _run():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

asyncio.run(_run())
```

The server process is single-threaded, but engine calls no longer block the asyncio event loop:
`_run_with_progress()` (added 2026-08-16) runs them via `asyncio.to_thread`, so the stdio
transport stays responsive during a multi-second-to-multi-minute recognition call. Each tool call
is still handled one at a time end-to-end from the caller's perspective — there's no concurrent
tool execution, just a non-blocked event loop during the wait.

---

## File Layout

```
omr-mcp/
├── pyproject.toml
├── src/
│   └── omr_mcp/
│       ├── __init__.py
│       ├── server.py        ← MCP layer (tool registration, dispatch)
│       ├── omr_engine.py    ← Business logic (oemer, merge)
│       └── utils.py         ← Input validation, base64, image info
└── tests/
    ├── test_server.py
    ├── test_omr.py
    ├── test_utils.py
    └── test_samples/
        └── pdmx_satb_samples/  ← PNG + MXL fixture pairs
```
