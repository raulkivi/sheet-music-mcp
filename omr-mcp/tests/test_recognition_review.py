"""Recognition Review linking: the ``ui://omr/recognition-review`` resource, tool ``_meta``,
``structuredContent`` and the app-only ``get_source_preview`` (proposal 5.5, AC-O1 and AC-O2)."""

import asyncio
import base64
import io
import json

from types import SimpleNamespace

import jsonschema
import pytest
from mcp import Client
from mcp.client import advertise
from PIL import Image
from sheet_music_mcp_core.ui import UI_EXTENSION, UI_MIME, is_app_only

import omr_mcp.server as srv
from omr_mcp.previews import MAX_PREVIEW_SIDE
from omr_mcp.server import app, list_tools
from omr_mcp.server import call_tool_result as _call_tool_result

from .conftest import REVIEW_HTML

UI_CLIENT = {"extensions": [advertise(UI_EXTENSION, {"mimeTypes": [UI_MIME]})]}


def _ctx(*, ui: bool):
    """What the server sees as ctx when a client does or does not advertise MCP Apps."""
    extensions = {UI_EXTENSION: {"mimeTypes": [UI_MIME]}} if ui else {}
    capabilities = SimpleNamespace(extensions=extensions)
    return SimpleNamespace(meta=None, session=SimpleNamespace(client_capabilities=capabilities))


async def call_tool_result(name, arguments, ctx=_ctx(ui=True)):
    """The server's result for a client that can show the app, unless a test says otherwise."""
    return await _call_tool_result(name, arguments, ctx)


REVIEW_URI = "ui://omr/recognition-review"
LINKED = ("recognize_sheet", "recognize_sheets")
XML = "<score-partwise><part id='P1'/></score-partwise>"


@pytest.fixture(autouse=True)
def output_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path / "out"))
    return tmp_path / "out"


def _tools():
    return {tool.name: tool for tool in asyncio.run(list_tools())}


def _page_image(tmp_path, name="page.png", size=(2400, 1800), staves=0):
    """A real image; ``staves`` > 0 draws that many five-line staves."""
    from PIL import ImageDraw

    path = tmp_path / name
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    for s in range(staves):
        for line in range(5):
            y = 100 + s * 300 + line * 12
            draw.rectangle([50, y, size[0] - 50, y], fill="black")
    image.save(path)
    return path


def _engine_result(staves=1, measures=8, engine="oemer"):
    return {"musicxml": XML, "metadata": {"source": "x.png", "staves_detected": staves, "measures": measures,
                                          "processing_time_ms": 12, "engine": engine}}


def _stub_single(monkeypatch, **kwargs):
    monkeypatch.setattr(srv, "recognize_image", lambda path, engine="oemer": _engine_result(engine=engine, **kwargs))


def _stub_pages(monkeypatch, pages):
    def fake(paths, engine="oemer"):
        return {"musicxml": XML,
                "metadata": {"page_count": len(paths), "staves_detected": 2, "measures": 13,
                             "processing_time_ms": 30, "engine": engine},
                "_pages": [{"index": i, "staves_detected": s, "measures": m} for i, (s, m) in enumerate(pages, 1)]}

    monkeypatch.setattr(srv, "recognize_images", fake)


class TestToolLinking:
    @pytest.mark.parametrize("name", LINKED)
    def test_recognition_tools_link_the_app_when_packaged(self, packaged_ui, name):
        assert _tools()[name].meta == {"ui": {"resourceUri": REVIEW_URI}}

    @pytest.mark.parametrize("name", LINKED)
    def test_no_link_without_a_ui_build(self, name):
        assert _tools()[name].meta is None

    def test_scripted_and_other_tools_stay_unlinked(self, packaged_ui):
        # health_check is excluded: it links to the Setup Doctor, not the review app.
        others = [
            t for n, t in _tools().items()
            if n not in (*LINKED, "health_check") and not is_app_only(t)
        ]

        assert {t.name for t in others} >= {"recognize_sheet_to_file", "list_capabilities"}
        assert all(t.meta is None for t in others)

    @pytest.mark.parametrize("name", LINKED)
    def test_linked_tools_declare_an_output_schema(self, name):
        schema = _tools()[name].output_schema

        assert schema["type"] == "object"
        # job_id is for the app, so a client that cannot show it gets a result without one.
        assert set(schema["required"]) == {"metadata", "pages"}
        assert "musicxml" not in schema["properties"]

    def test_get_source_preview_is_app_only_even_without_a_build(self):
        tool = _tools()["get_source_preview"]

        assert is_app_only(tool)
        assert "resourceUri" not in tool.meta["ui"]

    def test_get_source_preview_is_app_only_and_linked_when_packaged(self, packaged_ui):
        tool = _tools()["get_source_preview"]

        assert tool.meta == {"ui": {"resourceUri": REVIEW_URI, "visibility": ["app"]}}

    def test_get_recognized_score_is_app_only_and_takes_only_a_job_id(self, packaged_ui):
        tool = _tools()["get_recognized_score"]

        assert tool.meta == {"ui": {"resourceUri": REVIEW_URI, "visibility": ["app"]}}
        assert tool.input_schema["additionalProperties"] is False
        assert tool.input_schema["required"] == ["job_id"]
        assert set(tool.input_schema["properties"]) == {"job_id"}
        assert set(tool.output_schema["required"]) == {"job_id", "musicxml"}

    def test_get_recognized_score_is_app_only_even_without_a_build(self):
        assert is_app_only(_tools()["get_recognized_score"])

    def test_get_source_preview_takes_no_path_and_no_extras(self):
        schema = _tools()["get_source_preview"].input_schema

        assert schema["additionalProperties"] is False
        assert set(schema["properties"]) == {"job_id", "page", "offset", "length"}
        assert schema["required"] == ["job_id"]


