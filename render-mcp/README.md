# render-mcp

<!-- mcp-name: io.github.raulkivi/render-mcp -->

MCP server that renders MusicXML scores to PDF or PNG images.

## What it does

Takes a MusicXML document and produces print-ready PDFs or screen-ready PNG images. Uses Verovio for layout and engraving — no external tools or GUI required.

## Tools

| Tool | Description |
|------|-------------|
| `render_to_pdf` | Render the full score to a multi-page PDF file |
| `render_to_image` | Render a single page to PNG or SVG |
| `list_capabilities` | Return server metadata: backend version, supported formats, available renderers |
| `health_check` | Check whether all runtime dependencies are available and the server is ready to render scores |

## Installation

Quick install: run `./install.sh` for one-command setup, or see [SETUP.md](SETUP.md) for a
non-technical walkthrough. Ready-made client configs (Claude Desktop, Cursor, Windsurf, Continue,
Zed) are in [`examples/`](examples/). If something isn't working, check [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

Manual setup:

```bash
cd render-mcp
uv sync
```

`libcairo` is required for PNG output:

```bash
# Ubuntu / Debian (usually pre-installed on desktop systems)
sudo apt install libcairo2
```

## Running

```bash
uv run render-mcp
```

No environment variables required.

## Usage examples

```json
// Render full score to PDF
{
  "tool": "render_to_pdf",
  "arguments": {
    "musicxml_path": "/path/to/score.mxl",
    "output_path": "/tmp/score.pdf"
  }
}

// Render page 1 to PNG at 150 DPI
{
  "tool": "render_to_image",
  "arguments": {
    "musicxml_path": "/path/to/score.mxl",
    "output_path": "/tmp/page1.png",
    "page": 1,
    "dpi": 150
  }
}
```

DPI range: 72–600. Default: 150. Page numbers are 1-indexed.

## Testing

```bash
# All tests including integration (Verovio runs in-process, no external tool needed)
VIRTUAL_ENV= .venv/bin/pytest tests/ -v
```

## Dependencies

- [verovio](https://www.verovio.org/) — MusicXML engraving to SVG (pure Python, in-process)
- [cairosvg](https://cairosvg.org/) — SVG to PNG/PDF conversion
- [pypdf](https://pypdf.readthedocs.io/) — multi-page PDF assembly
- [Pillow](https://python-pillow.org/) — image utilities
- [mcp](https://github.com/modelcontextprotocol/python-sdk) — MCP protocol

## System requirements

- Python 3.11+
- `libcairo2` shared library (for PNG/PDF output via cairosvg)
