"""The manual run's evidence hook (S6): collecting results and building the record command.

The record itself (format, judge, git note) is tools/release-evidence's and tested there.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from . import manual_evidence as me

ROOT = Path("/repo")


def _report(nodeid, when, outcome, longrepr=None):
    return SimpleNamespace(nodeid=nodeid, when=when, outcome=outcome, longrepr=longrepr)


NODE = "tests/test_manual.py::TestRealMicrophoneLifecycle::test_pm1_load_start_poll_stop"


class TestEnabled:
    @pytest.mark.parametrize("env, markexpr, on", [
        ({"PITCH_MANUAL_EVIDENCE": "1"}, "manual", True),
        ({"PITCH_MANUAL_EVIDENCE": "1"}, "", False),
        ({"PITCH_MANUAL_EVIDENCE": "1"}, "integration", False),
        ({"PITCH_MANUAL_EVIDENCE": "0"}, "manual", False),
        ({}, "manual", False),
    ])
    def test_only_a_manual_run_with_the_variable(self, env, markexpr, on):
        assert me.enabled(env, markexpr) is on


class TestCollector:
    def test_passed(self):
        c = me.Collector()
        for when in ("setup", "call", "teardown"):
            c.add(_report(NODE, when, "passed"))
        assert c.results() == [{"name": "test_pm1_load_start_poll_stop", "outcome": "passed", "skipReason": None}]

    def test_failed_call(self):
        c = me.Collector()
        c.add(_report(NODE, "setup", "passed"))
        c.add(_report(NODE, "call", "failed"))
        c.add(_report(NODE, "teardown", "passed"))
        assert c.results()[0]["outcome"] == "failed"

    def test_failed_setup_or_teardown_fails_the_test(self):
        c = me.Collector()
        c.add(_report(NODE, "setup", "passed"))
        c.add(_report(NODE, "call", "passed"))
        c.add(_report(NODE, "teardown", "failed"))
        assert c.results()[0]["outcome"] == "failed"

    def test_skip_keeps_the_reason(self):
        c = me.Collector()
        c.add(_report(NODE, "setup", "skipped", ("tests/x.py", 3, "Skipped: no input device")))
        c.add(_report(NODE, "teardown", "passed"))
        assert c.results() == [{"name": "test_pm1_load_start_poll_stop", "outcome": "skipped", "skipReason": "no input device"}]

    def test_order_is_run_order(self):
        c = me.Collector()
        c.add(_report("a.py::test_pm2_b", "call", "passed"))
        c.add(_report("a.py::test_pm1_a", "call", "passed"))
        assert [r["name"] for r in c.results()] == ["test_pm2_b", "test_pm1_a"]


class TestCommands:
    def test_head_command(self):
        argv = me.head_command(ROOT)
        assert argv[:4] == ["uv", "run", "--project", str(ROOT / "tools" / "release-evidence")]
        assert argv[-3:] == ["--repo", str(ROOT), "head"]

    def test_record_command(self):
        argv = me.record_command(
            ROOT, Path("/tmp/r.json"), {"commit": "a" * 40, "dirty": True},
            versions={"pitch-mcp": "0.4.0"}, input_device="usb", notes="fine",
        )
        tail = argv[argv.index("record"):]
        assert tail == [
            "record", "--suite", "pitch-mic", "--tests", "/tmp/r.json", "--commit", "a" * 40, "--dirty",
            "--version", "pitch-mcp=0.4.0", "--input-device", "usb", "--notes", "fine",
        ]
        assert "--no-dev" in argv and "--frozen" in argv

    def test_clean_start_and_no_device(self):
        argv = me.record_command(ROOT, Path("/r.json"), {"commit": "a" * 40, "dirty": False},
                                 versions={}, input_device=None, notes="")
        assert "--dirty" not in argv and "--input-device" not in argv


def test_versions_name_packages_only():
    versions = me.versions()
    assert versions["pitch-mcp"]
    assert versions["python"].count(".") == 2
    assert set(versions) <= {"pitch-mcp", "python", "numpy", "sounddevice", "portaudio"}


def test_manual_tests_carry_the_required_ids():
    import inspect

    from . import test_manual

    names = [n for n, _ in inspect.getmembers(test_manual.TestRealMicrophoneLifecycle) if n.startswith("test_")]
    assert sorted(n.split("_")[1] for n in names) == ["pm1", "pm2"]