class TestResources:
    def _with_client(self, call):
        async def go():
            async with Client(app) as client:
                return await call(client)

        return asyncio.run(go())

    def test_the_app_is_listed_and_read_when_packaged(self, packaged_ui):
        async def call(client):
            listed = await client.list_resources()
            read = await client.read_resource(REVIEW_URI)
            return listed, read

        listed, read = self._with_client(call)

        assert [r.uri for r in listed.resources] == [REVIEW_URI, "ui://omr/setup-doctor"]
        assert listed.resources[0].mime_type == UI_MIME
        assert read.contents[0].text == REVIEW_HTML

    def test_nothing_is_listed_without_a_ui_build(self):
        listed = self._with_client(lambda client: client.list_resources())

        assert listed.resources == []

    def test_the_server_never_accepts_a_path_for_the_preview(self):
        async def call(client):
            return await client.call_tool("get_source_preview", {"job_id": "x", "path": "/etc/passwd"})

        result = self._with_client(call)

        assert result.is_error
        assert json.loads(result.content[0].text)["error_code"] == "INVALID_PARAMETER"


class TestRecognizeSheetStructure:
    def test_structured_content_has_the_contract_shape(self, tmp_path, monkeypatch):
        _stub_single(monkeypatch)

        result = asyncio.run(call_tool_result("recognize_sheet", {"image": str(_page_image(tmp_path))}))
        sc = result.structured_content

        assert set(sc) == {"job_id", "metadata", "pages"}
        assert sc["metadata"]["engine"] == "oemer"
        assert sc["metadata"]["staves_detected"] == 1
        assert sc["pages"] == [{"index": 1, "staves_detected": 1, "measures": 8, "has_preview": True}]
        jsonschema.validate(sc, _tools()["recognize_sheet"].output_schema)

    def test_content_does_not_leak_the_job_id_or_internals(self, tmp_path, monkeypatch):
        _stub_single(monkeypatch)

        result = asyncio.run(call_tool_result("recognize_sheet", {"image": str(_page_image(tmp_path))}))

        assert result.structured_content["job_id"] not in result.content[0].text
        assert "staff_systems_estimate" not in result.content[0].text

    @pytest.mark.parametrize("mode", ["inline", "path"])
    def test_structured_content_never_carries_the_score(self, tmp_path, monkeypatch, mode):
        _stub_single(monkeypatch)

        result = asyncio.run(
            call_tool_result("recognize_sheet", {"image": str(_page_image(tmp_path)), "return": mode})
        )

        assert "musicxml" not in result.structured_content
        assert XML not in json.dumps(result.structured_content)

    def test_staff_systems_estimate_is_in_the_metadata(self, tmp_path, monkeypatch):
        _stub_single(monkeypatch, staves=1)

        result = asyncio.run(
            call_tool_result("recognize_sheet", {"image": str(_page_image(tmp_path, staves=4))})
        )

        assert result.structured_content["metadata"]["staff_systems_estimate"] == 4

    def test_an_unreadable_image_still_recognises_without_a_preview(self, tmp_path, monkeypatch):
        _stub_single(monkeypatch)
        broken = tmp_path / "broken.png"
        broken.write_bytes(b"x")

        result = asyncio.run(call_tool_result("recognize_sheet", {"image": str(broken)}))
        sc = result.structured_content

        assert "staff_systems_estimate" not in sc["metadata"]
        assert sc["pages"][0]["has_preview"] is False

    def test_a_base64_image_gets_a_preview_too(self, tmp_path, monkeypatch):
        _stub_single(monkeypatch)
        buffer = io.BytesIO()
        Image.new("RGB", (64, 64), "white").save(buffer, "PNG")
        data = base64.b64encode(buffer.getvalue()).decode()

        result = asyncio.run(call_tool_result("recognize_sheet", {"image": data, "format": "base64"}))

        assert result.structured_content["pages"][0]["has_preview"] is True

    def test_each_run_gets_its_own_job(self, tmp_path, monkeypatch):
        _stub_single(monkeypatch)
        image = str(_page_image(tmp_path))

        first = asyncio.run(call_tool_result("recognize_sheet", {"image": image}))
        second = asyncio.run(call_tool_result("recognize_sheet", {"image": image}))

        assert first.structured_content["job_id"] != second.structured_content["job_id"]


