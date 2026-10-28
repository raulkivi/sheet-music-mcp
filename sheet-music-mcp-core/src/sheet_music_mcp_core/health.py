"""The standard ``health_check`` report every server returns, and the Setup Doctor app showing it.

A server builds one ``HealthCheck`` per dependency and returns ``health_report(checks)`` as the
tool's ``structuredContent``, with ``output_schema=HEALTH_OUTPUT_SCHEMA`` and the tool linked to
``setup_doctor_resource("<uri name>")`` (mcp-apps-ux-proposal.md §5.7). The text ``content`` stays
as it is.

Mapping a server's existing health output to checks:

- One check per thing a user installs or configures: a package, a system library, a file or
  environment variable, a smoke test. ``name`` is what the user recognises ("music21",
  "Soundfont"), not an internal key.
- ``status``: ``fail`` when the server's main tools cannot work without it; ``warn`` when an
  optional feature is off or the first use will be slow but the main tools work; ``ok`` when it
  works, or is optional and in its expected default state.
- ``version``: the dependency's version when known; sentinels such as "unknown" become None.
- ``hint``: one sentence for a ``warn``/``fail`` check saying what is wrong and what stops
  working, with the old error text when there was one. An ``ok`` check has one only when the
  user must know something (a download on first use).
- ``fix_snippet``: only text to paste verbatim, a shell command or a client-config fragment;
  prose belongs in ``hint``.
- ``doc_url``: the server's TROUBLESHOOTING.md for ``warn``/``fail`` checks.
- The overall status is never set by the server; ``health_report`` derives it (any ``fail`` is
  ``not_ready``, else any ``warn`` is ``degraded``, else ``ready``).

Each server's current output, as checks (docs/conventions.md, Health Reports, has the hints and
fix snippets):

========  ==========================================  ===========================================
server    source                                      checks (status when not ok)
========  ==========================================  ===========================================
omr       ``omr_engine.health_check()["checks"]``     oemer (fail), oemer model cache (warn),
                                                      Audiveris (optional) (``not_installed`` = ok)
render    ``engine.get_health_status()``              Rendering backend (fail), cairosvg (warn,
                                                      only when Verovio is available)
synth     probes in ``server.py`` ``health_check``    Soundfont (fail), FluidSynth (fail),
                                                      music21 (fail)
abc       ``engine.health_check()["checks"]``         music21 (fail), ABC round trip (fail)
comparer  ``engine.health_check()["checks"]``         music21 (fail), Self-comparison (fail)
pitch     ``engine.health_check()``                   librosa (offline analysis) (fail), Server
                                                      microphone (PortAudio) (warn), Microphone
                                                      (warn, only when PortAudio works)
========  ==========================================  ===========================================

No MCP imports: engines may build checks. ``setup_doctor_resource`` imports ``ui`` (and so
``mcp``) only when called, from ``server.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Iterable, Literal

if TYPE_CHECKING:
    from .ui import UiResource

__all__ = [
    "CHECK_STATUSES",
    "HEALTH_OUTPUT_SCHEMA",
    "REPORT_STATUSES",
    "CheckStatus",
    "HealthCheck",
    "ReportStatus",
    "health_report",
    "setup_doctor_resource",
]

CheckStatus = Literal["ok", "warn", "fail"]
ReportStatus = Literal["ready", "degraded", "not_ready"]

CHECK_STATUSES: tuple[str, ...] = ("ok", "warn", "fail")
REPORT_STATUSES: tuple[str, ...] = ("ready", "degraded", "not_ready")

SETUP_DOCTOR_ASSET = "setup-doctor.html"

# The <server> part of ui://<server>/...: a short lowercase name such as "synth" or "abc".
_SERVER_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


@dataclass(frozen=True)
class HealthCheck:
    """One row of the Setup Doctor: a dependency, whether it works, and how to fix it."""

    name: str
    status: CheckStatus
    version: str | None = None
    hint: str | None = None
    fix_snippet: str | None = None
    doc_url: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("HealthCheck name must be a non-empty string")
        if self.status not in CHECK_STATUSES:
            raise ValueError(f"HealthCheck status must be one of {', '.join(CHECK_STATUSES)}, got {self.status!r}")

    def to_dict(self) -> dict:
        """The check as JSON, without the fields that are None."""
        return {f.name: value for f in fields(self) if (value := getattr(self, f.name)) is not None}


def health_report(checks: Iterable[HealthCheck]) -> dict:
    """``{"status": "ready"|"degraded"|"not_ready", "checks": [...]}`` in the order given.

    Raises ValueError for two checks with the same name (the Setup Doctor keys rows by name) and
    TypeError for anything that is not a ``HealthCheck``.
    """
    checks = list(checks)
    seen: set[str] = set()
    for check in checks:
        if not isinstance(check, HealthCheck):
            raise TypeError(f"health_report takes HealthCheck objects, got {type(check).__name__}")
        if check.name in seen:
            raise ValueError(f"Two health checks are named {check.name!r}")
        seen.add(check.name)
    statuses = {check.status for check in checks}
    if "fail" in statuses:
        status = "not_ready"
    elif "warn" in statuses:
        status = "degraded"
    else:
        status = "ready"
    return {"status": status, "checks": [check.to_dict() for check in checks]}


_OPTIONAL_TEXT = {"type": "string"}

HEALTH_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": list(REPORT_STATUSES)},
        "checks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "status": {"type": "string", "enum": list(CHECK_STATUSES)},
                    "version": _OPTIONAL_TEXT,
                    "hint": _OPTIONAL_TEXT,
                    "fix_snippet": _OPTIONAL_TEXT,
                    "doc_url": {"type": "string", "format": "uri"},
                },
                "required": ["name", "status"],
                # The Setup Doctor renders these fields only; anything else belongs in hint.
                "additionalProperties": False,
            },
        },
    },
    "required": ["status", "checks"],
}


def setup_doctor_resource(server: str) -> UiResource:
    """The Setup Doctor app for ``server``: ``ui://<server>/setup-doctor``, ``setup-doctor.html``.

    ``server`` is the name the server's other ``ui://`` URIs use ("synth", "abc"). The app asks
    only for ``clipboardWrite``, for the [Copy] button beside each fix snippet.
    """
    if not isinstance(server, str) or not _SERVER_NAME.fullmatch(server):
        raise ValueError(f"server must be a short lowercase name such as 'synth', got {server!r}")
    # Imported here so engines can import this module without mcp.
    from .ui import UiResource

    return UiResource(
        f"ui://{server}/setup-doctor",
        SETUP_DOCTOR_ASSET,
        "Setup Doctor",
        "Checks this server's dependencies and shows one fix, ready to copy, for each problem.",
        permissions={"clipboardWrite": {}},
    )
