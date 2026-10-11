"""Tests for render_mcp.utils."""

import pytest
from render_mcp.utils import (
    validate_musicxml,
    validate_image_format,
    validate_dpi,
    validate_page,
    generate_pdf_path,
    generate_image_path,
    RENDER_OUTPUT_DIR,
)


class TestValidateMusicxml:
    def test_valid_score_partwise(self):
        ok, err = validate_musicxml('<score-partwise version="3.1"><part-list/></score-partwise>')
        assert ok
        assert err == ""

    def test_valid_score_timewise(self):
        ok, err = validate_musicxml("<score-timewise/>")
        assert ok

    def test_empty_string(self):
        ok, err = validate_musicxml("")
        assert not ok
        assert "empty" in err.lower()

    def test_whitespace_only(self):
        ok, err = validate_musicxml("   \n  ")
        assert not ok

    def test_invalid_xml(self):
        ok, err = validate_musicxml("not xml at all")
        assert not ok
        assert "Invalid XML" in err

    def test_wrong_root_element(self):
        ok, err = validate_musicxml("<root><child/></root>")
        assert not ok
        assert "score-partwise" in err

    def test_xml_with_namespace(self):
        ok, err = validate_musicxml(
            '<score-partwise xmlns="http://www.musicxml.org/dtds/partwise.dtd"/>'
        )
        assert ok


class TestValidateImageFormat:
    def test_png_valid(self):
        ok, err = validate_image_format("png")
        assert ok
        assert err == ""

    def test_svg_valid(self):
        ok, err = validate_image_format("svg")
        assert ok

    def test_invalid_format(self):
        ok, err = validate_image_format("jpg")
        assert not ok
        assert "jpg" in err

    def test_empty_string(self):
        ok, err = validate_image_format("")
        assert not ok

    def test_pdf_invalid(self):
        ok, err = validate_image_format("pdf")
        assert not ok


class TestValidateDpi:
    def test_valid_150(self):
        ok, err = validate_dpi(150)
        assert ok
        assert err == ""

    def test_valid_lower_bound(self):
        ok, err = validate_dpi(72)
        assert ok

    def test_valid_upper_bound(self):
        ok, err = validate_dpi(600)
        assert ok

    def test_too_low(self):
        ok, err = validate_dpi(71)
        assert not ok
        assert "72" in err

    def test_too_high(self):
        ok, err = validate_dpi(601)
        assert not ok
        assert "600" in err

    def test_not_integer(self):
        ok, err = validate_dpi(150.5)
        assert not ok


class TestValidatePage:
    def test_page_1(self):
        ok, err = validate_page(1)
        assert ok
        assert err == ""

    def test_page_10(self):
        ok, err = validate_page(10)
        assert ok

    def test_page_zero(self):
        ok, err = validate_page(0)
        assert not ok

    def test_page_negative(self):
        ok, err = validate_page(-1)
        assert not ok

    def test_not_integer(self):
        ok, err = validate_page(1.5)
        assert not ok


class TestGeneratePaths:
    def test_returns_provided_pdf_path_inside_root(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
        result = generate_pdf_path(str(tmp_path / "score.pdf"))
        assert result == str((tmp_path / "score.pdf").resolve())

    def test_rejects_provided_pdf_path_outside_root(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
        with pytest.raises(ValueError):
            generate_pdf_path("/custom/path/score.pdf")

    def test_generates_pdf_path_when_none(self):
        result = generate_pdf_path(None)
        assert result.endswith(".pdf")
        assert RENDER_OUTPUT_DIR in result

    def test_returns_provided_image_path_inside_root(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
        result = generate_image_path(str(tmp_path / "score.png"), "png")
        assert result == str((tmp_path / "score.png").resolve())

    def test_generates_png_path_when_none(self):
        result = generate_image_path(None, "png")
        assert result.endswith(".png")
        assert RENDER_OUTPUT_DIR in result

    def test_generates_svg_path_when_none(self):
        result = generate_image_path(None, "svg")
        assert result.endswith(".svg")


class TestConfineOutputPath:
    def _confine(self, path, tmp_path, monkeypatch, suffixes=(".pdf",)):
        from render_mcp.utils import confine_output_path

        monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
        return confine_output_path(path, suffixes)

    def test_relative_path_lands_in_root(self, tmp_path, monkeypatch):
        out = self._confine("a.pdf", tmp_path, monkeypatch)
        assert out == str((tmp_path / "a.pdf").resolve())

    def test_rejects_parent_traversal(self, tmp_path, monkeypatch):
        with pytest.raises(ValueError, match="inside"):
            self._confine("../escape.pdf", tmp_path, monkeypatch)

    def test_rejects_absolute_path_outside_root(self, tmp_path, monkeypatch):
        with pytest.raises(ValueError, match="inside"):
            self._confine("/etc/cron.d/x.pdf", tmp_path, monkeypatch)

    def test_rejects_symlink_escape(self, tmp_path, monkeypatch):
        outside = tmp_path / "outside"
        outside.mkdir()
        root = tmp_path / "root"
        root.mkdir()
        (root / "link").symlink_to(outside)
        with pytest.raises(ValueError, match="inside"):
            self._confine("link/x.pdf", root, monkeypatch)

    def test_rejects_wrong_suffix(self, tmp_path, monkeypatch):
        with pytest.raises(ValueError, match="end with"):
            self._confine("notes.sh", tmp_path, monkeypatch)

    def test_rejects_existing_file(self, tmp_path, monkeypatch):
        (tmp_path / "a.pdf").write_text("x")
        with pytest.raises(ValueError, match="exists"):
            self._confine("a.pdf", tmp_path, monkeypatch)