class TestRecognizeSheetsStructure:
    def test_pages_come_from_the_engine_and_the_text_stays_clean(self, tmp_path, monkeypatch):
        _stub_pages(monkeypatch, [(2, 8), (2, 5)])
        images = [str(_page_image(tmp_path, f"p{i}.png", (800, 1400), staves=i)) for i in (2, 4)]

        result = asyncio.run(call_tool_result("recognize_sheets", {"images": images}))
        sc = result.structured_content

        assert [p["index"] for p in sc["pages"]] == [1, 2]
        assert [p["measures"] for p in sc["pages"]] == [8, 5]
        assert all(p["has_preview"] for p in sc["pages"])
        assert sc["metadata"]["page_count"] == 2
        assert sc["metadata"]["staff_systems_estimate"] == 4  # the busiest page
        assert "_pages" not in result.content[0].text
        assert "_pages" not in sc
        jsonschema.validate(sc, _tools()["recognize_sheets"].output_schema)

    def test_an_engine_without_page_detail_still_lists_the_pages(self, tmp_path, monkeypatch):
        monkeypatch.setattr(srv, "recognize_images", lambda paths, engine="oemer": {
            "musicxml": XML, "metadata": {"page_count": 2, "staves_detected": 2, "measures": 13,
                                          "processing_time_ms": 1, "engine": engine}})
        images = [str(_page_image(tmp_path, f"p{i}.png", (100, 100))) for i in range(2)]

        result = asyncio.run(call_tool_result("recognize_sheets", {"images": images}))

        assert result.structured_content["pages"] == [
            {"index": 1, "staves_detected": None, "measures": None, "has_preview": True},
            {"index": 2, "staves_detected": None, "measures": None, "has_preview": True},
        ]
        jsonschema.validate(result.structured_content, _tools()["recognize_sheets"].output_schema)


def _preview(job_id, **extra):
    return asyncio.run(call_tool_result("get_source_preview", {"job_id": job_id, **extra}))


def _recognise(tmp_path, monkeypatch, size=(3200, 2400)):
    _stub_single(monkeypatch)
    result = asyncio.run(call_tool_result("recognize_sheet", {"image": str(_page_image(tmp_path, size=size))}))
    return result.structured_content["job_id"]


