"""Tests for OMR MCP utils module."""

import base64
import tempfile
from pathlib import Path
import pytest

from omr_mcp.utils import (
    validate_image_path,
    decode_base64_image,
    format_file_size,
    get_image_info,
    SUPPORTED_IMAGE_FORMATS,
)


class TestValidateImagePath:
    """Tests for validate_image_path function."""

    def test_nonexistent_file(self):
        is_valid, error = validate_image_path("/nonexistent/path/image.png")
        assert is_valid is False
        assert "not found" in error.lower()

    def test_unsupported_format(self, tmp_path):
        # Create a file with unsupported extension
        test_file = tmp_path / "test.bmp"
        test_file.write_bytes(b"fake content")
        
        is_valid, error = validate_image_path(str(test_file))
        assert is_valid is False
        assert "Unsupported format" in error

    def test_file_too_large(self, tmp_path, monkeypatch):
        # Mock the MAX_IMAGE_SIZE to a small value for testing
        import omr_mcp.utils
        monkeypatch.setattr(omr_mcp.utils, "MAX_IMAGE_SIZE", 10)
        
        test_file = tmp_path / "test.png"
        test_file.write_bytes(b"x" * 100)  # Larger than mocked limit
        
        is_valid, error = validate_image_path(str(test_file))
        assert is_valid is False
        assert "too large" in error.lower()


class TestDecodeBase64Image:
    """Tests for decode_base64_image function."""

    def test_decode_valid_base64(self):
        # Create a minimal valid PNG (1x1 transparent pixel)
        png_data = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
            b'\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01'
            b'\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        base64_data = base64.b64encode(png_data).decode('utf-8')
        
        success, path = decode_base64_image(base64_data)
        assert success is True
        assert Path(path).exists()
        
        # Cleanup
        Path(path).unlink()

    def test_decode_with_data_url_prefix(self):
        # Create a minimal valid PNG
        png_data = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
            b'\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01'
            b'\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        base64_data = f"data:image/png;base64,{base64.b64encode(png_data).decode('utf-8')}"
        
        success, path = decode_base64_image(base64_data)
        assert success is True
        assert Path(path).exists()
        
        # Cleanup
        Path(path).unlink()

    def test_decode_invalid_base64(self):
        success, error = decode_base64_image("not-valid-base64!!!")
        assert success is False
        assert "Failed to decode" in error


class TestFormatFileSize:
    """Tests for format_file_size function."""

    def test_bytes(self):
        assert format_file_size(500) == "500.0 B"

    def test_kilobytes(self):
        assert format_file_size(2048) == "2.0 KB"

    def test_megabytes(self):
        assert format_file_size(5 * 1024 * 1024) == "5.0 MB"


class TestSupportedFormats:
    """Tests for supported format constants."""

    def test_supported_formats_include_common_types(self):
        assert ".png" in SUPPORTED_IMAGE_FORMATS
        assert ".jpg" in SUPPORTED_IMAGE_FORMATS
        assert ".jpeg" in SUPPORTED_IMAGE_FORMATS


class TestConfineOutputPath:
    def _confine(self, path, tmp_path, monkeypatch, suffixes=(".musicxml",)):
        from omr_mcp.utils import confine_output_path

        monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
        return confine_output_path(path, suffixes)

    def test_relative_path_lands_in_root(self, tmp_path, monkeypatch):
        out = self._confine("a.musicxml", tmp_path, monkeypatch)
        assert out == str((tmp_path / "a.musicxml").resolve())

    def test_rejects_parent_traversal(self, tmp_path, monkeypatch):
        with pytest.raises(ValueError, match="inside"):
            self._confine("../escape.musicxml", tmp_path, monkeypatch)

    def test_rejects_absolute_path_outside_root(self, tmp_path, monkeypatch):
        with pytest.raises(ValueError, match="inside"):
            self._confine("/etc/cron.d/x.musicxml", tmp_path, monkeypatch)

    def test_rejects_symlink_escape(self, tmp_path, monkeypatch):
        outside = tmp_path / "outside"
        outside.mkdir()
        root = tmp_path / "root"
        root.mkdir()
        (root / "link").symlink_to(outside)
        with pytest.raises(ValueError, match="inside"):
            self._confine("link/x.musicxml", root, monkeypatch)

    def test_rejects_wrong_suffix(self, tmp_path, monkeypatch):
        with pytest.raises(ValueError, match="end with"):
            self._confine("notes.sh", tmp_path, monkeypatch)

    def test_rejects_existing_file(self, tmp_path, monkeypatch):
        (tmp_path / "a.musicxml").write_text("x")
        with pytest.raises(ValueError, match="exists"):
            self._confine("a.musicxml", tmp_path, monkeypatch)
