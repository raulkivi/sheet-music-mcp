"""pytest configuration for pitch-mcp tests."""

import pytest


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