class TestGetSourcePreview:
    def test_returns_a_jpeg_within_the_size_limit(self, tmp_path, monkeypatch):
        job_id = _recognise(tmp_path, monkeypatch)

        result = _preview(job_id)
        sc = result.structured_content
        jpeg = Image.open(io.BytesIO(base64.b64decode(sc["data_b64"])))

        assert not result.is_error
        assert sc["eof"] is True
        assert jpeg.format == "JPEG"
        assert max(jpeg.size) <= MAX_PREVIEW_SIDE
        jsonschema.validate(sc, _tools()["get_source_preview"].output_schema)

    def test_reads_in_chunks(self, tmp_path, monkeypatch):
        job_id = _recognise(tmp_path, monkeypatch)
        first = _preview(job_id, offset=0, length=100).structured_content
        total = first["byte_length"]

        data, offset = b"", 0
        while True:
            chunk = _preview(job_id, offset=offset, length=1000).structured_content
            data += base64.b64decode(chunk["data_b64"])
            offset += chunk["length"]
            if chunk["eof"]:
                break

        assert first["length"] == 100 and first["eof"] is False
        assert len(data) == total
        assert Image.open(io.BytesIO(data)).format == "JPEG"

    def test_the_text_block_leaves_the_pixels_out_of_the_model_context(self, tmp_path, monkeypatch):
        job_id = _recognise(tmp_path, monkeypatch)

        result = _preview(job_id)

        assert result.structured_content["data_b64"][:40] not in result.content[0].text
        assert len(result.content[0].text) < 300

    def test_never_returns_a_path(self, tmp_path, monkeypatch):
        job_id = _recognise(tmp_path, monkeypatch)

        text = json.dumps(_preview(job_id).structured_content) + _preview(job_id).content[0].text

        assert str(tmp_path) not in text

    @pytest.mark.parametrize("job_id", ["nope", "", "../../etc/passwd", "/etc/passwd", "file:///etc/passwd"])
    def test_unknown_job_is_invalid_parameter_without_structured_content(self, job_id):
        result = _preview(job_id)

        assert result.is_error
        assert result.structured_content is None
        assert json.loads(result.content[0].text)["error_code"] == "INVALID_PARAMETER"

    def test_page_out_of_range_is_invalid_parameter(self, tmp_path, monkeypatch):
        job_id = _recognise(tmp_path, monkeypatch)

        result = _preview(job_id, page=2)

        assert result.is_error
        assert json.loads(result.content[0].text)["error_code"] == "INVALID_PARAMETER"

    def test_oversize_chunk_is_invalid_parameter(self, tmp_path, monkeypatch):
        job_id = _recognise(tmp_path, monkeypatch)

        result = _preview(job_id, length=10_000_000)

        assert result.is_error
        assert json.loads(result.content[0].text)["error_code"] == "INVALID_PARAMETER"

    def test_a_page_of_a_multi_page_job_is_served(self, tmp_path, monkeypatch):
        _stub_pages(monkeypatch, [(1, 4), (1, 4)])
        images = [str(_page_image(tmp_path, f"p{i}.png", (500, 300))) for i in range(2)]
        job_id = asyncio.run(call_tool_result("recognize_sheets", {"images": images})).structured_content["job_id"]

        first = _preview(job_id, page=1).structured_content
        second = _preview(job_id, page=2).structured_content

        assert first["artifact_id"] != second["artifact_id"]
        assert second["page"] == 2


class TestGetRecognizedScore:
    def _job(self, tmp_path, monkeypatch):
        _stub_single(monkeypatch)
        result = asyncio.run(call_tool_result("recognize_sheet", {"image": str(_page_image(tmp_path))}))
        return result.structured_content["job_id"]

    def test_returns_the_score_of_the_job(self, tmp_path, monkeypatch):
        job_id = self._job(tmp_path, monkeypatch)

        result = asyncio.run(call_tool_result("get_recognized_score", {"job_id": job_id}))

        assert not result.is_error
        assert result.structured_content == {"job_id": job_id, "musicxml": XML}
        jsonschema.validate(result.structured_content, _tools()["get_recognized_score"].output_schema)

    def test_the_text_block_is_one_short_line_without_the_xml(self, tmp_path, monkeypatch):
        job_id = self._job(tmp_path, monkeypatch)

        result = asyncio.run(call_tool_result("get_recognized_score", {"job_id": job_id}))

        assert len(result.content) == 1
        assert XML not in result.content[0].text
        assert "\n" not in result.content[0].text
        assert len(result.content[0].text) < 200

    @pytest.mark.parametrize("job_id", ["nope", "", "../../etc/passwd", "/etc/passwd"])
    def test_unknown_job_is_invalid_parameter(self, job_id):
        result = asyncio.run(call_tool_result("get_recognized_score", {"job_id": job_id}))

        assert result.is_error
        assert result.structured_content is None
        assert json.loads(result.content[0].text)["error_code"] == "INVALID_PARAMETER"

    def test_the_score_expires_with_the_job(self, tmp_path, monkeypatch):
        job_id = self._job(tmp_path, monkeypatch)
        monkeypatch.setattr(srv, "review_jobs", srv.ReviewJobs())  # a restart forgets every job

        result = asyncio.run(call_tool_result("get_recognized_score", {"job_id": job_id}))

        assert result.is_error

    def test_a_path_argument_is_rejected_through_the_protocol(self):
        async def call():
            async with Client(app, **UI_CLIENT) as client:
                return await client.call_tool("get_recognized_score", {"job_id": "x", "path": "/etc/passwd"})

        assert asyncio.run(call()).is_error


