"""Result content blocks (docs/conventions.md, Result Content)."""

import base64
import json

from sheet_music_mcp_core.content import error_content, file_link, png_block

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class TestErrorContent:
    def test_same_text_as_the_servers_produced_before(self):
        # Servers used json.dumps({"error": ..., "error_code": ...}) with default separators.
        [block] = error_content("Bad XML", "INVALID_INPUT")

        assert block.type == "text"
        assert block.text == '{"error": "Bad XML", "error_code": "INVALID_INPUT"}'

    def test_includes_hint_and_choices(self):
        [block] = error_content("x", "INVALID_PARAMETER", hint="h", choices=["a", "b"])

        assert json.loads(block.text) == {
            "error": "x",
            "error_code": "INVALID_PARAMETER",
            "hint": "h",
            "choices": ["a", "b"],
        }


class TestFileLink:
    def test_links_to_the_resolved_file(self, tmp_path):
        path = tmp_path / "score.pdf"
        path.write_bytes(b"%PDF-1.7")

        link = file_link(str(path), "application/pdf")

        assert link.type == "resource_link"
        assert str(link.uri) == path.resolve().as_uri()
        assert link.name == "score.pdf"
        assert link.mime_type == "application/pdf"
        assert link.size == 8

    def test_relative_path_is_resolved(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "a.wav").write_bytes(b"RIFF")

        link = file_link("a.wav", "audio/wav")

        assert str(link.uri) == (tmp_path / "a.wav").resolve().as_uri()


class TestPngBlock:
    def test_png_becomes_base64_image(self, tmp_path):
        path = tmp_path / "page.png"
        path.write_bytes(PNG_BYTES)

        block = png_block(str(path))

        assert block.type == "image"
        assert block.mime_type == "image/png"
        assert base64.b64decode(block.data) == PNG_BYTES

    def test_too_large_returns_none(self, tmp_path):
        path = tmp_path / "page.png"
        path.write_bytes(PNG_BYTES)

        assert png_block(str(path), max_bytes=len(PNG_BYTES) - 1) is None

    def test_exactly_at_limit_is_included(self, tmp_path):
        path = tmp_path / "page.png"
        path.write_bytes(PNG_BYTES)

        assert png_block(str(path), max_bytes=len(PNG_BYTES)) is not None

    def test_default_limit_is_one_megabyte(self, tmp_path):
        path = tmp_path / "big.png"
        path.write_bytes(b"\x00" * (1024 * 1024 + 1))

        assert png_block(str(path)) is None
