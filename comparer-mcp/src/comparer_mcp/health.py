"""The health_check standard report for comparer-mcp.

Maps the engine's raw dict to the core HealthCheck rows (docs/conventions.md, Health Reports)
and returns sheet_music_mcp_core.health.health_report(...) as structuredContent. No MCP imports:
engines and servers import this, the Setup Doctor resource is created in server.py.
"""

from __future__ import annotations

from sheet_music_mcp_core.health import HealthCheck, health_report

__all__ = ["DOC", "build_health_report", "health_checks"]

DOC = "https://github.com/raulkivi/sheet-music-mcp/blob/main/comparer-mcp/TROUBLESHOOTING.md"


def health_checks(raw: dict) -> list[HealthCheck]:
    """One row per thing a user installs, in the order the Setup Doctor reads it.

    ``raw`` is the dict returned by engine.health_check(); rows the engine did not run
    (self-comparison skips itself when music21 is missing) are omitted, and unset fields
    stay None so HealthCheck.to_dict drops them.
    """
    checks: list[HealthCheck] = []
    music21 = raw["checks"]["music21"]
    if music21["ok"]:
        checks.append(HealthCheck("music21", "ok", version=music21.get("version")))
    else:
        checks.append(
            HealthCheck(
                "music21",
                "fail",
                hint=f"music21 is not installed: {music21['error']}",
                fix_snippet="uv sync",
                doc_url=DOC,
            )
        )
    if "self_compare" in raw["checks"]:
        self_compare = raw["checks"]["self_compare"]
        if self_compare["ok"]:
            checks.append(HealthCheck("Self-comparison", "ok"))
        else:
            checks.append(
                HealthCheck(
                    "Self-comparison",
                    "fail",
                    hint=f"Comparing a score with itself failed: {self_compare['error']}",
                    doc_url=DOC,
                )
            )
    return checks


def build_health_report(raw: dict) -> dict:
    """The standard report; the overall status is derived by the core, never set here."""
    return health_report(health_checks(raw))
