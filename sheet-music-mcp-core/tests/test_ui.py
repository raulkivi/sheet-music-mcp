"""MCP Apps UI resources (docs/research/mcp-apps-phase0-spike-plan.md, step 2)."""

import asyncio

import pytest
from mcp import Client
from mcp.client import advertise
from mcp.server import Server
from mcp.types import ListToolsResult

from sheet_music_mcp_core.errors import ProcessingError
from sheet_music_mcp_core.ui import (
    UI_EXTENSION,
    UI_MIME,
    InMemoryAssetSource,
    PackageAssetSource,
    UiAssetMissing,
    UiRegistry,
    UiResource,
    UiResourceNotFound,
    client_supports_ui,
)

HTML = "<!doctype html><title>viewer</title>"
VIEWER = UiResource("ui://test/viewer", "viewer.html", "Score Viewer", "Pages through a score")
PLAYER = UiResource("ui://test/player", "player.html", "Practice Player")


def _registry(assets=None, resources=(VIEWER, PLAYER)):
    return UiRegistry(resources, InMemoryAssetSource({"viewer.html": HTML} if assets is None else assets))


def test_constants_follow_the_ext_apps_spec():
    assert UI_MIME == "text/html;profile=mcp-app"
    assert UI_EXTENSION == "io.modelcontextprotocol/ui"


def test_tool_meta_points_at_the_resource():
    assert VIEWER.tool_meta() == {"ui": {"resourceUri": "ui://test/viewer"}}


def test_ui_resource_is_immutable():
    with pytest.raises(AttributeError):
        VIEWER.uri = "ui://other"


def test_in_memory_source_reads_known_assets_only():
    source = InMemoryAssetSource({"viewer.html": HTML})

    assert source.read("viewer.html") == HTML
    assert source.read("player.html") is None


def test_in_memory_source_keeps_its_own_copy():
    assets = {"viewer.html": HTML}
    source = InMemoryAssetSource(assets)
    assets["viewer.html"] = "changed"

    assert source.read("viewer.html") == HTML


def test_package_source_reads_packaged_files():
    # The core's own modules stand in for a server's built UI assets.
    source = PackageAssetSource("sheet_music_mcp_core", directory=".")

    assert '"""MCP Apps UI resources' in source.read("ui.py")
    assert source.read("score-viewer.html") is None


def test_package_source_defaults_to_ui_assets():
    assert PackageAssetSource("sheet_music_mcp_core").read("__init__.py") is None


def test_meta_for_a_packaged_asset():
    assert _registry().meta_for(VIEWER) == VIEWER.tool_meta()


def test_meta_for_a_missing_asset_is_none():
    # The spec requires the referenced resource to exist, so the tool carries no UI link.
    assert _registry().meta_for(PLAYER) is None


def test_meta_for_an_unregistered_resource_is_a_programming_error():
    other = UiResource("ui://test/other", "viewer.html", "Other")

    with pytest.raises(ValueError, match="ui://test/other"):
        _registry().meta_for(other)


def test_duplicate_uris_are_rejected():
    with pytest.raises(ValueError, match="ui://test/viewer"):
        _registry(resources=(VIEWER, UiResource(VIEWER.uri, "player.html", "Again")))


def test_list_resources_omits_missing_assets():
    [resource] = _registry().list_resources()

    assert resource.uri == "ui://test/viewer"
    assert resource.name == "Score Viewer"
    assert resource.description == "Pages through a score"
    assert resource.mime_type == UI_MIME


def test_list_resources_is_empty_without_assets():
    assert _registry(assets={}).list_resources() == []


def test_read_returns_the_html_with_the_app_mime_type():
    result = _registry().read("ui://test/viewer")

    [contents] = result.contents
    assert (contents.uri, contents.mime_type, contents.text) == ("ui://test/viewer", UI_MIME, HTML)


def test_read_of_a_missing_asset_names_the_build_step():
    with pytest.raises(UiAssetMissing) as caught:
        _registry().read("ui://test/player")

    error = caught.value
    assert isinstance(error, ProcessingError)
    assert error.error_code == "UI_ASSET_MISSING"
    assert "player.html" in str(error)
    assert "npm run build" in str(error)
    assert "ui/" in str(error)


def test_read_of_an_unknown_uri_is_not_found():
    with pytest.raises(UiResourceNotFound) as caught:
        _registry().read("ui://test/nope")

    error = caught.value
    assert not isinstance(error, UiAssetMissing)
    assert error.error_code == "RESOURCE_NOT_FOUND"
    assert "ui://test/nope" in str(error)


def _ctx_seen_by_server(**client_kwargs):
    seen = {}

    async def on_list_tools(ctx, params):
        seen["ctx"] = ctx
        return ListToolsResult(tools=[])

    async def _go():
        async with Client(Server("test", on_list_tools=on_list_tools), **client_kwargs) as client:
            await client.list_tools()

    asyncio.run(_go())
    return seen["ctx"]


def test_client_supports_ui_when_it_advertises_the_extension():
    ctx = _ctx_seen_by_server(extensions=[advertise(UI_EXTENSION, {"mimeTypes": [UI_MIME]})])

    assert client_supports_ui(ctx)


def test_client_without_the_extension_does_not_support_ui():
    assert not client_supports_ui(_ctx_seen_by_server())
