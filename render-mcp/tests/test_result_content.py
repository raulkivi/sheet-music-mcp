"""Result content blocks appended after the JSON text (docs/conventions.md, Result Content)."""

import base64
import json
from pathlib import Path

import pytest

import render_mcp.server as server
from render_mcp.engine import ProcessingError
from render_mcp.server import call_tool

from .test_server import VALID_MUSICXML

# Smallest valid PNG: 1x1 transparent pixel.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>'


@pytest.fixture(autouse=True)
def output_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
    return tmp_path


def _fake_render_to_image(data: bytes):
    def fake(musicxml, page, fmt, dpi, output_path):
        Path(output_path).write_bytes(data)
        return {
            "image_path": output_path,
            "format": fmt,
            "page": page,
            "total_pages": 1,
            "backend": "verovio",
            "width_px": 1,
            "height_px": 1,
        }

    return fake


def _fake_render_to_pdf(musicxml, output_path):
    Path(output_path).write_bytes(b"%PDF-1.4\n%%EOF\n")
    return output_path, 2


# ---------------------------------------------------------------------------
# render_to_image
# ---------------------------------------------------------------------------


class TestRenderToImagePng:
    async def test_json_block_unchanged(self, monkeypatch, output_root):
        fake = _fake_render_to_image(TINY_PNG)
        monkeypatch.setattr(server, "render_to_image", fake)
        out = str(output_root / "page.png")

        result = await call_tool("render_to_image", {"musicxml": VALID_MUSICXML, "output_path": out})

        expected = fake(None, 1, "png", 150, str(output_root / "expected.png"))
        expected["image_path"] = out
        assert result[0].type == "text"
        assert result[0].text == json.dumps(expected, indent=2)

    async def test_appends_image_then_link(self, monkeypatch, output_root):
        monkeypatch.setattr(server, "render_to_image", _fake_render_to_image(TINY_PNG))
        out = output_root / "page.png"

        result = await call_tool("render_to_image", {"musicxml": VALID_MUSICXML, "output_path": str(out)})

        assert [block.type for block in result] == ["text", "image", "resource_link"]
        image, link = result[1], result[2]
        assert image.mime_type == "image/png"
        assert base64.b64decode(image.data) == TINY_PNG
        assert link.mime_type == "image/png"
        assert link.uri == out.resolve().as_uri()
        assert link.uri.startswith("file://")
        assert link.size == len(TINY_PNG)

    async def test_png_over_limit_gets_link_only(self, monkeypatch, output_root):
        big = TINY_PNG + b"\0" * (1024 * 1024)
        monkeypatch.setattr(server, "render_to_image", _fake_render_to_image(big))
        out = output_root / "big.png"

        result = await call_tool("render_to_image", {"musicxml": VALID_MUSICXML, "output_path": str(out)})

        assert [block.type for block in result] == ["text", "resource_link"]
        assert result[1].mime_type == "image/png"
        assert result[1].uri == out.resolve().as_uri()

    async def test_auto_generated_path_is_linked(self, monkeypatch, output_root):
        monkeypatch.setattr(server, "render_to_image", _fake_render_to_image(TINY_PNG))
        monkeypatch.setattr(
            server, "generate_image_path", lambda output_path, fmt: str(output_root / f"auto.{fmt}")
        )

        result = await call_tool("render_to_image", {"musicxml": VALID_MUSICXML})

        data = json.loads(result[0].text)
        assert result[-1].type == "resource_link"
        assert result[-1].uri == Path(data["image_path"]).resolve().as_uri()


class TestRenderToImageSvg:
    async def test_svg_gets_link_without_image(self, monkeypatch, output_root):
        monkeypatch.setattr(server, "render_to_image", _fake_render_to_image(SVG))
        out = output_root / "page.svg"

        result = await call_tool(
            "render_to_image", {"musicxml": VALID_MUSICXML, "format": "svg", "output_path": str(out)}
        )

        assert [block.type for block in result] == ["text", "resource_link"]
        assert result[1].mime_type == "image/svg+xml"
        assert result[1].uri == out.resolve().as_uri()
        assert json.loads(result[0].text)["format"] == "svg"


class TestRenderToImageErrors:
    async def test_processing_error_has_no_extra_blocks(self, monkeypatch):
        def fail(*args):
            raise ProcessingError("boom", "PROCESSING_FAILED")

        monkeypatch.setattr(server, "render_to_image", fail)

        result = await call_tool("render_to_image", {"musicxml": VALID_MUSICXML})

        assert len(result) == 1
        assert json.loads(result[0].text)["error_code"] == "PROCESSING_FAILED"

    async def test_validation_error_has_no_extra_blocks(self):
        result = await call_tool("render_to_image", {"musicxml": VALID_MUSICXML, "page": 0})

        assert len(result) == 1
        assert "error" in json.loads(result[0].text)

    async def test_missing_file_has_no_extra_blocks(self, monkeypatch, output_root):
        def no_file(musicxml, page, fmt, dpi, output_path):
            return {"image_path": output_path, "format": fmt, "page": page}

        monkeypatch.setattr(server, "render_to_image", no_file)

        result = await call_tool(
            "render_to_image", {"musicxml": VALID_MUSICXML, "output_path": str(output_root / "x.png")}
        )

        assert len(result) == 1


# ---------------------------------------------------------------------------
# render_to_pdf
# ---------------------------------------------------------------------------


class TestRenderToPdf:
    async def test_json_block_unchanged_and_link_appended(self, monkeypatch, output_root):
        monkeypatch.setattr(server, "render_to_pdf", _fake_render_to_pdf)
        monkeypatch.setattr(server, "detect_backend", lambda: "verovio")
        out = output_root / "score.pdf"

        result = await call_tool("render_to_pdf", {"musicxml": VALID_MUSICXML, "output_path": str(out)})

        expected = {"pdf_path": str(out), "page_count": 2, "backend": "verovio"}
        assert result[0].type == "text"
        assert result[0].text == json.dumps(expected, indent=2)
        assert [block.type for block in result] == ["text", "resource_link"]
        link = result[1]
        assert link.mime_type == "application/pdf"
        assert link.uri == out.resolve().as_uri()
        assert link.name == "score.pdf"

    async def test_error_has_no_extra_blocks(self, monkeypatch):
        def fail(*args):
            raise ProcessingError("no backend", "BACKEND_UNAVAILABLE")

        monkeypatch.setattr(server, "render_to_pdf", fail)

        result = await call_tool("render_to_pdf", {"musicxml": VALID_MUSICXML})

        assert len(result) == 1
        assert json.loads(result[0].text)["error_code"] == "BACKEND_UNAVAILABLE"
