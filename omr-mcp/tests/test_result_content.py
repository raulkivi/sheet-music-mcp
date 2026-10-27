"""Result content blocks appended after the JSON text (docs/conventions.md, Result Content).

recognize_image_to_file is replaced by fakes, so no OMR engine runs.
"""

import asyncio
import json

import pytest

import omr_mcp.server as srv

MUSICXML_MIME = "application/vnd.recordare.musicxml+xml"


@pytest.fixture(autouse=True)
def output_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
    return tmp_path


def _success(output_path, write=True):
    def fake(input_path, output_path_arg, engine="oemer"):
        if write:
            output_path.write_text("<score-partwise/>", encoding="utf-8")
        return {
            "output_path": str(output_path),
            "metadata": {
                "source": input_path,
                "staves_detected": 4,
                "measures": 8,
                "processing_time_ms": 12,
                "engine": engine,
            },
        }

    return fake


class TestRecognizeSheetToFile:
    def test_json_block_unchanged(self, monkeypatch, output_root):
        out = output_root / "score.musicxml"
        fake = _success(out)
        monkeypatch.setattr(srv, "recognize_image_to_file", fake)
        input_path = str(output_root / "page.png")

        result = asyncio.run(srv.call_tool("recognize_sheet_to_file", {"input_path": input_path}))

        expected = fake(input_path, None, "oemer")
        assert result[0].type == "text"
        assert result[0].text == json.dumps(expected, indent=2)

    def test_appends_musicxml_link(self, monkeypatch, output_root):
        out = output_root / "score.musicxml"
        monkeypatch.setattr(srv, "recognize_image_to_file", _success(out))

        result = asyncio.run(srv.call_tool(
            "recognize_sheet_to_file", {"input_path": str(output_root / "page.png")}
        ))

        assert [block.type for block in result] == ["text", "resource_link"]
        link = result[1]
        assert link.mime_type == MUSICXML_MIME
        assert link.uri.startswith("file://")
        assert link.uri == out.resolve().as_uri()
        assert link.name == "score.musicxml"

    def test_missing_output_file_gets_no_link(self, monkeypatch, output_root):
        out = output_root / "never_written.musicxml"
        monkeypatch.setattr(srv, "recognize_image_to_file", _success(out, write=False))

        result = asyncio.run(srv.call_tool(
            "recognize_sheet_to_file", {"input_path": str(output_root / "page.png")}
        ))

        assert len(result) == 1


class TestErrorsHaveNoExtraBlocks:
    def test_returned_error_dict(self, monkeypatch, output_root):
        # The engine returns (not raises) error dicts, e.g. for a missing input file.
        existing = output_root / "page.musicxml"
        existing.write_text("<score-partwise/>", encoding="utf-8")

        def fake(input_path, output_path, engine="oemer"):
            return {"error": f"File not found: {input_path}", "error_code": "FILE_NOT_FOUND"}

        monkeypatch.setattr(srv, "recognize_image_to_file", fake)

        result = asyncio.run(srv.call_tool(
            "recognize_sheet_to_file",
            {"input_path": str(output_root / "page.png"), "output_path": str(existing)},
        ))

        assert len(result) == 1
        assert json.loads(result[0].text)["error_code"] == "FILE_NOT_FOUND"

    def test_real_engine_missing_input(self, output_root):
        result = asyncio.run(srv.call_tool(
            "recognize_sheet_to_file", {"input_path": str(output_root / "absent.png")}
        ))

        assert len(result) == 1
        assert json.loads(result[0].text)["error_code"] == "FILE_NOT_FOUND"

    def test_raised_exception(self, monkeypatch, output_root):
        def fake(input_path, output_path, engine="oemer"):
            raise RuntimeError("boom")

        monkeypatch.setattr(srv, "recognize_image_to_file", fake)

        result = asyncio.run(srv.call_tool(
            "recognize_sheet_to_file", {"input_path": str(output_root / "page.png")}
        ))

        assert len(result) == 1
        assert json.loads(result[0].text)["error_code"] == "PROCESSING_FAILED"
