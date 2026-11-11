"""Which suite gates which package, and what each suite requires."""

import pytest

from release_evidence.checklist import load_rows
from release_evidence.suites import SUITES, suite_for_package


class TestSuiteForPackage:
    def test_pitch_mcp_needs_the_microphone_run(self):
        assert suite_for_package("pitch-mcp").name == "pitch-mic"

    def test_render_mcp_needs_the_claude_desktop_checklist(self):
        assert suite_for_package("render-mcp").name == "claude-desktop-host"

    @pytest.mark.parametrize("package", [
        "omr-mcp", "synth-mcp", "musicxml-abc-mcp", "comparer-mcp", "sheet-music-mcp-core", "unknown",
    ])
    def test_other_packages_are_not_gated(self, package):
        assert suite_for_package(package) is None


class TestRequiredTests:
    def test_pitch_mic_requires_the_two_manual_tests(self):
        assert SUITES["pitch-mic"].required_tests == ("PM1", "PM2")

    def test_host_suite_requires_every_required_checklist_row(self):
        rows = [row.id for row in load_rows() if row.required]
        assert SUITES["claude-desktop-host"].required_tests == tuple(rows)

    def test_only_the_host_run_takes_no_input_device(self):
        assert SUITES["pitch-mic"].input_device
        assert not SUITES["claude-desktop-host"].input_device

    def test_each_suite_tells_the_owner_how_to_run_it(self):
        assert "PITCH_MANUAL_EVIDENCE=1" in SUITES["pitch-mic"].run_hint
        assert "host-checklist" in SUITES["claude-desktop-host"].run_hint
