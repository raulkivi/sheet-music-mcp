"""Map ``engine.health_check()``'s raw dict to the standard Setup Doctor report.

The text content of the health_check tool stays the raw JSON; only the structured
content changes. Engines stay mcp-free, so this module imports only the core's
mcp-free health helpers (docs/conventions.md: Health Reports).
"""

from __future__ import annotations

from sheet_music_mcp_core.health import HealthCheck, health_report

DOC = "https://github.com/raulkivi/sheet-music-mcp/blob/main/musicxml-abc-mcp/TROUBLESHOOTING.md"

__all__ = ["build_health_report", "health_checks"]


def health_checks(raw: dict) -> list[HealthCheck]:
    """One check per dependency the engine probes, in the engine's order."""
    checks: list[HealthCheck] = []
    music21 = raw["checks"]["music21"]
    if music21["ok"]:
        checks.append(HealthCheck("music21", "ok", version=music21.get("version")))
    else:
        checks.append(
            HealthCheck(
                "music21",
                "fail",
                hint=f"music21 is not installed: {music21.get('error')}",
                fix_snippet="uv sync",
                doc_url=DOC,
            )
        )
    # The engine omits the row entirely when music21 is missing, so the round trip never ran.
    if "round_trip" in raw["checks"]:
        round_trip = raw["checks"]["round_trip"]
        if round_trip["ok"]:
            checks.append(HealthCheck("ABC round trip", "ok"))
        else:
            checks.append(
                HealthCheck(
                    "ABC round trip",
                    "fail",
                    hint=f"MusicXML → ABC → MusicXML smoke test failed: {round_trip.get('error')}",
                    doc_url=DOC,
                )
            )
    return checks


def build_health_report(raw: dict) -> dict:
    """``structuredContent`` for health_check; the overall status is derived, never copied."""
    return health_report(health_checks(raw))
