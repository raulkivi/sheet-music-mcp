"""MCP Apps UI resources: ``ui://`` HTML apps a tool links to through ``_meta.ui.resourceUri``.

A server registers its apps in a ``UiRegistry``, links tools with ``meta=registry.meta_for(app)``
and serves the registry through ``wiring.make_resource_handlers()``. Tools only an app calls take
``meta_for(app, app_only=True)``; ``wiring.make_handlers()`` hides them from clients without UI. The HTML is built from ``ui/``
and packaged with the server, so a source checkout may lack it; the registry then hides the app.

An app that needs the microphone, the clipboard or network origins declares them on its
``UiResource`` (``permissions``, ``csp``); the registry sends them as the resource's ``_meta.ui``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.resources import files
from typing import Iterable, Mapping, Protocol, TypeVar

from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID, ResourceCsp, ResourcePermissions, client_supports_apps
from mcp.types import ReadResourceResult, Resource, TextResourceContents, Tool
from pydantic import BaseModel

from .errors import ProcessingError

UI_MIME = APP_MIME_TYPE
UI_EXTENSION = EXTENSION_ID

# McpUiToolMeta.visibility for a tool the app calls and the model never sees.
_APP_ONLY = ["app"]

_BUILD_HINT = "Build the UI: run `npm run build` in ui/, then reinstall the server."


class AssetSource(Protocol):
    """Where a registry finds the built HTML, so it never touches the filesystem itself."""

    def read(self, name: str) -> str | None:
        """The asset's text, or None if it is not packaged."""
        ...


class PackageAssetSource:
    """Assets shipped inside a package, ``<package>/<directory>/<name>``."""

    def __init__(self, package: str, directory: str = "ui/assets"):
        self._package = package
        self._directory = directory

    def read(self, name: str) -> str | None:
        asset = files(self._package).joinpath(self._directory, name)
        return asset.read_text(encoding="utf-8") if asset.is_file() else None


class InMemoryAssetSource:
    """Assets held in memory, for tests that need no UI build."""

    def __init__(self, mapping: dict[str, str]):
        self._assets = dict(mapping)

    def read(self, name: str) -> str | None:
        return self._assets.get(name)


_M = TypeVar("_M", bound=BaseModel)


def _spec_model(model_type: type[_M], value: object, label: str) -> _M | None:
    """``value`` as the SDK model, from the model itself or its spec JSON (camelCase keys).

    Unknown keys are refused: the SDK model ignores them, so a typo such as ``microphon`` would
    silently drop the request and the host would never ask the user.
    """
    if value is None:
        return None
    if isinstance(value, model_type):
        # A copy, so the caller's model can change without changing a frozen resource.
        return value.model_copy(deep=True)
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a {model_type.__name__} or a mapping, got {type(value).__name__}")
    known = set(model_type.model_fields) | {f.alias for f in model_type.model_fields.values() if f.alias}
    unknown = sorted(str(key) for key in value if key not in known)
    if unknown:
        raise ValueError(f"Unknown {label} key(s): {', '.join(unknown)}")
    return model_type.model_validate(dict(value))


@dataclass(frozen=True)
class UiResource:
    """One ``ui://`` app: its URI, the asset file holding its HTML, and how hosts list it.

    ``permissions`` (``microphone``, ``camera``, ``geolocation``, ``clipboardWrite``) and ``csp``
    (``connectDomains``, ``resourceDomains``, ``frameDomains``, ``baseUriDomains``) follow the
    ext-apps ``McpUiResourceMeta``. Pass the SDK's ``ResourcePermissions`` / ``ResourceCsp`` or
    the same JSON as a mapping; either way the field holds the SDK model.
    """

    uri: str
    asset: str
    name: str
    description: str | None = None
    # Left out of the hash: the SDK models are unhashable, and uri already identifies the app.
    permissions: ResourcePermissions | None = field(default=None, hash=False)
    csp: ResourceCsp | None = field(default=None, hash=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "permissions", _spec_model(ResourcePermissions, self.permissions, "permissions"))
        object.__setattr__(self, "csp", _spec_model(ResourceCsp, self.csp, "csp"))

    def tool_meta(self, *, app_only: bool = False) -> dict:
        """The ``_meta`` a tool carries to open this app, or, ``app_only``, to serve only it."""
        ui: dict = {"resourceUri": self.uri}
        if app_only:
            ui["visibility"] = list(_APP_ONLY)
        return {"ui": ui}

    def resource_meta(self) -> dict | None:
        """The resource's ``_meta`` (``{"ui": {"permissions", "csp"}}``), or None when it asks for nothing.

        None keeps the listing of an app without permissions or CSP exactly as it was. A new dict
        each call, so a caller editing one result cannot change the next.
        """
        ui: dict = {}
        for key, model in (("permissions", self.permissions), ("csp", self.csp)):
            dumped = model.model_dump(by_alias=True, exclude_none=True) if model is not None else {}
            if dumped:
                ui[key] = dumped
        return {"ui": ui} if ui else None


