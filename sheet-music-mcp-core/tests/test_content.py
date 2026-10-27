"""Result content blocks (docs/conventions.md, Result Content)."""

import base64
import json

from mcp.types import AudioContent

from sheet_music_mcp_core.content import (
    AUDIO_MAX_BYTES,
    audio_block,
    error_content,
    file_link,
    png_block,
    processing_error_content,
)
from sheet_music_mcp_core.errors import ProcessingError

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
WAV_BYTES = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 64


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


class TestProcessingErrorContent:
    def test_carries_message_code_hint_and_choices(self):
        error = ProcessingError("Part 'X' not found.", "INVALID_PARAMETER", hint="h", choices=["Alto (P2)"])

        [block] = processing_error_content(error)

        assert json.loads(block.text) == {
            "error": "Part 'X' not found.",
            "error_code": "INVALID_PARAMETER",
            "hint": "h",
            "choices": ["Alto (P2)"],
        }

    def test_plain_error_is_byte_identical_to_error_content(self):
        error = ProcessingError("Rendering failed", "PROCESSING_FAILED")

        assert processing_error_content(error)[0].text == error_content("Rendering failed", "PROCESSING_FAILED")[0].text


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

    def test_oversize_file_is_not_read_into_memory(self, tmp_path, monkeypatch):
        path = tmp_path / "big.png"
        path.write_bytes(PNG_BYTES)

        def _fail(self):
            raise AssertionError("an oversize PNG must be rejected from its size, not read")

        monkeypatch.setattr("pathlib.Path.read_bytes", _fail)

        assert png_block(str(path), max_bytes=len(PNG_BYTES) - 1) is None

    def test_default_limit_is_one_megabyte(self, tmp_path):
        path = tmp_path / "big.png"
        path.write_bytes(b"\x00" * (1024 * 1024 + 1))

        assert png_block(str(path)) is None


class TestAudioBlock:
    def test_wav_becomes_base64_audio(self, tmp_path):
        path = tmp_path / "clip.wav"
        path.write_bytes(WAV_BYTES)

        block = audio_block(str(path))

        assert isinstance(block, AudioContent)
        assert block.type == "audio"
        assert block.mime_type == "audio/wav"
        assert base64.b64decode(block.data) == WAV_BYTES

    def test_default_limit_is_200_kilobytes(self):
        assert AUDIO_MAX_BYTES == 200 * 1024

    def test_exactly_at_the_default_limit_is_included(self, tmp_path):
        path = tmp_path / "clip.wav"
        path.write_bytes(b"\x00" * AUDIO_MAX_BYTES)

        assert audio_block(str(path)) is not None

    def test_one_byte_above_the_default_limit_returns_none(self, tmp_path):
        path = tmp_path / "clip.wav"
        path.write_bytes(b"\x00" * (AUDIO_MAX_BYTES + 1))

        assert audio_block(str(path)) is None

    def test_custom_limit(self, tmp_path):
        path = tmp_path / "clip.wav"
        path.write_bytes(WAV_BYTES)

        assert audio_block(path, max_bytes=len(WAV_BYTES)) is not None
        assert audio_block(path, max_bytes=len(WAV_BYTES) - 1) is None

    def test_oversize_file_is_not_read_into_memory(self, tmp_path, monkeypatch):
        path = tmp_path / "big.wav"
        path.write_bytes(WAV_BYTES)

        def _fail(self):
            raise AssertionError("an oversize WAV must be rejected from its size, not read")

        monkeypatch.setattr("pathlib.Path.read_bytes", _fail)

        assert audio_block(str(path), max_bytes=len(WAV_BYTES) - 1) is None
