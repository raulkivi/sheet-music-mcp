# omr-mcp

MCP server that converts sheet music images to MusicXML using optical music recognition (OMR).

## What it does

Takes a photo or scan of printed sheet music and returns a MusicXML document. Handles single pages or multi-page scores. Feeds directly into the rest of the choir-music-assistant pipeline.

Two selectable OMR backends, via an optional `engine` argument on the recognition tools:
- **`oemer`** (default) — fast, no extra download beyond the ~100 MB model checkpoints. Best for
  single/two-staff scores; flattens multi-staff (SATB) choir scores into one part (see "Known
  limitations" below).
- **`audiveris`** — correctly separates multi-staff SATB scores into simultaneous parts. Requires
  300+ DPI source images and a larger (~80 MB) first-use download; runs as a subprocess.

## Tools

| Tool | Description |
|------|-------------|
| `recognize_sheet` | Convert a single image (file path or base64) to MusicXML string |
| `recognize_sheet_to_file` | Convert a single image and write MusicXML to a file |
| `recognize_sheets` | Process multiple pages and merge them into one MusicXML document |
| `list_capabilities` | Return server metadata: backend version, input/output formats, available tools |
| `list_supported_formats` | (Deprecated — use `list_capabilities`) List supported input and output formats |
| `health_check` | Check that all runtime dependencies are available and return a human-readable status summary; useful on first run |

## Installation

```bash
cd omr-mcp
uv sync
```

On first run, oemer downloads ~100 MB of model checkpoints. This happens once and is cached.

**Quick install:** `bash install.sh` sets up everything in one command and prints a ready-to-paste
client config — see [SETUP.md](SETUP.md). Ready-made configs for Claude Desktop, Cursor, Windsurf,
Continue, and Zed are in [`examples/`](examples/). Having trouble? Check
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Running

```bash
uv run omr-mcp
```

No environment variables required.

## Claude Desktop configuration

```json
{
  "mcpServers": {
    "omr": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/omr-mcp", "run", "omr-mcp"]
    }
  }
}
```

## Usage examples

```json
// Recognize a single image file (default engine: oemer)
{"tool": "recognize_sheet", "arguments": {"image": "/path/to/scan.png", "format": "path"}}

// Recognize from base64-encoded image
{"tool": "recognize_sheet", "arguments": {"image": "<base64 data>", "format": "base64"}}

// Recognize a multi-staff SATB choir score with correct voice separation (300+ DPI source required)
{"tool": "recognize_sheet", "arguments": {"image": "/path/to/satb_scan.png", "engine": "audiveris"}}

// Process multiple pages into one score
{"tool": "recognize_sheets", "arguments": {"images": ["/path/page1.png", "/path/page2.png"]}}

// Save result directly to file
{"tool": "recognize_sheet_to_file", "arguments": {"input_path": "/path/scan.png", "output_path": "/tmp/score.musicxml"}}
```

## Testing

```bash
# Unit tests (fast, no model required)
VIRTUAL_ENV= .venv/bin/pytest tests/ -v

# Integration tests (~10 min one-time model-checkpoint download, then ~90-100s per page on CPU)
VIRTUAL_ENV= .venv/bin/pytest tests/ -v -m integration
```

## Test samples

SATB a cappella samples are available in `test_samples/pdmx_satb_samples/`:

```
pdmx_satb_samples/
├── mxl/    # MusicXML ground truth
├── pdf/    # PDF scores
└── png/    # PNG images (OMR input)
```

Source: [PDMX dataset](https://zenodo.org/records/14648209) — 250K+ public domain scores.

## Dependencies

- [oemer](https://github.com/BreezeWhite/oemer) — default deep learning OMR engine (UNet + SVM, ONNX Runtime)
- `onnxruntime>=1.30` — releases after 1.19 reject the negative ConvTranspose pads baked into oemer's `unet_big` checkpoint; `onnx_compat.py` rewrites them into the equivalent `output_padding` before each recognition (needs `onnx`). This allows Python 3.11–3.14 (see `docs/HANDOVER.md` gotchas)
- `opencv-python-headless==4.10.0.84` — pinned; 5.x changed `cv2.HoughLinesP()`'s return shape, which crashes oemer's staffline extraction (see `pyproject.toml` comments / `docs/HANDOVER.md` gotchas)
- [Pillow](https://python-pillow.org/) — image loading and validation
- [defusedxml](https://github.com/tiran/defusedxml) — safe XML parsing
- [mcp](https://github.com/modelcontextprotocol/python-sdk) — MCP protocol
- [Audiveris](https://github.com/Audiveris/audiveris) — optional alternate OMR engine (`engine="audiveris"`). Not a Python dependency: a self-contained binary (bundles its own JRE) downloaded automatically on first use of that engine. Requires `dpkg-deb` (present on virtually all Debian/Ubuntu systems) to extract it — no root/system install.

## Known limitations

- **oemer's default output loses SATB voice structure.** oemer reads multi-staff choir systems
  sequentially rather than simultaneously, so a 4–5 voice SATB score comes out as a single merged
  `<part>` with the clef alternating back and forth, instead of one part per voice — real data
  loss, not a benign modeling difference (confirmed by inspecting generated MusicXML), and
  architectural in oemer itself (its rhythm-alignment code hard-asserts at most 2 simultaneous
  staff tracks — see [docs/HANDOVER.md](docs/HANDOVER.md)). **Use `engine="audiveris"`** for
  multi-staff choir scores — it correctly separates voices into simultaneous parts, verified
  against real fixtures. Requires 300+ DPI source images.

## Performance notes

- Processing time: ~90–100s per page on CPU for `oemer` once its model checkpoints are cached;
  ~7–15s per page for `audiveris` in testing (despite JVM subprocess startup overhead)
- Output may vary slightly between runs (both engines) — do not assert on exact XML equality
- The generated MusicXML is functionally correct but may not pass strict schema validation

## System requirements

- Python 3.11+
- No system libraries required (ONNX Runtime is bundled via pip)
