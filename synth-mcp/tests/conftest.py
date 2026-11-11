"""pytest configuration for synth-mcp tests."""

import pytest
from sheet_music_mcp_core.artifacts import InMemoryArtifactStore
from sheet_music_mcp_core.ui import InMemoryAssetSource, UiRegistry

import synth_mcp.server as server
from synth_mcp.scorebook import ScoreBook

PLAYER_HTML = "<!doctype html><title>Practice Player</title>"
SETUP_DOCTOR_HTML = "<!doctype html><title>Setup Doctor</title>"


def registry(*, packaged: bool) -> UiRegistry:
    """The server's UI registry over in-memory assets, with or without the built apps."""
    assets = {}
    if packaged:
        assets[server.PRACTICE_PLAYER.asset] = PLAYER_HTML
        assets[server.SETUP_DOCTOR.asset] = SETUP_DOCTOR_HTML
    return UiRegistry([server.PRACTICE_PLAYER, server.SETUP_DOCTOR], InMemoryAssetSource(assets))


def use_store(monkeypatch, store) -> None:
    """Make the server keep its WAVs and scores in ``store``, the way production pairs them."""
    monkeypatch.setattr(server, "artifact_store", store)
    monkeypatch.setattr(server, "score_book", ScoreBook(lambda: server.artifact_store))


@pytest.fixture(autouse=True)
def isolated_output_root(tmp_path, monkeypatch):
    """Default output root for every test, so a default output path never lands in the repo."""
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))


@pytest.fixture(autouse=True)
def unpackaged_ui(monkeypatch):
    """Tests see a source checkout without a UI build, whatever a local build left behind."""
    monkeypatch.setattr(server, "ui_registry", registry(packaged=False))


@pytest.fixture(autouse=True)
def artifacts(monkeypatch):
    """A fresh store per test, so ids and scores never leak between tests."""
    store = InMemoryArtifactStore()
    use_store(monkeypatch, store)
    return store


@pytest.fixture
def packaged_ui(monkeypatch):
    """The Practice Player HTML is packaged, as in a released wheel."""
    monkeypatch.setattr(server, "ui_registry", registry(packaged=True))
