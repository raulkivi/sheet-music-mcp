"""Render one part of a score to a WAV with synth-mcp, in synth-mcp's own venv (test support).

The servers never share a venv (root CLAUDE.md), so the round trip runs synth-mcp's interpreter on
``synth-mcp/tests/render_part.py`` in a subprocess: an argument list, never a shell.
"""

import os
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

SYNTH_DIR = Path(__file__).resolve().parents[2] / "synth-mcp"


class RenderFailed(RuntimeError):
    """synth-mcp could not render the part; the message is its stderr."""


def _python(synth_dir: Path) -> Path:
    return synth_dir / ".venv" / "bin" / "python"


def _script(synth_dir: Path) -> Path:
    return synth_dir / "tests" / "render_part.py"


def unavailable_reason(
    environ: Mapping[str, str] = os.environ, synth_dir: Path = SYNTH_DIR
) -> str | None:
    """Why the round trip cannot run here, or None when it can."""
    if not _python(synth_dir).is_file() or not _script(synth_dir).is_file():
        return f"no synth-mcp venv at {synth_dir} (run: cd synth-mcp && uv sync --frozen --extra dev)"
    soundfont = environ.get("SYNTH_SOUNDFONT_PATH", "")
    if not soundfont:
        return "SYNTH_SOUNDFONT_PATH not set (synth-mcp needs a soundfont to render)"
    if not Path(soundfont).is_file():
        return f"SYNTH_SOUNDFONT_PATH points to a missing file: {soundfont}"
    return None


def render_part(
    score: Path,
    part: str,
    output: Path,
    *,
    soundfont: str,
    timbre: str = "score",
    synth_dir: Path = SYNTH_DIR,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> Path:
    """Render ``part`` of ``score`` to ``output`` with synth-mcp; return ``output``."""
    args = [
        str(_python(synth_dir)),
        "-I",
        str(_script(synth_dir)),
        str(score),
        str(output),
        "--part",
        part,
        "--timbre",
        timbre,
    ]
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env["SYNTH_SOUNDFONT_PATH"] = soundfont
    result = run(args, cwd=str(synth_dir), env=env, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RenderFailed(result.stderr.strip() or f"render_part exited {result.returncode}")
    return output
