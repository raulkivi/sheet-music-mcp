"""The standard Setup Doctor report for pitch-mcp, mapped from ``engine.health_check()``.

MCP-free: only ``sheet_music_mcp_core.health`` (no ``mcp`` import), so the engine-side
tests can exercise the mapping without the MCP stack. ``server.py`` keeps the tool's text
content byte-identical (``json.dumps(raw, indent=2)``) and adds ``build_health_report(raw)``
as ``structuredContent`` (docs/conventions.md, Health Reports).
"""

from __future__ import annotations

from sheet_music_mcp_core.health import HealthCheck, health_report

__all__ = ["build_health_report", "health_checks"]

DOC = "https://github.com/raulkivi/sheet-music-mcp/blob/main/pitch-mcp/TROUBLESHOOTING.md"

LIBROSA = "librosa (offline analysis)"
PORTAUDIO = "Server microphone (PortAudio)"
MICROPHONE = "Microphone"

# The engine uses these sentinels when a probe fails or a backend has no __version__.
_UNSET = ("unavailable", "unknown")


def _version(value: str) -> str | None:
    return None if value in _UNSET else value


def health_checks(raw: dict) -> list[HealthCheck]:
    """One check per dependency the user installs, in the order the Setup Doctor shows them."""
    checks: list[HealthCheck] = []

    offline = raw["offline_analysis"]
    if offline["available"]:
        checks.append(HealthCheck(LIBROSA, "ok", version=_version(offline["librosa_version"])))
    else:
        checks.append(
            HealthCheck(
                LIBROSA,
                "fail",
                hint="librosa is not installed; analyze_recording fails.",
                fix_snippet="uv sync",
                doc_url=DOC,
            )
        )

    realtime = raw["realtime_monitoring"]
    if realtime["available"]:
        checks.append(HealthCheck(PORTAUDIO, "ok", version=_version(realtime["sounddevice_version"])))
    else:
        if realtime["sounddevice_available"]:
            cause, fix = "libportaudio2 is missing", "sudo apt install libportaudio2"
        else:
            cause, fix = "sounddevice is not installed", "uv sync"
        checks.append(
            HealthCheck(
                PORTAUDIO,
                "warn",
                hint=(
                    f"{cause}; start_monitoring with the server microphone fails. "
                    "The Practice Coach can still use the browser microphone."
                ),
                fix_snippet=fix,
                doc_url=DOC,
            )
        )

    # Only meaningful once PortAudio works; without it there is no device query at all.
    if realtime["available"]:
        if realtime["microphone_detected"]:
            checks.append(HealthCheck(MICROPHONE, "ok"))
        else:
            checks.append(
                HealthCheck(
                    MICROPHONE,
                    "warn",
                    hint="No input device found on the server; use the browser microphone instead.",
                    doc_url=DOC,
                )
            )

    return checks


def build_health_report(raw: dict) -> dict:
    """The standard ``health_report`` over ``health_checks(raw)``; the overall status is derived."""
    return health_report(health_checks(raw))
