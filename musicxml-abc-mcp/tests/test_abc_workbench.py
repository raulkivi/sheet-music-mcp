"""ABC Workbench linking: the ``ui://abc/workbench`` resource, tool ``_meta``, ``structuredContent``
and the app-only ``get_abc`` (proposal 5.6, AC-A1 to AC-A3 server side)."""

import asyncio
import json

import jsonschema
import pytest
from mcp import Client, MCPError
from mcp.client import advertise
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS
from sheet_music_mcp_core.ui import UI_EXTENSION, UI_MIME, is_app_only

from musicxml_abc_mcp.presenter import (
    ABC_OUTPUT_SCHEMA,
    CONVERSION_OUTPUT_SCHEMA,
    VALIDATION_OUTPUT_SCHEMA,
)
from musicxml_abc_mcp.server import app, call_tool_result, list_tools

from .conftest import WORKBENCH_HTML
from .test_measures import SATB_SIX_BARS
from .test_server import MINIMAL_ABC, MINIMAL_MUSICXML

WORKBENCH_URI = "ui://abc/workbench"
LINKED = ("musicxml_to_abc", "abc_to_musicxml")
UI_CLIENT = {"extensions": [advertise(UI_EXTENSION, {"mimeTypes": [UI_MIME]})]}


def _with_client(call, **client_kwargs):
    async def _go():
        async with Client(app, **client_kwargs) as client:
            return await call(client)

    return asyncio.run(_go())


async def _tools():
    return {tool.name: tool for tool in await list_tools()}


class TestToolLinking:
    @pytest.mark.parametrize("name", LINKED)
    async def test_tools_link_the_workbench_when_packaged(self, packaged_ui, name):
        assert (await _tools())[name].meta == {"ui": {"resourceUri": WORKBENCH_URI}}

    @pytest.mark.parametrize("name", LINKED)
    async def test_no_link_without_a_ui_build(self, name):
        assert (await _tools())[name].meta is None

    async def test_other_model_facing_tools_are_not_linked(self, packaged_ui):
        others = [t for n, t in (await _tools()).items() if n not in LINKED and not is_app_only(t)]

        assert others
        assert all(t.meta is None or "resourceUri" not in t.meta.get("ui", {}) for t in others)

    @pytest.mark.parametrize(
        "name, schema",
        [
            ("musicxml_to_abc", ABC_OUTPUT_SCHEMA),
            ("abc_to_musicxml", CONVERSION_OUTPUT_SCHEMA),
            ("validate_abc", VALIDATION_OUTPUT_SCHEMA),
        ],
    )
    async def test_structured_tools_declare_an_output_schema(self, name, schema):
        assert (await _tools())[name].output_schema == schema


class TestResources:
    def test_lists_the_workbench_when_packaged(self, packaged_ui):
        result = _with_client(lambda c: c.list_resources())

        assert [(r.uri, r.name, r.mime_type) for r in result.resources] == [
            (WORKBENCH_URI, "ABC Workbench", UI_MIME)
        ]

    def test_lists_nothing_without_a_ui_build(self):
        assert _with_client(lambda c: c.list_resources()).resources == []

    def test_reads_the_workbench_html(self, packaged_ui):
        [contents] = _with_client(lambda c: c.read_resource(WORKBENCH_URI)).contents

        assert (contents.uri, contents.mime_type, contents.text) == (WORKBENCH_URI, UI_MIME, WORKBENCH_HTML)

    def test_missing_build_is_an_error_naming_the_fix(self):
        async def read(client):
            with pytest.raises(MCPError) as caught:
                await client.read_resource(WORKBENCH_URI)
            return caught.value

        error = _with_client(read)

        assert error.code == INTERNAL_ERROR
        assert error.data["error_code"] == "UI_ASSET_MISSING"

    def test_unknown_resource_is_invalid_params(self, packaged_ui):
        async def read(client):
            with pytest.raises(MCPError) as caught:
                await client.read_resource("ui://abc/nope")
            return caught.value

        assert _with_client(read).code == INVALID_PARAMS


class TestMusicxmlToAbc:
    def _export(self, **arguments):
        arguments = {"musicxml": MINIMAL_MUSICXML, **arguments}
        return _with_client(lambda c: c.call_tool("musicxml_to_abc", arguments))

    def test_structured_content_is_the_export_plus_an_id(self):
        result = self._export()

        assert not result.is_error
        data = result.structured_content
        jsonschema.validate(data, ABC_OUTPUT_SCHEMA)
        assert {k: v for k, v in data.items() if k != "abc_id"} == json.loads(result.content[0].text)
        assert "abc_id" not in result.content[0].text

    def test_every_call_gets_a_new_id_even_for_identical_input(self):
        ids = {self._export().structured_content["abc_id"] for _ in range(3)}

        assert len(ids) == 3

    def test_part_and_measures_are_honoured(self):
        result = self._export(musicxml=SATB_SIX_BARS, part="Alto", measures=[3, 4])

        assert result.structured_content["parts_included"] == ["P2"]


class TestAbcToMusicxml:
    def test_inline_delivery_reports_size_and_warnings_but_not_the_score(self):
        result = _with_client(lambda c: c.call_tool("abc_to_musicxml", {"abc": MINIMAL_ABC}))

        data = result.structured_content
        jsonschema.validate(data, CONVERSION_OUTPUT_SCHEMA)
        text = json.loads(result.content[0].text)
        assert data == {
            "warnings": text["warnings"],
            "delivery": "inline",
            "musicxml_bytes": len(text["musicxml"].encode("utf-8")),
        }
        assert "musicxml" not in data  # proposal 6.3 rule 4

    def test_path_delivery_is_reported(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))

        result = _with_client(lambda c: c.call_tool("abc_to_musicxml", {"abc": MINIMAL_ABC, "return": "path"}))

        data = result.structured_content
        jsonschema.validate(data, CONVERSION_OUTPUT_SCHEMA)
        assert data["delivery"] == "path"
        assert data["musicxml_bytes"] > 0
        assert "path" not in "".join(data)  # no key or value leaks a location
        assert str(tmp_path) not in json.dumps(data)


