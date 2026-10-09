"""Utility functions for OMR MCP server."""

import os
import base64
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image
import logging

logger = logging.getLogger(__name__)

SUPPORTED_IMAGE_FORMATS = {".png", ".jpg", ".jpeg"}
MAX_IMAGE_SIZE = 50 * 1024 * 1024  # 50MB

def validate_image_path(image_path: str) -> Tuple[bool, Optional[str]]:
    """
    Validate if the given path is a valid image file.
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    path = Path(image_path)
    
    if not path.exists():
        return False, f"File not found: {image_path}"
    
    if path.suffix.lower() not in SUPPORTED_IMAGE_FORMATS:
        return False, f"Unsupported format: {path.suffix}. Supported: {', '.join(SUPPORTED_IMAGE_FORMATS)}"
    
    if path.stat().st_size > MAX_IMAGE_SIZE:
        return False, f"File too large: {path.stat().st_size} bytes (max: {MAX_IMAGE_SIZE} bytes)"
    
    try:
        # Try to open the image to verify it's valid
        with Image.open(path) as img:
            img.verify()
        return True, None
    except Exception as e:
        return False, f"Invalid image file: {str(e)}"

def decode_base64_image(base64_data: str, output_path: Optional[str] = None) -> Tuple[bool, str]:
    """
    Decode base64 image data and save to a temporary file.
    
    Args:
        base64_data: Base64 encoded image data
        output_path: Optional path to save the decoded image
        
    Returns:
        Tuple of (success, file_path_or_error_message)
    """
    try:
        # Remove data URL prefix if present
        if base64_data.startswith("data:"):
            base64_data = base64_data.split(",", 1)[1]
        
        # Decode the base64 data
        image_bytes = base64.b64decode(base64_data)
        
        # Determine output path
        if output_path is None:
            import tempfile
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            output_path = temp_file.name
            temp_file.close()
        
        # Save the decoded image
        with open(output_path, "wb") as f:
            f.write(image_bytes)
        
        # Validate the saved image
        is_valid, error = validate_image_path(output_path)
        if not is_valid:
            Path(output_path).unlink(missing_ok=True)
            return False, error
        
        return True, output_path
        
    except Exception as e:
        logger.error(f"Failed to decode base64 image: {str(e)}")
        return False, f"Failed to decode base64 image: {str(e)}"

def format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"

def get_image_info(image_path: str) -> dict:
    """Get basic information about an image file."""
    try:
        path = Path(image_path)
        with Image.open(path) as img:
            return {
                "width": img.width,
                "height": img.height,
                "format": img.format,
                "mode": img.mode,
                "file_size": path.stat().st_size,
                "file_size_formatted": format_file_size(path.stat().st_size)
            }
    except Exception as e:
        logger.error(f"Failed to get image info for {image_path}: {str(e)}")
        return {"error": str(e)}


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
