"""``get_pdf`` and ``read_pdf_chunk``: the app-only tools behind the Score Viewer's PDF download.

``get_pdf`` renders the viewer's inline score to a PDF in the output root and answers with an
opaque ``pdf_id``; ``read_pdf_chunk`` reads it back in bounded base64 chunks (core ``artifacts``).
Neither takes or returns a path (proposal §7), and a client without MCP Apps does not see them.
"""

import asyncio
import base64
from pathlib import Path

import pytest
from mcp import Client
from mcp.client import advertise
from sheet_music_mcp_core.annotations import READ_ONLY, WRITES_FILE
from sheet_music_mcp_core.artifacts import MAX_CHUNK_BYTES, InMemoryArtifactStore
from sheet_music_mcp_core.ui import UI_EXTENSION, UI_MIME

import render_mcp.server as server
from render_mcp.server import app, call_tool_result, list_tools

from .test_server import VALID_MUSICXML

UI_CLIENT = {"extensions": [advertise(UI_EXTENSION, {"mimeTypes": [UI_MIME]})]}
FAKE_PDF = b"%PDF-1.4\n" + b"0" * 3000 + b"\n%%EOF\n"


@pytest.fixture(autouse=True)
def output_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def fake_pdf(monkeypatch):
    """The engine writes a small PDF, so the tests need no rendering backend."""
    calls = []

    def fake(musicxml, output_path, **kwargs):
        calls.append(musicxml)
        Path(output_path).write_bytes(FAKE_PDF)
        return output_path, 3

    monkeypatch.setattr(server, "render_to_pdf", fake)
    return calls


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    from sheet_music_mcp_core.artifacts import FileArtifactStore

    monkeypatch.setattr(server, "pdf_store", FileArtifactStore())


def _with_client(call, **client_kwargs):
    async def _go():
        async with Client(app, **client_kwargs) as client:
            return await call(client)

    return asyncio.run(_go())


async def _tool(name):
    return next(t for t in await list_tools() if t.name == name)


async def _pdf_id(fake_pdf) -> str:
    result = await call_tool_result("get_pdf", {"musicxml": VALID_MUSICXML})
    return result.structured_content["pdf_id"]


class TestDefinition:
    async def test_get_pdf_is_app_only_and_linked_to_the_viewer_when_packaged(self, packaged_ui):
        assert (await _tool("get_pdf")).meta == {
            "ui": {"resourceUri": "ui://render/score-viewer", "visibility": ["app"]}
        }

    async def test_read_pdf_chunk_is_app_only_without_a_ui_build(self):
        assert (await _tool("read_pdf_chunk")).meta == {"ui": {"visibility": ["app"]}}

    async def test_titles_and_annotation_presets(self):
        pdf, chunk = await _tool("get_pdf"), await _tool("read_pdf_chunk")

        assert (pdf.title, chunk.title) == ("Render score PDF for download", "Read PDF chunk")
        assert pdf.annotations.model_dump(exclude_none=True) == dict(WRITES_FILE)
        assert chunk.annotations.model_dump(exclude_none=True) == dict(READ_ONLY)

    async def test_get_pdf_takes_inline_musicxml_and_no_path(self):
        schema = (await _tool("get_pdf")).input_schema

        assert set(schema["properties"]) == {"musicxml"}
        assert schema["required"] == ["musicxml"]
        assert schema["additionalProperties"] is False

    async def test_read_pdf_chunk_takes_an_id_and_a_bounded_range_and_no_path(self):
        schema = (await _tool("read_pdf_chunk")).input_schema

        assert set(schema["properties"]) == {"pdf_id", "offset", "length"}
        assert set(schema["required"]) == {"pdf_id", "offset", "length"}
        assert schema["properties"]["length"]["maximum"] == MAX_CHUNK_BYTES
        assert schema["additionalProperties"] is False

    async def test_both_declare_their_output(self):
        pdf, chunk = await _tool("get_pdf"), await _tool("read_pdf_chunk")

        assert set(pdf.output_schema["required"]) == {"pdf_id", "byte_length", "page_count", "backend"}
        assert set(chunk.output_schema["required"]) == {
            "artifact_id",
            "offset",
            "length",
            "byte_length",
            "eof",
            "data_b64",
        }


class TestVisibility:
    def test_hidden_from_clients_without_ui(self):
        names = {t.name for t in _with_client(lambda c: c.list_tools()).tools}

        assert not {"get_pdf", "read_pdf_chunk"} & names

    def test_listed_for_ui_clients(self):
        names = {t.name for t in _with_client(lambda c: c.list_tools(), **UI_CLIENT).tools}

        assert {"get_pdf", "read_pdf_chunk"} <= names


