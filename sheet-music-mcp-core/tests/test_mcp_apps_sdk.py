"""Pins down the mcp SDK behaviour MCP Apps support relies on (spike plan step 1).

If one of these fails after an SDK upgrade, ``sheet_music_mcp_core.ui`` needs revisiting.
"""

import asyncio

import pytest
from mcp import Client, MCPError
from mcp.client import advertise
from mcp.server import Server
from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID, client_supports_apps
from mcp.types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    ListResourcesResult,
    ListToolsResult,
    ReadResourceResult,
    Resource,
    TextResourceContents,
    Tool,
)

MIME = "text/html;profile=mcp-app"
EXTENSION = "io.modelcontextprotocol/ui"
URI = "ui://test/viewer"
VIEWER = Tool(
    name="view",
    description="Has a UI",
    input_schema={"type": "object"},
    meta={"ui": {"resourceUri": URI}},
)


def _run(server, call, **client_kwargs):
    async def _go():
        async with Client(server, **client_kwargs) as client:
            return await call(client)

    return asyncio.run(_go())


def _capturing_server(seen):
    async def on_list_tools(ctx, params):
        seen["ctx"] = ctx
        return ListToolsResult(tools=[VIEWER])

    return Server("test", on_list_tools=on_list_tools)


def test_sdk_constants_match_the_ext_apps_spec():
    assert (APP_MIME_TYPE, EXTENSION_ID) == (MIME, EXTENSION)


def test_client_extension_settings_reach_the_server_handler():
    seen = {}
    settings = {"mimeTypes": [MIME]}

    _run(_capturing_server(seen), lambda c: c.list_tools(), extensions=[advertise(EXTENSION, settings)])

    capabilities = seen["ctx"].session.client_capabilities
    assert capabilities.extensions[EXTENSION] == settings
    assert client_supports_apps(seen["ctx"])


def test_client_without_the_extension_is_not_ui_capable():
    seen = {}

    _run(_capturing_server(seen), lambda c: c.list_tools())

    assert not client_supports_apps(seen["ctx"])


def test_extension_without_the_app_mime_type_is_not_ui_capable():
    # The SDK requires the MIME type in the settings, not just the extension key.
    seen = {}

    _run(_capturing_server(seen), lambda c: c.list_tools(), extensions=[advertise(EXTENSION, {})])

    assert not client_supports_apps(seen["ctx"])


def test_tool_meta_is_sent_as_underscore_meta():
    assert VIEWER.model_dump(by_alias=True, exclude_none=True)["_meta"] == {"ui": {"resourceUri": URI}}

    result = _run(_capturing_server({}), lambda c: c.list_tools())

    assert result.tools[0].meta == {"ui": {"resourceUri": URI}}


def _resource_server(read):
    async def on_list_resources(ctx, params):
        return ListResourcesResult(resources=[Resource(uri=URI, name="viewer", mime_type=MIME)])

    async def on_read_resource(ctx, params):
        return await read(params)

    return Server("test", on_list_resources=on_list_resources, on_read_resource=on_read_resource)


def test_mime_profile_parameter_survives_list_and_read():
    async def read(params):
        return ReadResourceResult(
            contents=[TextResourceContents(uri=params.uri, mime_type=MIME, text="<!doctype html>")]
        )

    async def both(client):
        return await client.list_resources(), await client.read_resource(URI)

    listed, result = _run(_resource_server(read), both)

    assert listed.resources[0].mime_type == MIME
    [contents] = result.contents
    assert (contents.uri, contents.mime_type, contents.text) == (URI, MIME, "<!doctype html>")


def _read_error(server):
    """The MCPError a read raises, caught inside the session (outside it arrives as a TaskGroup error)."""

    async def read(client):
        try:
            await client.read_resource(URI)
        except MCPError as e:
            return e
        pytest.fail("read_resource did not raise")

    return _run(server, read)


def test_mcp_error_from_a_resource_handler_reaches_the_client_as_is():
    async def read(params):
        raise MCPError(INVALID_PARAMS, "Unknown resource", data={"uri": params.uri})

    error = _read_error(_resource_server(read))

    assert (error.code, error.message, error.data) == (INVALID_PARAMS, "Unknown resource", {"uri": URI})


def test_other_exception_from_a_resource_handler_becomes_an_opaque_internal_error():
    async def read(params):
        raise RuntimeError("asset gone")

    error = _read_error(_resource_server(read))

    # The message is not forwarded, so a handler must raise MCPError to explain itself.
    assert (error.code, error.message) == (INTERNAL_ERROR, "Internal server error")
