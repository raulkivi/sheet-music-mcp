"""
Core rendering engine for render-mcp.

No MCP SDK imports here — this module is independently unit-testable.

Pipeline:
    MusicXML string
        → render_to_pdf()    → PDF file at output_path, returns (path, page_count)
        → render_to_image()  → image file at output_path, returns image metadata dict

Both first cut the score to an optional ``measures=[start, end]`` with the core's
``select_measures`` and only then dispatch to MuseScore or Verovio, so the backends see the
same cut score and know nothing of ranges.

    MusicXML string + page, width, zoom
        → SvgPageRenderer.render() → one page's SVG for the Score Viewer (Verovio only)
"""

import hashlib
import io
import logging
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional, Sequence

from sheet_music_mcp_core.errors import ProcessingError  # re-exported for server.py
from sheet_music_mcp_core.measures import select_measures

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Backend detection (cached at module load)
# ---------------------------------------------------------------------------

# MuseScore command names to try, in order of preference
_MUSESCORE_CMDS = ("mscore4", "musescore4", "musescore")


def _find_musescore_cmd() -> Optional[str]:
    for cmd in _MUSESCORE_CMDS:
        if shutil.which(cmd):
            return cmd
    return None


def _check_verovio() -> bool:
    try:
        import verovio  # noqa: F401
        return True
    except ImportError:
        return False


def _check_cairosvg() -> bool:
    try:
        import cairosvg  # noqa: F401
        return True
    except (ImportError, OSError):
        return False


# Cached at module load time
_MUSESCORE_CMD: Optional[str] = _find_musescore_cmd()
_VEROVIO_AVAILABLE: bool = _check_verovio()
_CAIROSVG_AVAILABLE: bool = _check_cairosvg()


def detect_backend() -> Optional[str]:
    """Return the active rendering backend: 'musescore', 'verovio', or None."""
    if _MUSESCORE_CMD:
        return "musescore"
    if _VEROVIO_AVAILABLE:
        return "verovio"
    return None


def musescore_available() -> bool:
    return _MUSESCORE_CMD is not None


def verovio_available() -> bool:
    return _VEROVIO_AVAILABLE


def cairosvg_available() -> bool:
    return _CAIROSVG_AVAILABLE


def get_health_status() -> dict:
    """Return a status dict describing all runtime dependencies.

    Safe to call at any time; no MCP imports.
    """
    backend = detect_backend()
    return {
        "server": "render-mcp",
        "status": "ok" if backend is not None else "degraded",
        "backend": backend,
        "musescore_available": musescore_available(),
        "verovio_available": verovio_available(),
        "cairosvg_available": cairosvg_available(),
        "notes": (
            []
            if backend is not None
            else [
                "No rendering backend found. "
                "Install MuseScore 4 or run: uv add verovio cairosvg"
            ]
        )
        + (
            [
                "cairosvg or libcairo2 not accessible — PNG/PDF output via Verovio "
                "will fail. Install libcairo2 and run: uv add cairosvg"
            ]
            if verovio_available() and not cairosvg_available()
            else []
        ),
    }


# ---------------------------------------------------------------------------
# render_to_pdf
# ---------------------------------------------------------------------------

def render_to_pdf(
    musicxml_str: str, output_path: str, measures: Optional[Sequence[int]] = None
) -> tuple[str, int]:
    """Render a MusicXML score to a PDF file.

    Args:
        musicxml_str: MusicXML document as a string.
        output_path: Destination path for the PDF file.
        measures: Optional inclusive [start, end] printed measure numbers; only those bars
            are rendered (docs/conventions.md, Measure Ranges).

    Returns:
        (output_path, page_count) tuple.

    Raises:
        ProcessingError: if no backend is available, the measure range is invalid
            (INVALID_PARAMETER) or rendering fails.
    """
    musicxml_str = select_measures(musicxml_str, measures)
    backend = detect_backend()
    if backend is None:
        raise ProcessingError(
            "No rendering backend available. "
            "Install MuseScore 4 (https://musescore.org) or run: pip install verovio cairosvg",
            "PROCESSING_FAILED",
        )

    if backend == "musescore":
        return _render_pdf_musescore(musicxml_str, output_path)
    else:
        return _render_pdf_verovio(musicxml_str, output_path)


