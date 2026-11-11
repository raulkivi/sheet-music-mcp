"""Shared builders for the tests: a valid record and a throwaway git repository."""

import subprocess
from pathlib import Path

from release_evidence.record import Environment, Evidence, CheckResult

SHA = "a" * 40
OTHER_SHA = "b" * 40


def evidence(**overrides) -> Evidence:
    fields = dict(
        suite="pitch-mic",
        commit=SHA,
        dirty=False,
        versions={"pitch-mcp": "0.4.0", "python": "3.13.1"},
        environment=Environment(platform="linux", input_device="usb"),
        tests=(
            CheckResult("PM1 load start poll stop", "passed"),
            CheckResult("PM2 tempo bpm override is accepted", "passed"),
        ),
        ran_at="2026-11-11T10:00:00Z",
        notes="",
    )
    fields.update(overrides)
    return Evidence(**fields)


def record_dict(**overrides) -> dict:
    data = {
        "schema": 1,
        "suite": "pitch-mic",
        "commit": SHA,
        "dirty": False,
        "versions": {"pitch-mcp": "0.4.0"},
        "environment": {"platform": "linux", "inputDevice": "usb"},
        "tests": [{"title": "PM1 load", "state": "passed", "skipReason": None}],
        "ranAt": "2026-11-11T10:00:00Z",
        "notes": "",
    }
    data.update(overrides)
    return data


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def make_repo(path: Path) -> Path:
    """A repository with one commit and a local identity (no global config needed)."""
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "test@example.invalid")
    git(path, "config", "user.name", "Test")
    git(path, "config", "commit.gpgsign", "false")
    (path / ".gitignore").write_text("ignored/\n")
    (path / "README").write_text("x\n")
    git(path, "add", ".")
    git(path, "commit", "-q", "-m", "first")
    return path
