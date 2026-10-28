"""Map ``engine.get_health_status()`` to the standard health report (sheet_music_mcp_core.health).

No MCP imports: this is engine-side, so the checks are buildable without the MCP stack.
"""

from __future__ import annotations

import importlib.metadata

from sheet_music_mcp_core.health import HealthCheck, health_report

__all__ = ["DOC", "build_health_report", "health_checks"]

DOC = "https://github.com/raulkivi/sheet-music-mcp/blob/main/render-mcp/TROUBLESHOOTING.md"


def _verovio_version() -> str | None:
    # The backend is imported from the distribution; if the metadata is missing there is
    # no version to show rather than a guess.
    try:
        return importlib.metadata.version("verovio")
    except importlib.metadata.PackageNotFoundError:
        return None


def health_checks(status: dict) -> list[HealthCheck]:
    """The Setup Doctor rows for ``status`` (the dict from ``engine.get_health_status()``).

    The overall status is never set here; ``health_report`` derives it.
    """
    backend = status["backend"]
    if backend is None:
        checks = [
            HealthCheck(
                "Rendering backend",
                "fail",
                hint="No rendering backend found; render_to_pdf and render_to_image fail.",
                fix_snippet="uv add verovio cairosvg",
                doc_url=DOC,
            )
        ]
    else:
        checks = [
            HealthCheck(
                "Rendering backend",
                "ok",
                version=_verovio_version() if backend == "verovio" else None,
            )
        ]

    # cairosvg only matters for the Verovio path; a MuseScore backend does not use it.
    if status["verovio_available"]:
        if status["cairosvg_available"]:
            checks.append(HealthCheck("cairosvg", "ok"))
        else:
            checks.append(
                HealthCheck(
                    "cairosvg",
                    "warn",
                    hint="PNG and PDF output via Verovio will fail; SVG still works.",
                    fix_snippet="sudo apt install libcairo2",
                    doc_url=DOC,
                )
            )
    return checks


def build_health_report(status: dict) -> dict:
    return health_report(health_checks(status))
