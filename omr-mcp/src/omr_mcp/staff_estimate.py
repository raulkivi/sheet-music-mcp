"""A cheap staff count straight from the image, without running an OMR engine.

The Recognition Review compares it with ``staves_detected`` to warn when oemer flattened a choir
score (proposal 5.5, AC-O3). It counts staves on the page, not parts: a page of four one-staff
systems counts 4 as well, so it can only hint at a flattened score, never prove one.
"""

from __future__ import annotations

import logging
import os
from statistics import median

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# A staff line is a dark row reaching across this share of the page. Low enough for staves that
# do not span the full width, high enough to ignore note beams, text and ledger lines.
_MIN_LINE_COVERAGE = 0.35
_DARK = 128
# A gap this many times the usual line spacing separates two staves.
_STAFF_GAP_FACTOR = 2.5
# Fewer detected lines than this is not a staff (a lone rule, an underline).
_MIN_LINES_PER_STAFF = 3


def estimate_staves(image_path: str | os.PathLike) -> int | None:
    """Number of staves on the page; 0 if there are none, None if the image cannot be read."""
    try:
        with Image.open(image_path) as image:
            grey = _to_grey(image)
    except (OSError, ValueError, Image.DecompressionBombError) as e:
        logger.warning("Cannot count staves in %s: %s", image_path, e)
        return None
    return _count_staves(_line_centres(grey))


def _to_grey(image: Image.Image) -> np.ndarray:
    if image.mode in ("RGBA", "LA", "P"):
        # Transparent pixels are white paper, not black.
        rgba = image.convert("RGBA")
        paper = Image.new("RGBA", rgba.size, "white")
        image = Image.alpha_composite(paper, rgba)
    return np.asarray(image.convert("L"))


def _line_centres(grey: np.ndarray) -> list[float]:
    """Vertical centre of each horizontal dark band spanning enough of the width."""
    coverage = (grey < _DARK).mean(axis=1)
    rows = np.flatnonzero(coverage >= _MIN_LINE_COVERAGE)
    if rows.size == 0:
        return []
    bands = np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)
    return [float(band.mean()) for band in bands]


def _count_staves(centres: list[float]) -> int:
    if len(centres) < _MIN_LINES_PER_STAFF:
        return 0
    gaps = np.diff(centres)
    # Most gaps lie inside a staff, so the median is the line spacing.
    limit = median(gaps) * _STAFF_GAP_FACTOR
    sizes = np.diff([0, *(np.flatnonzero(gaps > limit) + 1), len(centres)])
    return int(sum(1 for size in sizes if size >= _MIN_LINES_PER_STAFF))
