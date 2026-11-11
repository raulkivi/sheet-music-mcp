"""The two manual suites, what each requires, and which package each one gates."""

from dataclasses import dataclass

from .checklist import load_rows


@dataclass(frozen=True)
class Suite:
    name: str
    required_tests: tuple[str, ...]
    run_hint: str
    input_device: bool = False  # whether the run records an input-device type


_PITCH_HINT = (
    "on a clean checkout of that commit, from pitch-mcp/: "
    "PITCH_MANUAL_EVIDENCE=1 PITCH_MANUAL_INPUT_DEVICE=<type> VIRTUAL_ENV= .venv/bin/pytest tests/ -v -m manual"
)
_HOST_HINT = (
    "on a clean checkout of that commit: "
    "uv run --project tools/release-evidence release-evidence host-checklist"
)

SUITES = {
    "pitch-mic": Suite(
        "pitch-mic",
        # pitch-mcp/tests/test_manual.py: test_pm1_* and test_pm2_*.
        required_tests=("PM1", "PM2"),
        run_hint=_PITCH_HINT,
        input_device=True,
    ),
    "claude-desktop-host": Suite(
        "claude-desktop-host",
        required_tests=tuple(row.id for row in load_rows() if row.required),
        run_hint=_HOST_HINT,
    ),
}

# Packages whose release needs a suite's evidence (publish.yml); the rest are not gated.
PACKAGE_SUITES = {"pitch-mcp": "pitch-mic", "render-mcp": "claude-desktop-host"}


def suite_for_package(package: str) -> Suite | None:
    name = PACKAGE_SUITES.get(package)
    return SUITES[name] if name else None
