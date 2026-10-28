import pytest
from sheet_music_mcp_core.ui import InMemoryAssetSource, UiRegistry

import render_mcp.server as server

VIEWER_HTML = "<!doctype html><title>Score Viewer</title>"


def registry(*, packaged: bool) -> UiRegistry:
    """The server's UI registry over in-memory assets, with or without the built viewer."""
    assets = {server.SCORE_VIEWER.asset: VIEWER_HTML} if packaged else {}
    return UiRegistry([server.SCORE_VIEWER], InMemoryAssetSource(assets))


@pytest.fixture(autouse=True)
def unpackaged_ui(monkeypatch):
    """Tests see a source checkout without a UI build, whatever ``npm run copy-assets`` left behind."""
    monkeypatch.setattr(server, "ui_registry", registry(packaged=False))


@pytest.fixture
def packaged_ui(monkeypatch):
    """The Score Viewer HTML is packaged, as in a released wheel."""
    monkeypatch.setattr(server, "ui_registry", registry(packaged=True))
