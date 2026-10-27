import os
import logging
import stat
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

# Moved to the core in Wave 2; re-exported so existing imports and tests keep working. It raises
# PathPolicyError, a ValueError, so callers catching ValueError are unchanged.
from sheet_music_mcp_core.paths import confine_output_path  # noqa: F401

logger = logging.getLogger(__name__)

# Per-user path; ensure_private_dir() rejects one that another user pre-created.
SYNTH_OUTPUT_DIR = f"/tmp/synth-mcp-{os.getuid()}"


def ensure_private_dir(path: str | Path) -> Path:
    """Create *path* as a private directory, or accept it only if it already is one.

    Raises PermissionError if the path is a symlink, is not a directory, is
    owned by another user, or is accessible to group or others.
    """
    p = Path(path)
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = os.lstat(p)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise PermissionError(f"{p} is not a real directory")
    if st.st_uid != os.getuid():
        raise PermissionError(f"{p} is owned by another user")
    if st.st_mode & 0o077:
        raise PermissionError(f"{p} is accessible to other users")
    return p


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

    output_dir = ensure_private_dir(SYNTH_OUTPUT_DIR)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return str(output_dir / f"output_{timestamp}.wav")
