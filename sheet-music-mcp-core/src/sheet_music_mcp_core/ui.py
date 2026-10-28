"""MCP Apps UI resources: ``ui://`` HTML apps a tool links to through ``_meta.ui.resourceUri``.

A server registers its apps in a ``UiRegistry``, links tools with ``meta=registry.meta_for(app)``
and serves the registry through ``wiring.make_resource_handlers()``. The HTML is built from ``ui/``
and packaged with the server, so a source checkout may lack it; the registry then hides the app.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from typing import Iterable, Protocol

from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID, client_supports_apps
from mcp.types import ReadResourceResult, Resource, TextResourceContents

from .errors import ProcessingError

UI_MIME = APP_MIME_TYPE
UI_EXTENSION = EXTENSION_ID

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


@dataclass(frozen=True)
class UiResource:
    """One ``ui://`` app: its URI, the asset file holding its HTML, and how hosts list it."""

    uri: str
    asset: str
    name: str
    description: str | None = None

    def tool_meta(self) -> dict:
        """The ``_meta`` a tool carries to open this app."""
        return {"ui": {"resourceUri": self.uri}}


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

    def meta_for(self, resource: UiResource) -> dict | None:
        """The tool ``_meta`` linking to ``resource``, or None when its HTML is not packaged.

        The spec requires a linked resource to exist, so a missing build drops the link rather
        than pointing hosts at a read that fails.
        """
        if self._resources.get(resource.uri) != resource:
            raise ValueError(f"UI resource {resource.uri} is not registered")
        return resource.tool_meta() if self._packaged(resource) else None

    def list_resources(self) -> list[Resource]:
        """The apps whose HTML is packaged."""
        return [
            Resource(uri=r.uri, name=r.name, description=r.description, mime_type=UI_MIME)
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
        return ReadResourceResult(contents=[TextResourceContents(uri=uri, mime_type=UI_MIME, text=html)])

    def _packaged(self, resource: UiResource) -> bool:
        # Cached: every tools/list and tools/call asks, and a built app is several MB. Packaged
        # assets do not change while the server runs.
        if resource.uri not in self._packaged_uris:
            self._packaged_uris[resource.uri] = self._source.read(resource.asset) is not None
        return self._packaged_uris[resource.uri]


def client_supports_ui(ctx) -> bool:
    """Whether the client's initialize capabilities offer MCP Apps (proposal §6.5).

    The SDK also requires ``UI_MIME`` in the extension's ``mimeTypes``, as the ext-apps spec has
    clients advertise it.
    """
    return client_supports_apps(ctx)
