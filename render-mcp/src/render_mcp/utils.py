import os
import logging
import stat
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Per-user path; ensure_private_dir() rejects one that another user pre-created.
RENDER_OUTPUT_DIR = f"/tmp/render-mcp-{os.getuid()}"

VALID_IMAGE_FORMATS = ("png", "svg")
DPI_MIN = 72
DPI_MAX = 600
DPI_DEFAULT = 150
PAGE_DEFAULT = 1


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


def validate_image_format(fmt: str) -> tuple[bool, str]:
    """Validate an image format string.

    Returns:
        (True, "") if valid, (False, error_message) if invalid.
    """
    if fmt not in VALID_IMAGE_FORMATS:
        return False, (
            f"Unsupported image format {fmt!r}. "
            f"Valid formats: {', '.join(VALID_IMAGE_FORMATS)}"
        )
    return True, ""


def validate_dpi(dpi: int) -> tuple[bool, str]:
    """Validate DPI value (must be in range DPI_MIN–DPI_MAX).

    Returns:
        (True, "") if valid, (False, error_message) if invalid.
    """
    if not isinstance(dpi, int):
        return False, f"dpi must be an integer, got {type(dpi).__name__}"
    if dpi < DPI_MIN or dpi > DPI_MAX:
        return False, (
            f"dpi must be between {DPI_MIN} and {DPI_MAX}, got {dpi}"
        )
    return True, ""


def validate_page(page: int) -> tuple[bool, str]:
    """Validate a page number (must be a positive integer).

    Returns:
        (True, "") if valid, (False, error_message) if invalid.
    """
    if not isinstance(page, int):
        return False, f"page must be an integer, got {type(page).__name__}"
    if page < 1:
        return False, f"page must be at least 1, got {page}"
    return True, ""


def generate_pdf_path(output_path: str | None) -> str:
    """Return output_path if provided, otherwise generate one in RENDER_OUTPUT_DIR."""
    if output_path:
        return confine_output_path(output_path, (".pdf",))
    output_dir = ensure_private_dir(RENDER_OUTPUT_DIR)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return str(output_dir / f"score_{timestamp}.pdf")


def generate_image_path(output_path: str | None, fmt: str) -> str:
    """Return output_path if provided, otherwise generate one in RENDER_OUTPUT_DIR."""
    if output_path:
        return confine_output_path(output_path, (f".{fmt}",))
    output_dir = ensure_private_dir(RENDER_OUTPUT_DIR)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return str(output_dir / f"score_{timestamp}.{fmt}")


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
