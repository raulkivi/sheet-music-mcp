import os
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Per-user so another local user cannot pre-create the directory.
SYNTH_OUTPUT_DIR = f"/tmp/synth-mcp-{os.getuid()}"


def validate_musicxml(musicxml_str: str) -> tuple[bool, str]:
    """Validate a MusicXML string.

    Returns:
        (True, "") if valid, (False, error_message) if invalid.
    """
    if not musicxml_str or not musicxml_str.strip():
        return False, "MusicXML string is empty"

    try:
        root = ET.fromstring(musicxml_str)
    except ET.ParseError as e:
        return False, f"Invalid XML: {e}"

    tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if tag not in ("score-partwise", "score-timewise"):
        return False, (
            f"Not a MusicXML score: root element is <{tag}>, "
            "expected <score-partwise> or <score-timewise>"
        )

    return True, ""


def validate_tempo_factor(tempo_factor: float) -> tuple[bool, str]:
    """Validate a tempo factor value (must be in range 0.25–4.0).

    Returns:
        (True, "") if valid, (False, error_message) if invalid.
    """
    if not isinstance(tempo_factor, (int, float)):
        return False, f"tempo_factor must be a number, got {type(tempo_factor).__name__}"

    if tempo_factor < 0.25 or tempo_factor > 4.0:
        return False, (
            f"tempo_factor must be between 0.25 and 4.0, got {tempo_factor}. "
            "Values below 1.0 slow the tempo; values above 1.0 speed it up."
        )

    return True, ""


def generate_output_path(output_path: str | None) -> str:
    """Return output_path if provided, otherwise generate one in SYNTH_OUTPUT_DIR."""
    if output_path:
        return confine_output_path(output_path, (".mid", ".midi", ".wav"))

    output_dir = Path(SYNTH_OUTPUT_DIR)
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return str(output_dir / f"output_{timestamp}.wav")


def confine_output_path(output_path: str, suffixes: tuple[str, ...]) -> str:
    """Return *output_path* resolved inside the output root, or raise ValueError.

    The path is chosen by the model, so it must not escape SHEET_MUSIC_OUTPUT_ROOT
    (default: the server's working directory), carry another file type, or
    overwrite an existing file.
    """
    root = Path(os.environ.get("SHEET_MUSIC_OUTPUT_ROOT") or Path.cwd()).resolve()
    candidate = Path(output_path).expanduser()
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"output_path must be inside {root}")
    if resolved.suffix.lower() not in suffixes:
        raise ValueError(f"output_path must end with one of {', '.join(suffixes)}")
    if resolved.exists():
        raise ValueError(f"output_path already exists: {resolved}")
    return str(resolved)