class UiAssetMissing(ProcessingError):
    """A registered app whose HTML was not built or packaged (UI_ASSET_MISSING)."""

    def __init__(self, resource: UiResource):
        super().__init__(
            f"UI asset '{resource.asset}' for {resource.uri} is not packaged. {_BUILD_HINT}",
            "UI_ASSET_MISSING",
            hint=_BUILD_HINT,
        )


class UiResourceNotFound(ProcessingError):
    """A URI no registered app answers to (RESOURCE_NOT_FOUND)."""

    def __init__(self, uri: str):
        super().__init__(f"Unknown resource: {uri}", "RESOURCE_NOT_FOUND")


class UiRegistry:
    """The apps a server offers. New apps are registered here; the handlers do not change."""

    def __init__(self, resources: Iterable[UiResource], source: AssetSource):
        self._resources: dict[str, UiResource] = {}
        for resource in resources:
            if resource.uri in self._resources:
                raise ValueError(f"UI resource {resource.uri} is registered twice")
            self._resources[resource.uri] = resource
        self._source = source
        self._packaged_uris: dict[str, bool] = {}

    def meta_for(self, resource: UiResource, *, app_only: bool = False) -> dict | None:
        """The tool ``_meta`` linking to ``resource``, or None when its HTML is not packaged.

        The spec requires a linked resource to exist, so a missing build drops the link rather
        than pointing hosts at a read that fails. An ``app_only`` tool keeps its visibility
        without the link, so a source checkout never shows the model a tool meant for an app.
        """
        if self._resources.get(resource.uri) != resource:
            raise ValueError(f"UI resource {resource.uri} is not registered")
        if self._packaged(resource):
            return resource.tool_meta(app_only=app_only)
        return {"ui": {"visibility": list(_APP_ONLY)}} if app_only else None

    def list_resources(self) -> list[Resource]:
        """The apps whose HTML is packaged, with ``_meta.ui`` for those that declare it."""
        return [
            Resource(uri=r.uri, name=r.name, description=r.description, mime_type=UI_MIME, meta=r.resource_meta())
            for r in self._resources.values()
            if self._packaged(r)
        ]

    def read(self, uri: str) -> ReadResourceResult:
        """The app's HTML; raises UiResourceNotFound or UiAssetMissing."""
        resource = self._resources.get(uri)
        if resource is None:
            raise UiResourceNotFound(uri)
        html = self._source.read(resource.asset)
        if html is None:
            raise UiAssetMissing(resource)
        # ext-apps hosts take _meta.ui from the content item first and fall back to the listing,
        # so both carry it.
        contents = TextResourceContents(uri=uri, mime_type=UI_MIME, text=html, meta=resource.resource_meta())
        return ReadResourceResult(contents=[contents])

    def _packaged(self, resource: UiResource) -> bool:
        # Cached: every tools/list and tools/call asks, and a built app is several MB. Packaged
        # assets do not change while the server runs.
        if resource.uri not in self._packaged_uris:
            self._packaged_uris[resource.uri] = self._source.read(resource.asset) is not None
        return self._packaged_uris[resource.uri]


def is_app_only(tool: Tool) -> bool:
    """Whether ``tool`` is visible to apps only (``_meta.ui.visibility`` without "model")."""
    ui = (tool.meta or {}).get("ui")
    if not isinstance(ui, dict):
        return False
    visibility = ui.get("visibility")
    return isinstance(visibility, list) and "app" in visibility and "model" not in visibility


def client_supports_ui(ctx) -> bool:
    """Whether the client's initialize capabilities offer MCP Apps (proposal §6.5).

    The SDK also requires ``UI_MIME`` in the extension's ``mimeTypes``, as the ext-apps spec has
    clients advertise it.
    """
    return client_supports_apps(ctx)
