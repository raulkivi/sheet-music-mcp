"""MCP Apps UI resources (docs/research/mcp-apps-phase0-spike-plan.md, step 2)."""

import asyncio

import pytest
from mcp import Client
from mcp.client import advertise
from mcp.server import Server
from mcp.server.apps import ResourceCsp, ResourcePermissions
from mcp.types import ListToolsResult, Tool

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
    is_app_only,
)
from sheet_music_mcp_core.wiring import make_resource_handlers

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


def test_app_only_tool_meta_adds_the_visibility():
    # Proposal §6.5: callable by the app, hidden from the model.
    assert VIEWER.tool_meta(app_only=True) == {
        "ui": {"resourceUri": "ui://test/viewer", "visibility": ["app"]}
    }


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


def test_app_only_meta_for_a_packaged_asset():
    assert _registry().meta_for(VIEWER, app_only=True) == VIEWER.tool_meta(app_only=True)


def test_app_only_meta_without_the_asset_keeps_the_tool_hidden():
    # A source checkout must not hand the model a tool meant only for an app; resourceUri is
    # optional in McpUiToolMeta, so the link alone is dropped.
    assert _registry().meta_for(PLAYER, app_only=True) == {"ui": {"visibility": ["app"]}}


def _tool(meta):
    return Tool(name="t", input_schema={"type": "object"}, meta=meta)


@pytest.mark.parametrize(
    "meta, expected",
    [
        (None, False),
        ({}, False),
        ({"ui": {"resourceUri": "ui://test/viewer"}}, False),
        ({"ui": {"visibility": ["model", "app"]}}, False),
        ({"ui": {"visibility": ["model"]}}, False),
        ({"ui": {"visibility": ["app"]}}, True),
        ({"ui": {"resourceUri": "ui://test/viewer", "visibility": ["app"]}}, True),
        ({"ui": "not a mapping"}, False),
    ],
)
def test_is_app_only(meta, expected):
    assert is_app_only(_tool(meta)) is expected


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


def test_packaged_check_reads_each_asset_once():
    # Tool listings run on every call and a built app is several MB, so the check is cached.
    class CountingSource(InMemoryAssetSource):
        reads = 0

        def read(self, name):
            CountingSource.reads += 1
            return super().read(name)

    registry = UiRegistry((VIEWER, PLAYER), CountingSource({"viewer.html": HTML}))
    for _ in range(3):
        registry.meta_for(VIEWER)
        registry.meta_for(PLAYER)
        registry.list_resources()

    assert CountingSource.reads == 2


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


# --- Resource _meta.ui: permissions and CSP (ext-apps McpUiResourceMeta) ----------------------

COACH = UiResource(
    "ui://test/coach",
    "coach.html",
    "Practice Coach",
    permissions=ResourcePermissions(microphone={}),
    csp=ResourceCsp(connect_domains=["https://api.example.com"]),
)
COACH_UI = {
    "permissions": {"microphone": {}},
    "csp": {"connectDomains": ["https://api.example.com"]},
}


def _coach_registry():
    return UiRegistry((VIEWER, COACH), InMemoryAssetSource({"viewer.html": HTML, "coach.html": HTML}))


def test_resource_without_permissions_or_csp_has_no_resource_meta():
    assert VIEWER.resource_meta() is None


def test_resource_meta_uses_the_spec_field_names():
    assert COACH.resource_meta() == {"ui": COACH_UI}


def test_permissions_and_csp_may_be_given_in_wire_form():
    # Same JSON as the ext-apps spec, so a server author can copy it from there.
    resource = UiResource(
        "ui://test/coach",
        "coach.html",
        "Practice Coach",
        permissions={"microphone": {}},
        csp={"connectDomains": ["https://api.example.com"]},
    )

    assert resource == COACH
    assert isinstance(resource.permissions, ResourcePermissions)
    assert isinstance(resource.csp, ResourceCsp)


@pytest.mark.parametrize(
    "kwargs, field",
    [
        ({"permissions": {"microphon": {}}}, "microphon"),
        ({"csp": {"connect_domain": ["https://a"]}}, "connect_domain"),
    ],
)
def test_unknown_permission_or_csp_keys_are_rejected(kwargs, field):
    # A typo would otherwise drop the request silently and the host would never ask the user.
    with pytest.raises(ValueError, match=field):
        UiResource("ui://test/x", "x.html", "X", **kwargs)


def test_permissions_of_the_wrong_type_are_rejected():
    with pytest.raises(ValueError):
        UiResource("ui://test/x", "x.html", "X", permissions=["microphone"])


def test_empty_permissions_add_no_resource_meta():
    assert UiResource("ui://test/x", "x.html", "X", permissions={}).resource_meta() is None


def test_only_set_parts_are_emitted():
    resource = UiResource("ui://test/x", "x.html", "X", permissions={"clipboardWrite": {}})

    assert resource.resource_meta() == {"ui": {"permissions": {"clipboardWrite": {}}}}


def test_resource_with_permissions_stays_hashable_and_immutable():
    permissions = ResourcePermissions(microphone={})
    resource = UiResource("ui://test/x", "x.html", "X", permissions=permissions)
    permissions.camera = {}

    assert hash(resource) == hash(UiResource("ui://test/x", "x.html", "X", permissions={"microphone": {}}))
    assert resource.permissions.camera is None


def test_tool_meta_does_not_carry_resource_meta():
    # Permissions and CSP belong on the resource, not the tool (McpUiToolMeta has neither).
    assert COACH.tool_meta() == {"ui": {"resourceUri": "ui://test/coach"}}


def test_list_resources_carries_resource_meta_only_when_set():
    resources = {r.uri: r for r in _coach_registry().list_resources()}

    assert resources["ui://test/viewer"].meta is None
    assert resources["ui://test/coach"].meta == {"ui": COACH_UI}


def test_read_carries_resource_meta_only_when_set():
    registry = _coach_registry()

    [viewer] = registry.read("ui://test/viewer").contents
    [coach] = registry.read("ui://test/coach").contents
    assert viewer.meta is None
    assert coach.meta == {"ui": COACH_UI}


def test_each_resource_gets_its_own_meta_dict():
    # A caller mutating one listing must not change the next one.
    registry = _coach_registry()
    registry.list_resources()[1].meta["ui"]["permissions"]["camera"] = {}

    assert registry.list_resources()[1].meta == {"ui": COACH_UI}


def test_existing_resource_output_is_unchanged_on_the_wire():
    [resource] = _registry().list_resources()
    [contents] = _registry().read("ui://test/viewer").contents

    assert "_meta" not in resource.model_dump(by_alias=True, exclude_none=True)
    assert "_meta" not in contents.model_dump(by_alias=True, exclude_none=True)


def test_microphone_permission_reaches_the_client():
    on_list_resources, on_read_resource = make_resource_handlers(_coach_registry())
    server = Server("test", on_list_resources=on_list_resources, on_read_resource=on_read_resource)

    async def _go():
        async with Client(server) as client:
            return await client.list_resources(), await client.read_resource("ui://test/coach")

    listed, read = asyncio.run(_go())

    [coach] = [r for r in listed.resources if r.uri == "ui://test/coach"]
    assert coach.meta["ui"]["permissions"]["microphone"] == {}
    assert read.contents[0].meta["ui"]["permissions"]["microphone"] == {}
    assert read.contents[0].meta["ui"]["csp"] == {"connectDomains": ["https://api.example.com"]}
