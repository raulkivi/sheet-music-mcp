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


# ---------------------------------------------------------------------------
# Manual-run evidence (S6/R8): PITCH_MANUAL_EVIDENCE=1 with -m manual writes a git note through
# tools/release-evidence. The logic is in tests/manual_evidence.py (unit-tested); these hooks
# only wire it to pytest. Not TDD: only a real -m manual run exercises them.
# ---------------------------------------------------------------------------

_evidence = {}


def pytest_sessionstart(session):
    import json
    import os
    import subprocess

    from tests import manual_evidence

    if not manual_evidence.enabled(os.environ, session.config.option.markexpr or ""):
        return
    root = session.config.rootpath.parent  # pitch-mcp/ → the repository root
    # The commit and dirty flag when the run starts, not when it ends.
    head = subprocess.run(manual_evidence.head_command(root), capture_output=True, text=True, check=True)
    _evidence.update(root=root, start=json.loads(head.stdout), collector=manual_evidence.Collector())


def pytest_runtest_logreport(report):
    if "collector" in _evidence:
        _evidence["collector"].add(report)


def pytest_terminal_summary(terminalreporter):
    import json
    import os
    import subprocess
    import tempfile
    from pathlib import Path

    from tests import manual_evidence

    if "collector" not in _evidence:
        return
    with tempfile.TemporaryDirectory() as tmp:
        results = Path(tmp) / "results.json"
        results.write_text(json.dumps(_evidence["collector"].results()))
        argv = manual_evidence.record_command(
            _evidence["root"], results, _evidence["start"],
            versions=manual_evidence.versions(),
            input_device=os.environ.get("PITCH_MANUAL_INPUT_DEVICE"),
            notes=os.environ.get("PITCH_MANUAL_NOTES", ""),
        )
        done = subprocess.run(argv, capture_output=True, text=True)
    terminalreporter.section("release evidence (pitch-mic)")
    for line in (done.stdout + done.stderr).splitlines():
        terminalreporter.write_line(line)