class TestClientsWithoutApps:
    """A client that cannot show the app gets no preview files and no job; content is unchanged."""

    def _both(self, tmp_path, monkeypatch, **extra):
        _stub_single(monkeypatch)
        args = {"image": str(_page_image(tmp_path, staves=4)), **extra}
        text_only = asyncio.run(_call_tool_result("recognize_sheet", args, _ctx(ui=False)))
        with_ui = asyncio.run(_call_tool_result("recognize_sheet", args, _ctx(ui=True)))
        return text_only, with_ui

    def test_content_is_byte_identical_for_both_kinds(self, tmp_path, monkeypatch):
        text_only, with_ui = self._both(tmp_path, monkeypatch)

        assert [b.model_dump() for b in text_only.content] == [b.model_dump() for b in with_ui.content]

    def test_no_job_no_estimate_no_preview_flag(self, tmp_path, monkeypatch):
        text_only, _ = self._both(tmp_path, monkeypatch)
        sc = text_only.structured_content

        assert set(sc) == {"metadata", "pages"}
        assert "staff_systems_estimate" not in sc["metadata"]
        assert sc["pages"] == [{"index": 1, "staves_detected": 1, "measures": 8}]
        jsonschema.validate(sc, _tools()["recognize_sheet"].output_schema)

    def test_nothing_is_written_or_remembered(self, tmp_path, monkeypatch, output_root):
        _stub_single(monkeypatch)

        asyncio.run(_call_tool_result("recognize_sheet", {"image": str(_page_image(tmp_path))}, _ctx(ui=False)))

        assert len(srv.review_jobs._jobs) == 0
        assert list(output_root.rglob("*.jpg")) == []

    def test_a_client_with_the_app_does_get_preview_files_and_a_job(self, tmp_path, monkeypatch, output_root):
        _stub_single(monkeypatch)

        asyncio.run(_call_tool_result("recognize_sheet", {"image": str(_page_image(tmp_path))}, _ctx(ui=True)))

        assert len(srv.review_jobs._jobs) == 1
        assert len(list(output_root.rglob("*.jpg"))) == 1

    def test_a_direct_call_without_a_context_counts_as_no_ui(self, tmp_path, monkeypatch):
        _stub_single(monkeypatch)

        result = asyncio.run(_call_tool_result("recognize_sheet", {"image": str(_page_image(tmp_path))}))

        assert "job_id" not in result.structured_content

    def test_through_the_protocol_both_kinds_are_served(self, tmp_path, monkeypatch):
        _stub_single(monkeypatch)
        args = {"image": str(_page_image(tmp_path))}

        async def call(**client):
            async with Client(app, **client) as c:
                return await c.call_tool("recognize_sheet", args)

        text_only, with_ui = asyncio.run(call()), asyncio.run(call(**UI_CLIENT))

        assert "job_id" not in text_only.structured_content
        assert "job_id" in with_ui.structured_content

    def test_sheets_follow_the_same_rule(self, tmp_path, monkeypatch):
        _stub_pages(monkeypatch, [(1, 4), (1, 4)])
        images = [str(_page_image(tmp_path, f"p{i}.png", (500, 300))) for i in range(2)]

        result = asyncio.run(_call_tool_result("recognize_sheets", {"images": images}, _ctx(ui=False)))

        assert set(result.structured_content) == {"metadata", "pages"}
        assert all("has_preview" not in p for p in result.structured_content["pages"])
        assert "_pages" not in json.dumps(result.structured_content)


class TestErrors:
    def test_engine_error_keeps_its_content_and_sets_is_error(self, tmp_path, monkeypatch):
        error = {"error": "File not found: x", "error_code": "FILE_NOT_FOUND"}
        monkeypatch.setattr(srv, "recognize_image", lambda path, engine="oemer": error)

        result = asyncio.run(call_tool_result("recognize_sheet", {"image": str(_page_image(tmp_path))}))

        assert result.is_error
        assert result.structured_content is None
        assert json.loads(result.content[0].text) == error

    def test_images_that_are_not_a_list_is_an_error_result(self):
        result = asyncio.run(call_tool_result("recognize_sheets", {"images": "x"}))

        assert result.is_error
        assert json.loads(result.content[0].text)["error_code"] == "INVALID_PARAMETER"

    def test_a_failed_recognition_stores_no_job(self, tmp_path, monkeypatch, artifact_store):
        monkeypatch.setattr(srv, "recognize_image", lambda path, engine="oemer": {
            "error": "boom", "error_code": "PROCESSING_FAILED"})

        asyncio.run(call_tool_result("recognize_sheet", {"image": str(_page_image(tmp_path))}))

        assert len(srv.review_jobs._jobs) == 0
