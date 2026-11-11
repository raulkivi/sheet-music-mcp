"""pytest configuration for musicxml-abc-mcp tests."""

import pytest
from sheet_music_mcp_core.ui import InMemoryAssetSource, UiRegistry

import musicxml_abc_mcp.server as server

WORKBENCH_HTML = "<!doctype html><title>ABC Workbench</title>"
SETUP_DOCTOR_HTML = "<!doctype html><title>Setup Doctor</title>"


def registry(*, packaged: bool) -> UiRegistry:
    """The server's UI registry over in-memory assets, with or without a UI build."""
    assets = {
        server.ABC_WORKBENCH.asset: WORKBENCH_HTML,
        server.SETUP_DOCTOR.asset: SETUP_DOCTOR_HTML,
    } if packaged else {}
    return UiRegistry([server.ABC_WORKBENCH, server.SETUP_DOCTOR], InMemoryAssetSource(assets))


@pytest.fixture(autouse=True)
def unpackaged_ui(monkeypatch):
    """Tests see a source checkout without a UI build, whatever a local build left behind."""
    monkeypatch.setattr(server, "ui_registry", registry(packaged=False))


@pytest.fixture
def packaged_ui(monkeypatch):
    """The workbench HTML is packaged, as in a released wheel."""
    monkeypatch.setattr(server, "ui_registry", registry(packaged=True))


@pytest.fixture(autouse=True)
def fresh_abc_store(monkeypatch):
    """Every test starts with no remembered ABC, so ids and 'latest' never leak between tests."""
    monkeypatch.setattr(server, "abc_store", server.AbcStore())