def _render_pdf_musescore(musicxml_str: str, output_path: str) -> tuple[str, int]:
    """Render via MuseScore CLI."""
    with tempfile.NamedTemporaryFile(suffix=".musicxml", delete=False, mode="w", encoding="utf-8") as f:
        f.write(musicxml_str)
        tmp_input = f.name

    try:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [_MUSESCORE_CMD, "-o", output_path, tmp_input],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise ProcessingError(
                f"MuseScore rendering failed (exit {result.returncode}): "
                f"{result.stderr.strip()}",
                "PROCESSING_FAILED",
            )
        if not Path(output_path).exists():
            raise ProcessingError(
                "MuseScore completed but did not produce a PDF file.",
                "PROCESSING_FAILED",
            )
        page_count = _get_pdf_page_count(output_path)
        return output_path, page_count
    finally:
        Path(tmp_input).unlink(missing_ok=True)


def _render_pdf_verovio(musicxml_str: str, output_path: str) -> tuple[str, int]:
    """Render via Verovio → SVG → cairosvg → PDF."""
    import verovio
    import cairosvg
    import pypdf

    tk = verovio.toolkit()
    tk.setOptions({
        "pageWidth": 1800,
        "pageHeight": 2546,
        "adjustPageHeight": 1,
        "adjustPageWidth": 0,
        "footer": "none",
        "header": "none",
    })

    if not tk.loadData(musicxml_str):
        raise ProcessingError("Verovio failed to load MusicXML", "INVALID_INPUT")

    page_count = tk.getPageCount()
    if page_count == 0:
        raise ProcessingError("Score has no renderable pages", "PROCESSING_FAILED")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Render each page SVG → single-page PDF, then merge
    page_pdfs: list[bytes] = []
    for page_num in range(1, page_count + 1):
        svg = tk.renderToSVG(page_num)
        pdf_page = cairosvg.svg2pdf(bytestring=svg.encode("utf-8"))
        page_pdfs.append(pdf_page)

    if len(page_pdfs) == 1:
        Path(output_path).write_bytes(page_pdfs[0])
    else:
        writer = pypdf.PdfWriter()
        for pdf_bytes in page_pdfs:
            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
            for page in reader.pages:
                writer.add_page(page)
        with open(output_path, "wb") as f:
            writer.write(f)

    return output_path, page_count


# ---------------------------------------------------------------------------
# render_to_image
# ---------------------------------------------------------------------------

def render_to_image(
    musicxml_str: str,
    page: int,
    fmt: str,
    dpi: int,
    output_path: str,
    measures: Optional[Sequence[int]] = None,
) -> dict:
    """Render a single page of a MusicXML score to PNG or SVG.

    Args:
        musicxml_str: MusicXML document as a string.
        page: Page number to render (1-indexed).
        fmt: Output format — "png" or "svg".
        dpi: Resolution for PNG output (ignored for SVG).
        output_path: Destination path for the image file.
        measures: Optional inclusive [start, end] printed measure numbers; only those bars
            are rendered, and ``page`` counts pages of the cut score.

    Returns:
        dict with keys: image_path, format, page, total_pages, backend,
                        width_px, height_px (PNG only).

    Raises:
        ProcessingError: on backend unavailability, invalid measure range or page, or
            render failure.
    """
    musicxml_str = select_measures(musicxml_str, measures)
    backend = detect_backend()
    if backend is None:
        raise ProcessingError(
            "No rendering backend available. "
            "Install MuseScore 4 or run: pip install verovio cairosvg",
            "PROCESSING_FAILED",
        )

    if backend == "musescore":
        return _render_image_musescore(musicxml_str, page, fmt, dpi, output_path)
    else:
        return _render_image_verovio(musicxml_str, page, fmt, dpi, output_path)


