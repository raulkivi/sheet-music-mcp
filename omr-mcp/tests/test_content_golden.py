"""Golden test: the tools' ``content`` stays byte-identical (MCP Apps Recognition Review).

Linking the Recognition Review and adding ``structuredContent`` must not change what text-only
clients see. The golden file was recorded before the presenter existed; regenerate it only for an
intended change with ``OMR_GOLDEN_UPDATE=1 pytest tests/test_content_golden.py``.
"""

import json
import os
import re
from pathlib import Path

import pytest

import omr_mcp.server as srv

GOLDEN = Path(__file__).parent / "golden" / "omr_content.json"
SMALL_XML = "<score-partwise><part id='P1'/></score-partwise>"
LARGE_XML = "<score-partwise>" + "<note/>" * 3000 + "</score-partwise>"
STAMP = re.compile(r"\d{8}-\d{6}-\d{6}")


def _fake_page(xml, staves=1):
    return lambda path, engine="oemer": {
        "musicxml": xml,
        "metadata": {"source": path, "staves_detected": staves, "measures": 8,
                     "processing_time_ms": 12, "engine": engine},
    }


def _fake_pages(xml):
    return lambda paths, engine="oemer": {
        "musicxml": xml,
        "metadata": {"page_count": len(paths), "staves_detected": 2, "measures": 16,
                     "processing_time_ms": 30, "engine": engine},
    }


def _fake_file(out):
    def fake(input_path, output_path, engine="oemer"):
        out.write_text(SMALL_XML, encoding="utf-8")
        return {"output_path": str(out), "metadata": {"source": input_path, "staves_detected": 4,
                                                      "measures": 8, "processing_time_ms": 5, "engine": engine}}
    return fake


def _normalised(blocks, tmp_path) -> list[dict]:
    dumped = json.dumps([b.model_dump(mode="json", by_alias=True, exclude_none=True) for b in blocks])
    dumped = dumped.replace(str(tmp_path.resolve()), "<TMP>").replace(str(tmp_path), "<TMP>")
    return json.loads(STAMP.sub("<STAMP>", dumped))


async def _all_contents(tmp_path, monkeypatch) -> dict:
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
    image = tmp_path / "page.png"
    image.write_bytes(b"x")
    contents = {}

    async def record(name, tool, arguments):
        contents[name] = _normalised(await srv.call_tool(tool, arguments), tmp_path)

    monkeypatch.setattr(srv, "recognize_image", _fake_page(SMALL_XML))
    await record("sheet_inline", "recognize_sheet", {"image": str(image)})
    await record("sheet_audiveris", "recognize_sheet", {"image": str(image), "engine": "audiveris"})
    monkeypatch.setattr(srv, "recognize_image", _fake_page(LARGE_XML))
    await record("sheet_auto_path", "recognize_sheet", {"image": str(image)})
    await record("sheet_bad_return", "recognize_sheet", {"image": str(image), "return": "bogus"})
    monkeypatch.setattr(srv, "recognize_image", lambda p, engine="oemer": {
        "error": "File not found: x", "error_code": "FILE_NOT_FOUND"})
    await record("sheet_engine_error", "recognize_sheet", {"image": str(image)})

    monkeypatch.setattr(srv, "recognize_images", _fake_pages(SMALL_XML))
    await record("sheets_inline", "recognize_sheets", {"images": [str(image), str(image)]})
    monkeypatch.setattr(srv, "recognize_images", _fake_pages(LARGE_XML))
    await record("sheets_auto_path", "recognize_sheets", {"images": [str(image), str(image)]})
    await record("sheets_not_list", "recognize_sheets", {"images": "x"})

    monkeypatch.setattr(srv, "recognize_image_to_file", _fake_file(tmp_path / "out.musicxml"))
    await record("to_file", "recognize_sheet_to_file", {"input_path": str(image)})
    return contents


async def test_content_matches_the_golden_file(tmp_path, monkeypatch):
    contents = await _all_contents(tmp_path, monkeypatch)

    if os.environ.get("OMR_GOLDEN_UPDATE") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(contents, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip("golden file rewritten")

    assert contents == json.loads(GOLDEN.read_text(encoding="utf-8"))
