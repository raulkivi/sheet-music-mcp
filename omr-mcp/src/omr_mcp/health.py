"""The standard health report for omr-mcp: the engine's raw probe dict mapped to HealthCheck rows.

MCP-free so it can be imported and tested without the MCP stack; the engine keeps producing its
own raw dict, this module only shapes it (docs/conventions.md, Health Reports).
"""

from __future__ import annotations

from sheet_music_mcp_core.health import HealthCheck, health_report

__all__ = ["DOC", "build_health_report", "health_checks"]

DOC = "https://github.com/raulkivi/sheet-music-mcp/blob/main/omr-mcp/TROUBLESHOOTING.md"


def _version(entry: dict) -> str | None:
    # "unknown" means the probe could not find a version — same as absent.
    version = entry.get("version")
    return None if version in (None, "unknown") else version


def health_checks(raw: dict) -> list[HealthCheck]:
    """The engine's ``health_check()`` dict as the standard report rows, in row order."""
    checks = raw["checks"]
    rows: list[HealthCheck] = []

    oemer = checks["oemer"]
    if oemer["status"] == "ok":
        rows.append(HealthCheck("oemer", "ok", version=_version(oemer)))
    else:
        rows.append(
            HealthCheck(
                "oemer",
                "fail",
                hint=f"oemer is not installed: {oemer.get('error')}",
                fix_snippet="uv sync",
                doc_url=DOC,
            )
        )

    cache = checks["model_cache"]
    if cache["status"] == "ok":
        rows.append(HealthCheck("oemer model cache", "ok"))
    else:
        # The model downloads itself on first use, so a missing cache slows but does not
        # block: warn, and let the engine's note explain the one-time download.
        rows.append(HealthCheck("oemer model cache", "warn", hint=cache["note"], doc_url=DOC))

    audiveris = checks["audiveris"]
    if audiveris["status"] == "ok":
        # An ok row with no hint: the note in the raw dict is just confirmation the user
        # does not need.
        rows.append(HealthCheck("Audiveris (optional)", "ok", version=_version(audiveris)))
    elif audiveris["status"] == "not_installed":
        # Optional, and not installed is its expected default state — ok, but the user
        # should know what is missing and that it downloads on first use.
        rows.append(HealthCheck("Audiveris (optional)", "ok", hint=audiveris["note"]))
    else:
        rows.append(
            HealthCheck(
                "Audiveris (optional)",
                "warn",
                hint=audiveris.get("note") or audiveris.get("error"),
                doc_url=DOC,
            )
        )

    return rows


def build_health_report(raw: dict) -> dict:
    """``structuredContent`` for the health_check tool; the overall status is derived."""
    return health_report(health_checks(raw))