class TestValidateAbc:
    @pytest.mark.parametrize("abc", [MINIMAL_ABC, "CDEF|", ""])
    def test_structured_content_equals_content(self, abc):
        result = _with_client(lambda c: c.call_tool("validate_abc", {"abc": abc}))

        assert not result.is_error
        assert result.structured_content == json.loads(result.content[0].text)
        jsonschema.validate(result.structured_content, VALIDATION_OUTPUT_SCHEMA)

    async def test_is_callable_by_the_app_and_the_model(self, packaged_ui):
        tool = (await _tools())["validate_abc"]

        assert not is_app_only(tool)


class TestGetAbc:
    async def test_is_app_only_and_never_linked_to_a_page_without_a_build(self):
        tool = (await _tools())["get_abc"]

        assert is_app_only(tool)
        assert tool.meta == {"ui": {"visibility": ["app"]}}
        assert set(tool.input_schema["properties"]) == {"abc_id"}
        assert tool.input_schema.get("additionalProperties") is False
        assert tool.output_schema == ABC_OUTPUT_SCHEMA

    async def test_links_the_workbench_when_packaged(self, packaged_ui):
        tool = (await _tools())["get_abc"]

        assert tool.meta == {"ui": {"resourceUri": WORKBENCH_URI, "visibility": ["app"]}}

    def test_hidden_from_clients_without_ui(self):
        names = {t.name for t in _with_client(lambda c: c.list_tools()).tools}

        assert "get_abc" not in names
        assert {"musicxml_to_abc", "abc_to_musicxml", "validate_abc"} <= names

    def test_listed_for_clients_with_ui(self):
        names = {t.name for t in _with_client(lambda c: c.list_tools(), **UI_CLIENT).tools}

        assert "get_abc" in names

    def test_returns_the_export_by_id_and_keeps_it_out_of_the_text(self):
        async def go(client):
            exported = await client.call_tool("musicxml_to_abc", {"musicxml": MINIMAL_MUSICXML})
            abc_id = exported.structured_content["abc_id"]
            return exported, await client.call_tool("get_abc", {"abc_id": abc_id})

        exported, fetched = _with_client(go)

        assert not fetched.is_error
        assert fetched.structured_content == exported.structured_content
        jsonschema.validate(fetched.structured_content, ABC_OUTPUT_SCHEMA)
        assert exported.structured_content["abc"] not in fetched.content[0].text

    def test_without_an_id_it_is_the_latest_export(self):
        async def go(client):
            await client.call_tool("musicxml_to_abc", {"musicxml": SATB_SIX_BARS, "part": "Soprano"})
            second = await client.call_tool("musicxml_to_abc", {"musicxml": SATB_SIX_BARS, "part": "Bass"})
            return second, await client.call_tool("get_abc", {})

        second, fetched = _with_client(go)

        assert fetched.structured_content == second.structured_content

    async def test_unknown_id_is_invalid_parameter_without_structured_content(self):
        result = await call_tool_result("get_abc", {"abc_id": "nope"})

        assert result.is_error
        assert result.structured_content is None
        assert json.loads(result.content[0].text)["error_code"] == "INVALID_PARAMETER"

    async def test_nothing_exported_yet_is_invalid_parameter(self):
        result = await call_tool_result("get_abc", {})

        assert result.is_error
        assert json.loads(result.content[0].text)["error_code"] == "INVALID_PARAMETER"

    @pytest.mark.parametrize("extra", [{"musicxml_path": "/etc/passwd"}, {"path": "/etc/passwd"}])
    def test_paths_are_not_accepted(self, extra):
        result = _with_client(lambda c: c.call_tool("get_abc", {"abc_id": "x", **extra}))

        assert result.is_error
        assert json.loads(result.content[0].text)["error_code"] == "INVALID_PARAMETER"

    def test_a_traversal_looking_id_is_just_an_unknown_id(self):
        result = _with_client(lambda c: c.call_tool("get_abc", {"abc_id": "../../../etc/passwd"}))

        assert result.is_error
        assert "etc/passwd" not in result.content[0].text


class TestErrors:
    @pytest.mark.parametrize(
        "tool, arguments, code",
        [
            ("musicxml_to_abc", {"musicxml": "<nope/>"}, "INVALID_INPUT"),
            ("musicxml_to_abc", {"musicxml": SATB_SIX_BARS, "part": "Tuba"}, "INVALID_PARAMETER"),
            ("musicxml_to_abc", {"musicxml": SATB_SIX_BARS, "measures": [9, 12]}, "INVALID_PARAMETER"),
            ("abc_to_musicxml", {"abc": ""}, "INVALID_INPUT"),
            ("abc_to_musicxml", {"abc": MINIMAL_ABC, "return": "carrier-pigeon"}, "INVALID_PARAMETER"),
        ],
    )
    def test_keep_the_envelope_and_carry_no_structured_content(self, tool, arguments, code):
        result = _with_client(lambda c: c.call_tool(tool, arguments))

        assert result.is_error
        assert result.structured_content is None
        assert json.loads(result.content[0].text)["error_code"] == code

    def test_a_failed_export_stores_nothing(self):
        _with_client(lambda c: c.call_tool("musicxml_to_abc", {"musicxml": "<nope/>"}))

        result = _with_client(lambda c: c.call_tool("get_abc", {}))

        assert result.is_error
