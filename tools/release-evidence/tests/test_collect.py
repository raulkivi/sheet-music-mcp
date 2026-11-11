"""Building a record from a run: pytest results, platform, privacy."""

import pytest

from release_evidence.collect import (
    PrivacyScrubber,
    build_evidence,
    current_platform,
    parse_versions,
    pytest_title,
    results_from_pytest,
)
from release_evidence.record import CheckResult, Environment
from release_evidence.suites import SUITES

from .helpers import SHA

NOW = "2026-11-11T10:00:00Z"


class TestPytestTitles:
    @pytest.mark.parametrize("name, title", [
        ("test_pm1_load_start_poll_stop", "PM1 load start poll stop"),
        ("test_pm12_x", "PM12 x"),
        ("test_pm1_case[usb]", "PM1 case [usb]"),
        ("test_load_start", "load start"),
    ])
    def test_title(self, name, title):
        assert pytest_title(name) == title

    def test_from_entries(self):
        entries = [
            {"name": "test_pm1_a", "outcome": "passed", "skipReason": None},
            {"name": "test_pm2_b", "outcome": "skipped", "skipReason": "no mic"},
            {"name": "test_pm3_c", "outcome": "failed", "skipReason": None},
        ]
        assert results_from_pytest(entries) == (
            CheckResult("PM1 a", "passed"),
            CheckResult("PM2 b", "skipped", "no mic"),
            CheckResult("PM3 c", "failed"),
        )

    def test_bad_outcome(self):
        with pytest.raises(ValueError):
            results_from_pytest([{"name": "test_pm1_a", "outcome": "error", "skipReason": None}])


class TestPlatform:
    @pytest.mark.parametrize("system, platform", [
        ("Linux", "linux"), ("Darwin", "macos"), ("Windows", "windows"), ("FreeBSD", "other"),
    ])
    def test_names(self, system, platform):
        assert current_platform(system) == platform


class TestVersions:
    def test_pairs(self):
        assert parse_versions(["pitch-mcp=0.4.0", "numpy=2.1.0"]) == {"pitch-mcp": "0.4.0", "numpy": "2.1.0"}

    @pytest.mark.parametrize("bad", ["pitch-mcp", "=1", "x="])
    def test_bad_pair(self, bad):
        with pytest.raises(ValueError):
            parse_versions([bad])


class TestPrivacy:
    def test_home_and_host_are_redacted(self):
        scrub = PrivacyScrubber(home="/home/alice", hostname="alice-laptop")
        assert scrub("failed at /home/alice/src on alice-laptop") == "failed at ~/src on <host>"

    def test_short_or_empty_values_are_not_redacted(self):
        scrub = PrivacyScrubber(home="/", hostname="")
        assert scrub("a/b") == "a/b"


class TestBuild:
    def _build(self, **overrides):
        args = dict(
            suite=SUITES["pitch-mic"],
            commit=SHA,
            dirty=False,
            versions={"pitch-mcp": "0.4.0"},
            tests=(CheckResult("PM1 a", "passed"),),
            notes="",
            input_device="usb",
            platform="linux",
            now=NOW,
            scrub=PrivacyScrubber(home="/home/alice", hostname="alice-laptop"),
        )
        args.update(overrides)
        return build_evidence(**args)

    def test_fields(self):
        evidence = self._build()
        assert evidence.suite == "pitch-mic"
        assert evidence.environment == Environment("linux", "usb")
        assert evidence.ran_at == NOW

    def test_strings_are_scrubbed(self):
        evidence = self._build(
            notes="sang in /home/alice/music",
            tests=(CheckResult("PM1 a", "skipped", "alice-laptop has no mic"),),
            versions={"pitch-mcp": "0.4.0+/home/alice"},
        )
        assert evidence.notes == "sang in ~/music"
        assert evidence.tests[0].skip_reason == "<host> has no mic"
        assert evidence.versions == {"pitch-mcp": "0.4.0+~"}

    def test_mic_suite_without_device_type_is_unspecified(self):
        assert self._build(input_device=None).environment.input_device == "unspecified"

    def test_host_suite_has_no_input_device(self):
        evidence = self._build(suite=SUITES["claude-desktop-host"], input_device="usb")
        assert evidence.environment.input_device is None

    def test_unknown_device_type_is_refused(self):
        with pytest.raises(ValueError):
            self._build(input_device="Alice's AirPods")

    def test_commit_is_lower_case(self):
        assert self._build(commit=SHA.upper()).commit == SHA
