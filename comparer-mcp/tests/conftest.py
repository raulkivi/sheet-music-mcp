"""pytest configuration for comparer-mcp tests."""

import pytest
from sheet_music_mcp_core.ui import InMemoryAssetSource, UiRegistry

import comparer_mcp.server as server

VIEWER_HTML = "<!doctype html><title>Diff Viewer</title>"


def registry(*, packaged: bool) -> UiRegistry:
    """The server's UI registry over in-memory assets, with or without the built viewer."""
    assets = {server.DIFF_VIEWER.asset: VIEWER_HTML} if packaged else {}
    return UiRegistry([server.DIFF_VIEWER], InMemoryAssetSource(assets))


@pytest.fixture(autouse=True)
def unpackaged_ui(monkeypatch):
    """Tests see a source checkout without a UI build, whatever a local build left behind."""
    monkeypatch.setattr(server, "ui_registry", registry(packaged=False))


@pytest.fixture
def packaged_ui(monkeypatch):
    """The Diff Viewer HTML is packaged, as in a released wheel."""
    monkeypatch.setattr(server, "ui_registry", registry(packaged=True))
