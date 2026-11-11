"""Evidence for the manual real-microphone run (S6, R8 in docs/research/ui-and-sound-testing-plan.md).

With ``PITCH_MANUAL_EVIDENCE=1`` and ``-m manual``, tests/conftest.py collects each test's result
here and, at the end of the run, hands them to tools/release-evidence (its own uv project), which
writes the git note on the commit the run started on and prints the verdict and the push command.

Only package versions, test names, states and skip reasons leave this module. The input-device
*type* comes from ``PITCH_MANUAL_INPUT_DEVICE`` (built-in, usb, bluetooth, headset,
audio-interface, other), never a device name; notes from ``PITCH_MANUAL_NOTES``.
"""

import platform
from importlib import metadata
from pathlib import Path

TOOL = Path("tools") / "release-evidence"
_FAILED_PHASES = ("setup", "call", "teardown")


def enabled(env, markexpr: str) -> bool:
    return env.get("PITCH_MANUAL_EVIDENCE") == "1" and markexpr == "manual"


class Collector:
    """Each test's outcome from pytest's reports, in run order."""

    def __init__(self):
        self._results: dict[str, dict] = {}

    def add(self, report) -> None:
        name = report.nodeid.split("::")[-1]
        result = self._results.setdefault(name, {"name": name, "outcome": "passed", "skipReason": None})
        if result["outcome"] == "failed":
            return
        if report.outcome == "failed" and report.when in _FAILED_PHASES:
            result["outcome"], result["skipReason"] = "failed", None
        elif report.outcome == "skipped":
            result["outcome"], result["skipReason"] = "skipped", _skip_reason(report.longrepr)

    def results(self) -> list[dict]:
        return list(self._results.values())


def _skip_reason(longrepr) -> str | None:
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return str(longrepr[2]).removeprefix("Skipped: ") or None
    return None


def _uv(root: Path) -> list[str]:
    return ["uv", "run", "--project", str(root / TOOL), "--frozen", "--no-dev", "release-evidence", "--repo", str(root)]


def head_command(root: Path) -> list[str]:
    return [*_uv(root), "head"]


def record_command(root: Path, results: Path, start: dict, *, versions, input_device, notes) -> list[str]:
    argv = [*_uv(root), "record", "--suite", "pitch-mic", "--tests", str(results), "--commit", start["commit"]]
    if start["dirty"]:
        argv.append("--dirty")
    for name, version in versions.items():
        argv += ["--version", f"{name}={version}"]
    if input_device:
        argv += ["--input-device", input_device]
    return argv + ["--notes", notes]


def versions() -> dict[str, str]:
    found = {"pitch-mcp": metadata.version("pitch-mcp"), "python": platform.python_version()}
    for package in ("numpy", "sounddevice"):
        try:
            found[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            pass
    try:
        import sounddevice

        found["portaudio"] = sounddevice.get_portaudio_version()[1].split(",")[0].strip()
    except Exception:  # no PortAudio: the manual tests fail on their own and say so
        pass
    return found