def _render_image_musescore(
    musicxml_str: str, page: int, fmt: str, dpi: int, output_path: str
) -> dict:
    """Render image via MuseScore CLI."""
    if fmt not in ("png", "svg"):
        raise ProcessingError(
            f"Unsupported format {fmt!r}. Use 'png' or 'svg'.", "INVALID_PARAMETER"
        )

    suffix = f".{fmt}"
    with tempfile.NamedTemporaryFile(suffix=".musicxml", delete=False, mode="w", encoding="utf-8") as f:
        f.write(musicxml_str)
        tmp_input = f.name

    # MuseScore writes page images as output-N.ext
    with tempfile.TemporaryDirectory() as tmp_dir:
        stem = "render"
        tmp_out_base = str(Path(tmp_dir) / (stem + suffix))
        try:
            result = subprocess.run(
                [_MUSESCORE_CMD, "-o", tmp_out_base, tmp_input, "-r", str(dpi)],
                capture_output=True,
                text=True,
                timeout=120,
            )
        finally:
            Path(tmp_input).unlink(missing_ok=True)

        if result.returncode != 0:
            raise ProcessingError(
                f"MuseScore rendering failed (exit {result.returncode}): "
                f"{result.stderr.strip()}",
                "PROCESSING_FAILED",
            )

        # Find the generated file — MuseScore may add `-N` suffix for page N
        candidates = [
            Path(tmp_dir) / f"{stem}{suffix}",
            Path(tmp_dir) / f"{stem}-{page}{suffix}",
        ]
        found = next((c for c in candidates if c.exists()), None)
        if found is None:
            # Fallback: look for any file matching the pattern
            matches = list(Path(tmp_dir).glob(f"{stem}*{suffix}"))
            if not matches:
                raise ProcessingError(
                    "MuseScore completed but did not produce an image file.",
                    "PROCESSING_FAILED",
                )
            found = sorted(matches)[page - 1] if page <= len(matches) else matches[0]

        # Count total pages from all generated files
        all_pages = sorted(Path(tmp_dir).glob(f"{stem}*{suffix}"))
        total_pages = len(all_pages)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        import shutil as _shutil
        _shutil.copy2(str(found), output_path)

    result_dict: dict = {
        "image_path": output_path,
        "format": fmt,
        "page": page,
        "total_pages": total_pages,
        "backend": "musescore",
    }
    if fmt == "png":
        w, h = _get_image_dimensions(output_path)
        result_dict["width_px"] = w
        result_dict["height_px"] = h
    return result_dict


def _render_image_verovio(
    musicxml_str: str, page: int, fmt: str, dpi: int, output_path: str
) -> dict:
    """Render image via Verovio → SVG (→ PNG if requested)."""
    import verovio

    if fmt not in ("png", "svg"):
        raise ProcessingError(
            f"Unsupported format {fmt!r}. Use 'png' or 'svg'.", "INVALID_PARAMETER"
        )

    tk = verovio.toolkit()
    tk.setOptions({
        "pageWidth": 1800,
        "pageHeight": 2546,
        "adjustPageHeight": 1,
        "adjustPageWidth": 0,
        "footer": "none",
        "header": "none",
    })

    if not tk.loadData(musicxml_str):
        raise ProcessingError("Verovio failed to load MusicXML", "INVALID_INPUT")

    total_pages = tk.getPageCount()
    if total_pages == 0:
        raise ProcessingError("Score has no renderable pages", "PROCESSING_FAILED")

    if page < 1 or page > total_pages:
        raise ProcessingError(
            f"Page {page} is out of range. Score has {total_pages} page(s).",
            "INVALID_PARAMETER",
        )

    svg = tk.renderToSVG(page)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    result_dict: dict = {
        "image_path": output_path,
        "format": fmt,
        "page": page,
        "total_pages": total_pages,
        "backend": "verovio",
    }

    if fmt == "svg":
        Path(output_path).write_text(svg, encoding="utf-8")
    else:
        import cairosvg
        # Verovio SVGs use fixed pixel dimensions; scale by dpi/96 to honour the
        # caller's resolution request (96 px/in is the CSS/screen reference).
        scale = dpi / 96.0
        png_bytes = cairosvg.svg2png(bytestring=svg.encode("utf-8"), scale=scale)
        Path(output_path).write_bytes(png_bytes)
        w, h = _get_image_dimensions(output_path)
        result_dict["width_px"] = w
        result_dict["height_px"] = h

    return result_dict


# ---------------------------------------------------------------------------
# Page SVG for the Score Viewer (render_page_svg)
# ---------------------------------------------------------------------------

# Mirrors ui/packages/kit/src/score/paging.ts so a server-rendered page looks like one the
# viewer renders with Verovio WASM; both are checked against ui/.../layout-cases.json.
_BASE_SCALE = 40
_MIN_LAYOUT_WIDTH = 1500
_PAGE_ASPECT = 1.414
_MIN_SCALE = 1
_MAX_SCALE = 1000


def _js_round(value: float) -> int:
    """JavaScript's Math.round: halves go up (Python's round() goes to even)."""
    return math.floor(value + 0.5)


