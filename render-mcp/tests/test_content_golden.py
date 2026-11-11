"""Golden test: the render tools' ``content`` stays byte-identical (MCP Apps spike, DoD-1).

The UI linking and ``structuredContent`` must not change what text-only clients see. The golden
file was recorded before the presenter existed; regenerate it only for an intended change with
``RENDER_GOLDEN_UPDATE=1 pytest tests/test_content_golden.py``.
"""

import json
import os
from pathlib import Path

import pytest

import render_mcp.server as server
from render_mcp.engine import ProcessingError
from render_mcp.server import call_tool

from .test_result_content import SVG, TINY_PNG
from .test_server import VALID_MUSICXML

GOLDEN = Path(__file__).parent / "golden" / "render_content.json"


def _image_engine(musicxml, page, fmt, dpi, output_path, measures=None):
    data = SVG if fmt == "svg" else TINY_PNG
    Path(output_path).write_bytes(data)
    result = {
        "image_path": output_path,
        "format": fmt,
        "page": page,
        "total_pages": 3,
        "backend": "verovio",
    }
    if fmt == "png":
        result.update(width_px=1, height_px=1)
    return result


def _pdf_engine(musicxml, output_path, measures=None):
    Path(output_path).write_bytes(b"%PDF-1.4\n%%EOF\n")
    return output_path, 2 if measures is None else 1


def _failing_engine(error):
    def fail(*args, **kwargs):
        raise error

    return fail


# (name, tool, arguments relative to the output root, engine override or None)
CASES = [
    ("pdf", "render_to_pdf", {"output_path": "score.pdf"}, None),
    ("pdf_measures", "render_to_pdf", {"output_path": "cut.pdf", "measures": [1, 1]}, None),
    ("pdf_from_path", "render_to_pdf", {"path": True, "output_path": "from-path.pdf"}, None),
    ("png", "render_to_image", {"output_path": "page.png", "page": 2, "dpi": 300}, None),
    ("svg", "render_to_image", {"output_path": "page.svg", "format": "svg"}, None),
    ("png_measures", "render_to_image", {"output_path": "cut.png", "measures": [1, 1]}, None),
    ("invalid_xml", "render_to_pdf", {"musicxml": "<nope/>"}, None),
    ("bad_page", "render_to_image", {"page": 0}, None),
    ("bad_dpi", "render_to_image", {"dpi": 5}, None),
    ("no_score", "render_to_pdf", {"no_score": True}, None),
    (
        "engine_error_with_hint",
        "render_to_image",
        {"output_path": "e.png"},
        ProcessingError("Measures 9-12 are outside the score.", "INVALID_PARAMETER", hint="This score has measures 1-4."),
    ),
    ("engine_crash", "render_to_pdf", {"output_path": "crash.pdf"}, RuntimeError("cairo exploded")),
]


async def _content(root: Path, tool: str, spec: dict, error, monkeypatch) -> list[dict]:
    monkeypatch.setattr(server, "render_to_image", _failing_engine(error) if error else _image_engine)
    monkeypatch.setattr(server, "render_to_pdf", _failing_engine(error) if error else _pdf_engine)
    monkeypatch.setattr(server, "detect_backend", lambda: "verovio")
    arguments = dict(spec)
    if arguments.pop("path", False):
        score = root / "score.musicxml"
        score.write_text(VALID_MUSICXML, encoding="utf-8")
        arguments["musicxml_path"] = str(score)
    elif not arguments.pop("no_score", False):
        arguments.setdefault("musicxml", VALID_MUSICXML)
    if "output_path" in arguments:
        arguments["output_path"] = str(root / arguments["output_path"])
    blocks = await call_tool(tool, arguments)
    text = json.dumps([block.model_dump(mode="json", by_alias=True, exclude_none=True) for block in blocks])
    return json.loads(text.replace(str(root.resolve()), "<ROOT>").replace(str(root), "<ROOT>"))


async def _all_contents(tmp_path, monkeypatch) -> dict:
    contents = {}
    for name, tool, spec, error in CASES:
        root = tmp_path / name
        root.mkdir()
        monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(root))
        contents[name] = await _content(root, tool, spec, error, monkeypatch)
    return contents


async def test_content_matches_the_golden_file(tmp_path, monkeypatch):
    contents = await _all_contents(tmp_path, monkeypatch)

    if os.environ.get("RENDER_GOLDEN_UPDATE") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(contents, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip("golden file rewritten")

    assert contents == json.loads(GOLDEN.read_text(encoding="utf-8"))
