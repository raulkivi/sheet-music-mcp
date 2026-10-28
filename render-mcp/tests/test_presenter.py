"""Presenter: engine results to ``content`` plus ``structuredContent`` (MCP Apps spike, step 4)."""

import json

import jsonschema
import pytest

from render_mcp.presenter import (
    IMAGE_OUTPUT_SCHEMA,
    PDF_OUTPUT_SCHEMA,
    present_image,
    present_pdf,
)

from .test_result_content import SVG, TINY_PNG


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "score.pdf"
    path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    return str(path)


def _image(tmp_path, fmt="png"):
    path = tmp_path / f"page.{fmt}"
    path.write_bytes(TINY_PNG if fmt == "png" else SVG)
    result = {
        "image_path": str(path),
        "format": fmt,
        "page": 2,
        "total_pages": 3,
        "backend": "verovio",
    }
    if fmt == "png":
        result.update(width_px=1, height_px=1)
    return result


class TestPdf:
    def test_content_is_the_json_text_then_the_file_link(self, pdf):
        content, _ = present_pdf(pdf, 2, "verovio")

        assert content[0].text == json.dumps({"pdf_path": pdf, "page_count": 2, "backend": "verovio"}, indent=2)
        assert [block.type for block in content] == ["text", "resource_link"]
        assert content[1].mime_type == "application/pdf"

    def test_structured_content_is_the_same_data(self, pdf):
        _, structured = present_pdf(pdf, 2, "verovio")

        assert structured == {"pdf_path": pdf, "page_count": 2, "backend": "verovio"}
        jsonschema.validate(structured, PDF_OUTPUT_SCHEMA)

    def test_backend_may_be_unknown(self, pdf):
        # detect_backend() returns None when nothing is installed; the schema must allow it.
        _, structured = present_pdf(pdf, 1, None)

        jsonschema.validate(structured, PDF_OUTPUT_SCHEMA)

    def test_a_missing_file_gets_no_link(self, tmp_path):
        content, _ = present_pdf(str(tmp_path / "gone.pdf"), 1, "verovio")

        assert [block.type for block in content] == ["text"]


class TestImage:
    def test_png_content_is_text_image_then_link(self, tmp_path):
        result = _image(tmp_path)

        content, _ = present_image(result)

        assert content[0].text == json.dumps(result, indent=2)
        assert [block.type for block in content] == ["text", "image", "resource_link"]
        assert content[2].mime_type == "image/png"

    def test_png_structured_content_mirrors_the_text(self, tmp_path):
        result = _image(tmp_path)

        _, structured = present_image(result)

        assert structured == result
        assert {"image_path", "format", "page", "width_px", "height_px"} <= set(structured)
        jsonschema.validate(structured, IMAGE_OUTPUT_SCHEMA)

    def test_svg_has_a_link_and_no_pixel_size(self, tmp_path):
        result = _image(tmp_path, "svg")

        content, structured = present_image(result)

        assert [block.type for block in content] == ["text", "resource_link"]
        assert content[1].mime_type == "image/svg+xml"
        assert "width_px" not in structured
        jsonschema.validate(structured, IMAGE_OUTPUT_SCHEMA)

    def test_structured_content_is_a_copy(self, tmp_path):
        result = _image(tmp_path)

        _, structured = present_image(result)
        structured["page"] = 99

        assert result["page"] == 2

    def test_schemas_reject_a_wrong_shape(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"pdf_path": "/x.pdf"}, PDF_OUTPUT_SCHEMA)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"image_path": "/x.png", "format": "gif", "page": 1}, IMAGE_OUTPUT_SCHEMA)
