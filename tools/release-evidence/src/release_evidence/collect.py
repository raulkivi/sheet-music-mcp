"""Building a record from a run: pytest results to titles, the platform, and privacy scrubbing."""

import os
import platform as _platform
import re
import socket
from datetime import datetime, timezone
from typing import Callable, Iterable

from .record import INPUT_DEVICES, STATES, CheckResult, Environment, Evidence
from .suites import Suite

_PYTEST_ID = re.compile(r"^test_([a-z]+\d+)_(.+)$")
_PLATFORMS = {"linux": "linux", "darwin": "macos", "windows": "windows"}


def pytest_title(name: str) -> str:
    """``test_pm1_load_start[usb]`` → ``PM1 load start [usb]``: the stable id first."""
    base, _, params = name.partition("[")
    match = _PYTEST_ID.match(base)
    if match:
        words = f"{match.group(1).upper()} {match.group(2).replace('_', ' ')}"
    else:
        words = base.removeprefix("test_").replace("_", " ")
    return f"{words} [{params}" if params else words


def results_from_pytest(entries: Iterable[dict]) -> tuple[CheckResult, ...]:
    """Results written by pitch-mcp's conftest: ``name``, ``outcome``, ``skipReason``."""
    results = []
    for entry in entries:
        if entry.get("outcome") not in STATES or not isinstance(entry.get("name"), str):
            raise ValueError(f"Not a pytest result: {entry!r}")
        results.append(CheckResult(pytest_title(entry["name"]), entry["outcome"], entry.get("skipReason")))
    return tuple(results)


def current_platform(system: str | None = None) -> str:
    return _PLATFORMS.get((system or _platform.system()).lower(), "other")


def parse_versions(pairs: Iterable[str]) -> dict[str, str]:
    versions = {}
    for pair in pairs:
        name, sep, version = pair.partition("=")
        if not sep or not name.strip() or not version.strip():
            raise ValueError(f"Version {pair!r} must look like name=1.2.3.")
        versions[name.strip()] = version.strip()
    return versions


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class PrivacyScrubber:
    """Replaces the home directory with ``~`` and the host name with ``<host>`` in free text.

    The record's closed fields cannot hold either; this covers notes, skip reasons and versions.
    """

    def __init__(self, home: str | None = None, hostname: str | None = None):
        self.home = os.path.expanduser("~") if home is None else home
        self.hostname = socket.gethostname() if hostname is None else hostname

    def __call__(self, text: str) -> str:
        if len(self.home) > 1:
            text = text.replace(self.home, "~")
        if len(self.hostname) > 2:
            text = text.replace(self.hostname, "<host>")
        return text


def build_evidence(
    *,
    suite: Suite,
    commit: str,
    dirty: bool,
    versions: dict[str, str],
    tests: Iterable[CheckResult],
    notes: str,
    input_device: str | None,
    platform: str | None = None,
    now: str | None = None,
    scrub: Callable[[str], str] | None = None,
) -> Evidence:
    scrub = scrub or PrivacyScrubber()
    if suite.input_device:
        device = input_device or "unspecified"
        if device not in INPUT_DEVICES:
            raise ValueError(f"Input device type must be one of {', '.join(INPUT_DEVICES)} (a type, never a name).")
    else:
        device = None
    return Evidence(
        suite=suite.name,
        commit=commit.lower(),
        dirty=dirty,
        versions={scrub(k): scrub(v) for k, v in versions.items()},
        environment=Environment(platform or current_platform(), device),
        tests=tuple(
            CheckResult(scrub(t.title), t.state, None if t.skip_reason is None else scrub(t.skip_reason))
            for t in tests
        ),
        ran_at=now or utc_now(),
        notes=scrub(notes),
    )