class TestGetPdf:
    async def test_returns_an_opaque_id_and_the_size(self, fake_pdf):
        result = await call_tool_result("get_pdf", {"musicxml": VALID_MUSICXML})

        assert not result.is_error
        data = result.structured_content
        assert data["byte_length"] == len(FAKE_PDF)
        assert data["page_count"] == 3
        assert isinstance(data["pdf_id"], str) and data["pdf_id"]
        assert fake_pdf == [VALID_MUSICXML]

    async def test_never_puts_a_path_in_the_result(self, fake_pdf, output_root):
        result = await call_tool_result("get_pdf", {"musicxml": VALID_MUSICXML})

        assert str(output_root) not in repr(result)

    async def test_writes_the_pdf_inside_the_output_root(self, fake_pdf, output_root):
        await call_tool_result("get_pdf", {"musicxml": VALID_MUSICXML})

        assert [p.read_bytes() for p in output_root.rglob("*.pdf")] == [FAKE_PDF]

    async def test_each_call_gets_its_own_id(self, fake_pdf):
        assert await _pdf_id(fake_pdf) != await _pdf_id(fake_pdf)

    async def test_invalid_musicxml_is_invalid_input(self, fake_pdf):
        result = await call_tool_result("get_pdf", {"musicxml": "<nope/>"})

        assert result.is_error
        assert "INVALID_INPUT" in result.content[0].text
        assert fake_pdf == []

    async def test_a_score_over_the_size_cap_is_invalid_parameter(self, fake_pdf, monkeypatch):
        monkeypatch.setenv("SHEET_MUSIC_MAX_SCORE_BYTES", "100")

        result = await call_tool_result("get_pdf", {"musicxml": VALID_MUSICXML})

        assert result.is_error
        assert "INVALID_PARAMETER" in result.content[0].text

    async def test_a_failing_backend_is_processing_failed(self, monkeypatch):
        def boom(musicxml, output_path, **kwargs):
            raise RuntimeError("cairo exploded")

        monkeypatch.setattr(server, "render_to_pdf", boom)

        result = await call_tool_result("get_pdf", {"musicxml": VALID_MUSICXML})

        assert result.is_error
        assert "PROCESSING_FAILED" in result.content[0].text


class TestReadPdfChunk:
    async def test_the_first_chunk_starts_with_the_pdf_magic(self, fake_pdf):
        pdf_id = await _pdf_id(fake_pdf)

        result = await call_tool_result("read_pdf_chunk", {"pdf_id": pdf_id, "offset": 0, "length": 1024})

        assert not result.is_error
        data = result.structured_content
        assert base64.b64decode(data["data_b64"]).startswith(b"%PDF")
        assert (data["offset"], data["length"], data["eof"]) == (0, 1024, False)
        assert data["byte_length"] == len(FAKE_PDF)

    async def test_chunks_join_to_the_whole_file(self, fake_pdf):
        pdf_id = await _pdf_id(fake_pdf)
        joined, offset = b"", 0

        while True:
            result = await call_tool_result("read_pdf_chunk", {"pdf_id": pdf_id, "offset": offset, "length": 1000})
            data = result.structured_content
            joined += base64.b64decode(data["data_b64"])
            offset += data["length"]
            if data["eof"]:
                break

        assert joined == FAKE_PDF

    async def test_an_unknown_id_is_invalid_parameter(self):
        result = await call_tool_result("read_pdf_chunk", {"pdf_id": "nope", "offset": 0, "length": 10})

        assert result.is_error
        assert "INVALID_PARAMETER" in result.content[0].text

    async def test_a_path_is_just_an_unknown_id(self, output_root):
        result = await call_tool_result(
            "read_pdf_chunk", {"pdf_id": str(output_root / "x.pdf"), "offset": 0, "length": 10}
        )

        assert result.is_error
        assert "INVALID_PARAMETER" in result.content[0].text

    def test_a_chunk_over_the_limit_is_refused_by_the_schema(self, fake_pdf):
        result = _with_client(
            lambda c: c.call_tool(
                "read_pdf_chunk", {"pdf_id": "x", "offset": 0, "length": MAX_CHUNK_BYTES + 1}
            ),
            **UI_CLIENT,
        )

        assert result.is_error
        assert "INVALID" in result.content[0].text.upper()

    async def test_an_id_from_another_store_is_unknown(self, fake_pdf, monkeypatch):
        pdf_id = await _pdf_id(fake_pdf)
        monkeypatch.setattr(server, "pdf_store", InMemoryArtifactStore())

        result = await call_tool_result("read_pdf_chunk", {"pdf_id": pdf_id, "offset": 0, "length": 10})

        assert result.is_error


@pytest.mark.integration
async def test_the_real_backend_produces_a_pdf_that_reads_back(output_root):
    result = await call_tool_result("get_pdf", {"musicxml": VALID_MUSICXML})
    assert not result.is_error, result.content
    pdf_id = result.structured_content["pdf_id"]

    chunk = await call_tool_result("read_pdf_chunk", {"pdf_id": pdf_id, "offset": 0, "length": 64})

    assert base64.b64decode(chunk.structured_content["data_b64"]).startswith(b"%PDF")
    assert chunk.structured_content["byte_length"] == result.structured_content["byte_length"]
