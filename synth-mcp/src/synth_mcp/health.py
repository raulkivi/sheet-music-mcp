"""The synth-mcp health probes, the human-readable report and the standard Setup Doctor mapping.

No mcp imports: ``probe()`` imports ``fluidsynth`` and ``music21`` at call time (not at module
import time) because tests inject fake or missing modules through sys.modules and
builtins.__import__. ``health_text`` is the text the server sent before the standard report
existed, unchanged.
"""

from __future__ import annotations

import importlib.metadata
import os
from dataclasses import dataclass

from sheet_music_mcp_core.health import HealthCheck, health_report

__all__ = ["DOC", "Probe", "build_health_report", "health_checks", "health_text", "probe"]

DOC = "https://github.com/raulkivi/sheet-music-mcp/blob/main/synth-mcp/TROUBLESHOOTING.md"


@dataclass(frozen=True)
class Probe:
    """What health_check found: the soundfont setting and whether each import works."""

    soundfont_path: str
    soundfont_ok: bool
    fluidsynth_error: str | None
    music21_version: str | None
    music21_error: str | None


def probe() -> Probe:
    soundfont_path = os.environ.get("SYNTH_SOUNDFONT_PATH", "")
    soundfont_ok = bool(soundfont_path) and os.path.exists(soundfont_path)

    # Imported here, not at module load: tests replace the module in sys.modules or make
    # builtins.__import__ raise, and the server must report the current state, not the one at
    # startup.
    fluidsynth_error = None
    try:
        import fluidsynth  # noqa: F401
    except (ImportError, OSError) as e:
        fluidsynth_error = str(e)

    music21_error = None
    music21_version = None
    try:
        import music21
    except ImportError as e:
        music21_error = str(e)
    else:
        music21_version = music21.__version__

    return Probe(soundfont_path, soundfont_ok, fluidsynth_error, music21_version, music21_error)


def health_text(p: Probe) -> str:
    lines = ["synth-mcp health check\n" + "=" * 22]

    # Soundfont
    if not p.soundfont_path:
        sf_status = "MISSING — SYNTH_SOUNDFONT_PATH is not set"
        sf_ok = False
    elif not p.soundfont_ok:
        sf_status = f"MISSING — file not found at {p.soundfont_path!r}"
        sf_ok = False
    else:
        sf_status = f"OK — {p.soundfont_path}"
        sf_ok = True
    lines.append(f"Soundfont:    {sf_status}")

    if not sf_ok:
        lines.append(
            "\n  To fix: download an SF2 soundfont, e.g. TimGM6mb.sf2 from\n"
            "  https://sourceforge.net/projects/timidity/files/\n"
            "  Then add to your LLM client config:\n"
            '    "env": {"SYNTH_SOUNDFONT_PATH": "/path/to/soundfont.sf2"}'
        )

    # FluidSynth Python binding
    if p.fluidsynth_error is not None:
        lines.append(f"FluidSynth:   MISSING — {p.fluidsynth_error}")
    else:
        lines.append("FluidSynth:   OK")

    # music21
    if p.music21_error is not None:
        lines.append(f"music21:      MISSING — {p.music21_error}")
    else:
        lines.append("music21:      OK")

    # Overall status
    all_ok = sf_ok and p.fluidsynth_error is None and p.music21_error is None
    status = "READY" if all_ok else "NOT READY"
    lines.append(f"\nOverall:      {status}")
    if not all_ok:
        lines.append(
            "Fix the issues above, then restart the server and run health_check again."
        )

    return "\n".join(lines)


def health_checks(p: Probe) -> list[HealthCheck]:
    """The probe as the Setup Doctor's rows (docs/conventions.md, Health Reports)."""
    checks: list[HealthCheck] = []

    if p.soundfont_ok:
        checks.append(HealthCheck("Soundfont", "ok"))
    else:
        if p.soundfont_path:
            hint = f"No soundfont file at {p.soundfont_path!r}."
        else:
            hint = (
                "SYNTH_SOUNDFONT_PATH is not set; download an SF2 soundfont such as "
                "TimGM6mb.sf2 (https://sourceforge.net/projects/timidity/files/)."
            )
        checks.append(
            HealthCheck(
                "Soundfont",
                "fail",
                hint=hint,
                fix_snippet='"env": {"SYNTH_SOUNDFONT_PATH": "/path/to/TimGM6mb.sf2"}',
                doc_url=DOC,
            )
        )

    if p.fluidsynth_error is None:
        # The binding imported, but the distribution may still be absent (imported some other way).
        try:
            version = importlib.metadata.version("pyfluidsynth")
        except importlib.metadata.PackageNotFoundError:
            version = None
        checks.append(HealthCheck("FluidSynth", "ok", version=version))
    else:
        checks.append(
            HealthCheck(
                "FluidSynth",
                "fail",
                hint=f"FluidSynth could not be loaded: {p.fluidsynth_error}",
                fix_snippet="sudo apt install libfluidsynth-dev",
                doc_url=DOC,
            )
        )

    if p.music21_error is None:
        checks.append(HealthCheck("music21", "ok", version=p.music21_version))
    else:
        checks.append(
            HealthCheck(
                "music21",
                "fail",
                hint=f"music21 is not installed: {p.music21_error}",
                fix_snippet="uv sync",
                doc_url=DOC,
            )
        )

    return checks


def build_health_report(p: Probe) -> dict:
    """The standard report: health_check's rows, overall status derived by the core."""
    return health_report(health_checks(p))
