"""pytest configuration for omr-mcp tests."""

import pytest
from sheet_music_mcp_core.artifacts import InMemoryArtifactStore
from sheet_music_mcp_core.ui import InMemoryAssetSource, UiRegistry

import omr_mcp.server as server
from omr_mcp.previews import ReviewJobs

REVIEW_HTML = "<!doctype html><title>Recognition Review</title>"


def registry(*, packaged: bool) -> UiRegistry:
    """The server's UI registry over in-memory assets, with or without the built app."""
    assets = {server.RECOGNITION_REVIEW.asset: REVIEW_HTML} if packaged else {}
    return UiRegistry([server.RECOGNITION_REVIEW], InMemoryAssetSource(assets))


@pytest.fixture(autouse=True)
def unpackaged_ui(monkeypatch):
    """Tests see a source checkout without a UI build, whatever a local build left behind."""
    monkeypatch.setattr(server, "ui_registry", registry(packaged=False))


@pytest.fixture
def packaged_ui(monkeypatch):
    """The Recognition Review HTML is packaged, as in a released wheel."""
    monkeypatch.setattr(server, "ui_registry", registry(packaged=True))


@pytest.fixture(autouse=True)
def artifact_store(monkeypatch):
    """Previews go to memory and every test starts with no jobs."""
    store = InMemoryArtifactStore()
    monkeypatch.setattr(server, "artifact_store", store)
    monkeypatch.setattr(server, "review_jobs", ReviewJobs())
    return store


def pytest_collection_modifyitems(config, items):
    """Skip integration-marked tests unless explicitly requested with -m integration."""
    mark_expr = config.option.markexpr if hasattr(config.option, "markexpr") else ""
    if mark_expr == "integration":
        return  # user is explicitly running integration tests — don't skip

    skip_integration = pytest.mark.skip(
        reason="Integration test — run with: uv run pytest tests/ -v -m integration"
    )
    for item in items:
        if item.get_closest_marker("integration"):
            item.add_marker(skip_integration)