def _fit_width_scale(container_width: float, page_width: float) -> int:
    if not container_width > 0 or not page_width > 0:
        return 100
    return min(_MAX_SCALE, max(_MIN_SCALE, _js_round(container_width / page_width * 100)))


def page_layout(container_width: float, zoom: float) -> dict:
    """Verovio ``scale``, ``pageWidth`` and ``pageHeight`` for a viewer width and zoom (paging.ts layoutFor)."""
    scale = _js_round(zoom * _BASE_SCALE)
    wanted = _js_round((container_width * 100) / scale)
    if wanted >= _MIN_LAYOUT_WIDTH:
        page_width = wanted
    else:
        scale = min(scale, _fit_width_scale(container_width, _MIN_LAYOUT_WIDTH))
        page_width = _MIN_LAYOUT_WIDTH
    return {"scale": scale, "pageWidth": page_width, "pageHeight": _js_round(page_width * _PAGE_ASPECT)}


def _viewer_options(layout: dict) -> dict:
    # Same as ScoreView.applyLayout(); smuflTextFont stays Verovio's "embedded" default (see
    # docs/architecture.md: no mode shows tempo note glyphs under the spec's default CSP).
    return {**layout, "adjustPageHeight": True, "breaks": "auto", "footer": "none"}


def _verovio_toolkit():
    from importlib.resources import files

    import verovio

    toolkit = verovio.toolkit()
    # verovio sets its default resource path per thread, on the importing thread only; a toolkit
    # made on a worker thread would otherwise look for fonts at the wheel's build-time path.
    toolkit.setResourcePath(str(files("verovio") / "data"))
    return toolkit


class SvgPageRenderer:
    """Renders single pages of the last score it was given, re-parsing only a new score.

    The viewer pages and zooms through one score with a call per page, so the parsed score is
    kept by content hash and a new width or zoom only re-flows it. One score at a time keeps
    memory flat; a second viewer showing another score just reloads.
    """

    def __init__(self, toolkit_factory: Callable[[], object] = _verovio_toolkit):
        self._toolkit_factory = toolkit_factory
        self._toolkit = None
        self._score_hash: str | None = None
        self._layout: dict | None = None

    def render(self, musicxml: str, page: int, width_px: int, zoom: float) -> dict:
        """``{"svg", "page", "page_count"}`` for ``page`` laid out at ``width_px`` and ``zoom``.

        Raises:
            ProcessingError: INVALID_INPUT if Verovio cannot read the score, INVALID_PARAMETER
                (hint: the page range) if ``page`` is past the last page of this layout.
        """
        layout = page_layout(width_px, zoom)
        toolkit = self._toolkit_for(musicxml, layout)
        page_count = toolkit.getPageCount()
        if page_count < 1:
            raise ProcessingError("Score has no renderable pages", "PROCESSING_FAILED")
        if not 1 <= page <= page_count:
            raise ProcessingError(
                f"Page {page} is out of range.",
                "INVALID_PARAMETER",
                hint=f"This score has pages 1–{page_count} at this width and zoom.",
            )
        return {"svg": toolkit.renderToSVG(page), "page": page, "page_count": page_count}

    def _toolkit_for(self, musicxml: str, layout: dict):
        score_hash = hashlib.sha256(musicxml.encode("utf-8")).hexdigest()
        if score_hash != self._score_hash:
            # Forget the old score first, so a failed load never leaves a stale one cached.
            self._toolkit = self._score_hash = None
            toolkit = self._toolkit_factory()
            toolkit.setOptions(_viewer_options(layout))
            if not toolkit.loadData(musicxml):
                raise ProcessingError("Verovio failed to load MusicXML", "INVALID_INPUT")
            self._toolkit, self._score_hash, self._layout = toolkit, score_hash, layout
        elif layout != self._layout:
            self._toolkit.setOptions(_viewer_options(layout))
            self._toolkit.redoLayout()
            self._layout = layout
        return self._toolkit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_pdf_page_count(pdf_path: str) -> int:
    """Return the page count of a PDF file."""
    try:
        import pypdf
        with open(pdf_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            return len(reader.pages)
    except Exception:
        return 0


def _get_image_dimensions(image_path: str) -> tuple[int, int]:
    """Return (width, height) in pixels for a PNG/image file."""
    from PIL import Image
    with Image.open(image_path) as img:
        return img.size
