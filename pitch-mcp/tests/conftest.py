"""pytest configuration for pitch-mcp tests."""

import pytest
from sheet_music_mcp_core.ui import InMemoryAssetSource, UiRegistry

import pitch_mcp.server as server

COACH_HTML = "<!doctype html><title>Practice Coach</title>"
DOCTOR_HTML = "<!doctype html><title>Setup Doctor</title>"


def registry(*, packaged: bool) -> UiRegistry:
    """The server's UI registry over in-memory assets, with or without the built apps."""
    assets = {}
    if packaged:
        assets[server.PRACTICE_COACH.asset] = COACH_HTML
        assets[server.SETUP_DOCTOR.asset] = DOCTOR_HTML
    return UiRegistry(
        [server.PRACTICE_COACH, server.SETUP_DOCTOR], InMemoryAssetSource(assets)
    )


@pytest.fixture(autouse=True)
def unpackaged_ui(monkeypatch):
    """Tests see a source checkout without a UI build, whatever a local build left behind."""
    monkeypatch.setattr(server, "ui_registry", registry(packaged=False))


@pytest.fixture
def packaged_ui(monkeypatch):
    """The Practice Coach HTML is packaged, as in a released wheel."""
    monkeypatch.setattr(server, "ui_registry", registry(packaged=True))


def pytest_collection_modifyitems(config, items):
    """Skip integration/manual-marked tests unless explicitly requested via -m."""
    mark_expr = config.option.markexpr if hasattr(config.option, "markexpr") else ""

    skip_integration = pytest.mark.skip(
        reason="Integration test — run with: pytest tests/ -v -m integration"
    )
    skip_manual = pytest.mark.skip(
        reason="Manual test (requires a real microphone) — run with: pytest tests/ -v -m manual"
    )

    for item in items:
        if mark_expr != "integration" and item.get_closest_marker("integration"):
            item.add_marker(skip_integration)
        if mark_expr != "manual" and item.get_closest_marker("manual"):
            item.add_marker(skip_manual)


@pytest.fixture(autouse=True, scope="session")
def _stop_session_reaper():
    """load_score starts the idle-session reaper thread lazily; stop it when the run ends."""
    yield
    from pitch_mcp import engine

    engine._stop_reaper()
