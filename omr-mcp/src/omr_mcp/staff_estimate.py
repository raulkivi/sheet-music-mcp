"""A cheap count of staves per system straight from the image, without running an OMR engine.

The Recognition Review compares it with ``staves_detected`` to warn when oemer flattened a choir
score (proposal 5.5, AC-O3). An SATB page counts 4 however many systems it holds, and a melody page
counts 1: engraved scores join the staves of one system with a vertical system line at their left
end, while one-staff systems stand alone. It counts staves, not parts (an SA/TB short score counts
2, a piano part 2), so it can only hint at a flattened score, never prove one.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from statistics import median

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# A staff line is a dark row reaching across this share of the page. Low enough for staves that
# do not span the full width, high enough to ignore note beams, text and ledger lines.
_MIN_LINE_COVERAGE = 0.35
# Ink is anything this share of the way from the paper's shade towards the darkest ink. Closer to
# the paper than to the ink, so one-pixel lines smoothed to gray by scaling or rotation still count.
_INK_SHARE = 0.25
# Percentile of the gray values taken as the darkest ink (a page is mostly paper: the median).
_INK_PERCENTILE = 1
# A gap this many times the usual line spacing separates two staves.
_STAFF_GAP_FACTOR = 2.5
# Fewer detected lines than this is not a staff (a lone rule, an underline).
_MIN_LINES_PER_STAFF = 3
# Share of the staff's width a typical line inks; notes sit on the lines and do not break them.
_MIN_LINE_SOLIDITY = 0.8
# Each gap inside a staff lies within this share of a whole number of line spacings.
_SPACING_TOLERANCE = 0.3
# A system line covers nearly every row between two staves; stems, slurs and lyrics do not.
_MIN_JOIN_COVERAGE = 0.9
# Columns this many line spacings beyond the shorter staff's ends still count (brackets, braces),
# so a page frame or scan shadow in the margin cannot join staves.
_JOIN_MARGIN_SPACINGS = 2
# Skew search in degrees: a scanned or photographed page a little off square, not a sideways one.
_MAX_SKEW = 3.0
_COARSE_STEP = 0.25
_FINE_STEP = 0.025


@dataclass(frozen=True)
class _Staff:
    first_row: int  # top row of the top line
    last_row: int  # bottom row of the bottom line
    left: int
    right: int


def estimate_staves(image_path: str | os.PathLike) -> int | None:
    """Staves in the largest system on the page; 0 if there are none, None if the image cannot be read."""
    try:
        with Image.open(image_path) as image:
            gray = _to_gray(image)
    except (OSError, ValueError, Image.DecompressionBombError) as e:
        logger.warning("Cannot count staves in %s: %s", image_path, e)
        return None
    dark = _deskewed(_ink(gray))
    staves, spacing = _staves(dark)
    return _largest_system(dark, staves, spacing)


def _to_gray(image: Image.Image) -> np.ndarray:
    if image.mode in ("RGBA", "LA", "P"):
        # Transparent pixels are white paper, not black.
        rgba = image.convert("RGBA")
        paper = Image.new("RGBA", rgba.size, "white")
        image = Image.alpha_composite(paper, rgba)
    return np.asarray(image.convert("L"))


def _ink(gray: np.ndarray) -> np.ndarray:
    """Pixels darker than the paper by a quarter of the paper-to-ink contrast."""
    paper = float(np.median(gray))
    ink = float(np.percentile(gray, _INK_PERCENTILE))
    return gray < paper - (paper - ink) * _INK_SHARE


def _deskewed(dark: np.ndarray) -> np.ndarray:
    """``dark`` turned so the staff lines run level; a level page comes back unchanged.

    A line tilted by even 0.2 degrees spreads over several rows of a 1200 px page and no longer
    reaches the coverage of one row, so a scan a little off square would show no staves at all.
    """
    ys, xs = np.nonzero(dark)
    if ys.size == 0:
        return dark
    slope = _skew_slope(ys, xs)
    if slope == 0.0:
        return dark
    # Small-angle rotation of the dark pixels' coordinates; vertical lines turn with the rows.
    new_ys = np.rint(ys + xs * slope).astype(np.intp)
    new_xs = np.rint(xs - ys * slope).astype(np.intp)
    new_ys -= new_ys.min()
    new_xs -= new_xs.min()
    turned = np.zeros((new_ys.max() + 1, new_xs.max() + 1), dtype=bool)
    turned[new_ys, new_xs] = True
    return turned


def _skew_slope(ys: np.ndarray, xs: np.ndarray) -> float:
    """tan of the turn that makes the row profile sharpest: staff lines pile into single rows."""

    def sharpness(slope: float) -> float:
        rows = np.rint(ys + xs * slope).astype(np.intp)
        counts = np.bincount(rows - rows.min()).astype(np.float64)
        return float(np.dot(counts, counts))

    def best(candidates: np.ndarray, current: float) -> float:
        chosen, score = current, sharpness(current)
        for slope in candidates:
            value = sharpness(float(slope))
            if value > score:
                chosen, score = float(slope), value
        return chosen

    coarse = best(np.tan(np.radians(np.arange(-_MAX_SKEW, _MAX_SKEW + 1e-9, _COARSE_STEP))), 0.0)
    around = np.degrees(np.arctan(coarse))
    fine = np.arange(around - _COARSE_STEP, around + _COARSE_STEP + 1e-9, _FINE_STEP)
    return best(np.tan(np.radians(fine)), coarse)


def _line_bands(dark: np.ndarray) -> list[np.ndarray]:
    """Rows of each horizontal dark band spanning enough of the width, top to bottom."""
    rows = np.flatnonzero(dark.mean(axis=1) >= _MIN_LINE_COVERAGE)
    if rows.size == 0:
        return []
    return np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)


def _staves(dark: np.ndarray) -> tuple[list[_Staff], float]:
    """The staves on the page, top to bottom, and the usual line spacing."""
    bands = _line_bands(dark)
    if len(bands) < _MIN_LINES_PER_STAFF:
        return [], 0.0
    centers = [float(band.mean()) for band in bands]
    gaps = np.diff(centers)
    # Most gaps lie inside a staff, so the median is the line spacing.
    spacing = float(median(gaps))
    breaks = np.flatnonzero(gaps > spacing * _STAFF_GAP_FACTOR) + 1
    groups = (_without_strays(list(group), centers) for group in np.split(np.arange(len(bands)), breaks))
    candidates = (
        _staff(dark, [bands[i] for i in group], spacing)
        for group in groups
        if len(group) >= _MIN_LINES_PER_STAFF and _evenly_spaced([centers[i] for i in group])
    )
    return [staff for staff in candidates if staff is not None], spacing


def _without_strays(group: list[int], centers: list[float]) -> list[int]:
    """``group`` less the bands that sit too close to the line above: long beams, tremolo rows."""
    if len(group) < _MIN_LINES_PER_STAFF:
        return group
    spacing = median(np.diff([centers[i] for i in group]))
    kept = [group[0]]
    for i in group[1:]:
        if centers[i] - centers[kept[-1]] >= spacing * (1 - _SPACING_TOLERANCE):
            kept.append(i)
    return kept


def _evenly_spaced(centers: list[float]) -> bool:
    """Whether the lines are spaced like a staff: every gap one or two line spacings.

    Two spacings is a line too faint to detect. Frame rules and the strokes of large title letters
    are spaced anyhow.
    """
    gaps = np.diff(centers)
    ratios = gaps / median(gaps)
    nearest = np.rint(ratios)
    return bool(np.all((nearest >= 1) & (nearest <= 2) & (np.abs(ratios - nearest) <= _SPACING_TOLERANCE)))


def _staff(dark: np.ndarray, lines: list[np.ndarray], spacing: float) -> _Staff | None:
    """The staff these lines draw, or None when they are not solid enough to be staff lines."""
    inked_lines = [dark[line].any(axis=0) for line in lines]
    # A column belongs to the staff where at least half its lines are dark. The staff is the
    # longest such run: a frame or scan shadow in the margin is dark on every row too, but apart.
    inked = sum(line.astype(int) for line in inked_lines)
    columns = np.flatnonzero(inked * 2 >= len(lines))
    runs = np.split(columns, np.flatnonzero(np.diff(columns) > max(spacing, 1)) + 1)
    run = max(runs, key=lambda r: r[-1] - r[0])
    left, right = int(run[0]), int(run[-1])
    # Staff lines are unbroken across the staff; rows of large lettering have gaps between letters.
    solidity = median(float(line[left : right + 1].mean()) for line in inked_lines)
    if solidity < _MIN_LINE_SOLIDITY:
        return None
    return _Staff(int(lines[0][0]), int(lines[-1][-1]), left, right)


def _largest_system(dark: np.ndarray, staves: list[_Staff], spacing: float) -> int:
    if not staves:
        return 0
    largest = size = 1
    for upper, lower in zip(staves, staves[1:]):
        size = size + 1 if _joined(dark, upper, lower, spacing) else 1
        largest = max(largest, size)
    return largest


def _joined(dark: np.ndarray, upper: _Staff, lower: _Staff, spacing: float) -> bool:
    """Whether a vertical line runs from ``upper`` down to ``lower`` within their shared width."""
    margin = int(round(spacing * _JOIN_MARGIN_SPACINGS))
    left = max(upper.left, lower.left, margin) - margin
    right = min(upper.right, lower.right) + margin
    gap = dark[upper.last_row + 1 : lower.first_row, left : right + 1]
    if gap.shape[0] == 0:
        return True
    if gap.shape[1] == 0:
        return False
    # One pixel of slack either side keeps a line that leans a little (a scan off square) whole.
    widened = gap.copy()
    widened[:, 1:] |= gap[:, :-1]
    widened[:, :-1] |= gap[:, 1:]
    return bool(widened.mean(axis=0).max() >= _MIN_JOIN_COVERAGE)
