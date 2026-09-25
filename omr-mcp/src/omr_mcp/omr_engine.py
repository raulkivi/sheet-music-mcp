import os
import time
import re
import shutil
import subprocess
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from defusedxml.ElementTree import fromstring as _fromstring  # type: ignore[import-untyped]
from pathlib import Path
import logging
from typing import Any, Optional

from .onnx_compat import fix_negative_convtranspose_pads

logger = logging.getLogger(__name__)

# oemer always prefers the CUDA execution provider on Linux/Windows when a
# GPU is visible. onnxruntime's CUDA provider has been observed to hard-abort
# (a native crash, not a catchable Python exception) on hosts where the
# driver's CUDA runtime doesn't line up with the onnxruntime-gpu build.
# Hiding the GPU makes onnxruntime fall back to CPU cleanly instead. Uses
# setdefault so an operator who has deliberately set CUDA_VISIBLE_DEVICES is
# still respected.
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

_AUDIVERIS_VERSION = "5.11.0"
_AUDIVERIS_DEB_URL = (
    f"https://github.com/Audiveris/audiveris/releases/download/"
    f"{_AUDIVERIS_VERSION}/Audiveris-{_AUDIVERIS_VERSION}-ubuntu24.04-x86_64.deb"
)
_AUDIVERIS_TIMEOUT_SECONDS = 300


def _oemer_checkpoint_path() -> Optional[Path]:
    """Return the path oemer stores its downloaded model checkpoints under.

    oemer caches checkpoints inside its own installed package directory
    (``MODULE_PATH/checkpoints/...``), not under the user's home directory.
    """
    try:
        from oemer import MODULE_PATH  # type: ignore[import-untyped]
    except ImportError:
        return None
    return Path(MODULE_PATH) / "checkpoints" / "unet_big" / "model.onnx"


def _audiveris_home() -> Path:
    """Cache directory Audiveris is downloaded/extracted into on first use."""
    override = os.environ.get("OMR_AUDIVERIS_HOME")
    if override:
        return Path(override)
    return Path.home() / ".cache" / "omr-mcp" / "audiveris"


def _audiveris_binary_path() -> Path:
    return _audiveris_home() / "opt" / "audiveris" / "bin" / "Audiveris"


def health_check() -> dict[str, Any]:
    """Check runtime dependencies and return a human-readable status summary.

    Returns a dict with top-level ``status`` ("ok" or "degraded") and a
    ``checks`` mapping with per-dependency results.  Does not import oemer
    beyond a simple availability probe so it stays fast.
    """
    checks: dict[str, dict[str, Any]] = {}

    # --- oemer availability ---
    try:
        import oemer  # noqa: F401  # type: ignore[import-untyped]
        from importlib.metadata import version as pkg_version
        try:
            oemer_version = pkg_version("oemer")
        except Exception:
            oemer_version = "unknown"
        checks["oemer"] = {"status": "ok", "version": oemer_version}
    except ImportError as exc:
        checks["oemer"] = {
            "status": "missing",
            "error": str(exc),
            "hint": "Run 'uv sync' inside omr-mcp/ to install dependencies.",
        }

    # --- oemer model cache ---
    checkpoint_path = _oemer_checkpoint_path()

    if checkpoint_path is not None and checkpoint_path.exists():
        checks["model_cache"] = {
            "status": "ok",
            "path": str(checkpoint_path.parent.parent),
            "note": "Model cache found — ready to recognise sheet music.",
        }
    else:
        checks["model_cache"] = {
            "status": "missing",
            "path": None,
            "note": (
                "Model cache not found. On first use oemer will download ~100 MB of "
                "model checkpoints (this may take 5–10 minutes). Subsequent runs are fast."
            ),
        }

    # --- Audiveris (optional alternate engine) ---
    # Not required for the server to function (default engine is oemer), so its absence
    # doesn't affect overall status — only oemer/model_cache are load-bearing there.
    audiveris_binary = _audiveris_binary_path()
    if audiveris_binary.exists():
        checks["audiveris"] = {
            "status": "ok",
            "path": str(audiveris_binary),
            "version": _AUDIVERIS_VERSION,
            "note": "Optional alternate engine (engine=\"audiveris\") — ready to use.",
        }
    else:
        checks["audiveris"] = {
            "status": "not_installed",
            "path": None,
            "note": (
                "Optional alternate engine, better suited to multi-staff (SATB) scores "
                "than oemer. Not required — downloads automatically (~80 MB) on first use "
                "of engine=\"audiveris\"."
            ),
        }

    overall = "ok" if checks["oemer"]["status"] == "ok" and checks["model_cache"]["status"] == "ok" else "degraded"
    return {"status": overall, "checks": checks}


def _extract_musicxml_metadata(musicxml_content: str) -> dict[str, Any]:
    """Extract metadata from MusicXML content."""
    metadata = {}

    # Count staves (parts)
    staves_matches = re.findall(r'<part\s+id=', musicxml_content)
    metadata["staves_detected"] = len(staves_matches) if staves_matches else 0

    # Count measures (in first part to avoid duplicates)
    measure_matches = re.findall(r'<measure\s+number="(\d+)"', musicxml_content)
    if measure_matches:
        # Count of distinct measure numbers — not max(), since not every engine numbers
        # measures 1-indexed with no gaps (Audiveris starts at 0, which would undercount
        # by one under max()).
        unique_measures = set(int(m) for m in measure_matches)
        metadata["measures"] = len(unique_measures)
    else:
        metadata["measures"] = 0

    return metadata


def _ensure_oemer_checkpoints() -> None:
    """Download oemer's model checkpoints on first use (~100 MB, one-time)."""
    from oemer.ete import CHECKPOINTS_URL, download_file  # type: ignore[import-untyped]

    checkpoint_path = _oemer_checkpoint_path()
    if checkpoint_path is None or checkpoint_path.exists():
        return

    logger.info("Downloading oemer model checkpoints (first run only, ~100 MB)...")
    module_path = checkpoint_path.parent.parent
    for title, url in CHECKPOINTS_URL.items():
        save_dir = "unet_big" if title.startswith("1st") else "seg_net"
        save_path = module_path / save_dir / title.split("_")[1]
        download_file(title, url, str(save_path))


def _run_oemer(image_path: str) -> str:
    """Run oemer on an image and return the output path."""
    import tempfile
    from argparse import Namespace
    from oemer.ete import clear_data, extract  # type: ignore[import-untyped]

    _ensure_oemer_checkpoints()
    # Runs every time, not only after a download: checkpoints cached by an
    # older omr-mcp are still unpatched. A no-op once the model is fixed.
    checkpoint_path = _oemer_checkpoint_path()
    if checkpoint_path is not None:
        fix_negative_convtranspose_pads(checkpoint_path)

    output_dir = tempfile.mkdtemp(prefix="oemer_")
    args = Namespace(
        img_path=image_path,
        output_path=output_dir,
        use_tf=False,
        save_cache=False,
        without_deskew=False,
    )
    # oemer keeps prediction state in module-level layers between calls —
    # clear it first so consecutive recognitions don't see stale data.
    clear_data()
    return extract(args)


def _ensure_audiveris_installed() -> Path:
    """Download and extract Audiveris on first use (~80 MB download, ~190 MB extracted).

    Audiveris ships as a self-contained Ubuntu .deb bundling its own JRE — extracted
    directly with ``dpkg-deb -x`` into a user cache dir rather than a system-wide
    ``dpkg -i``/``apt install``, so this never needs root and never touches system
    package state (unlike system libraries the other servers depend on via apt).
    """
    binary = _audiveris_binary_path()
    if binary.exists():
        return binary

    home = _audiveris_home()
    home.mkdir(parents=True, exist_ok=True)
    deb_path = home / "audiveris.deb"

    logger.info(f"Downloading Audiveris OMR engine (first run only, ~80 MB): {_AUDIVERIS_DEB_URL}")
    urllib.request.urlretrieve(_AUDIVERIS_DEB_URL, deb_path)

    try:
        subprocess.run(
            ["dpkg-deb", "-x", str(deb_path), str(home)],
            check=True, capture_output=True, text=True,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "'dpkg-deb' is required to install the Audiveris engine but was not found. "
            "It ships with dpkg on Debian/Ubuntu; on other distributions, extract "
            f"{deb_path} manually into {home}."
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to extract Audiveris package: {e.stderr}")
    finally:
        deb_path.unlink(missing_ok=True)

    if not binary.exists():
        raise RuntimeError(
            f"Audiveris extraction completed but expected binary not found at {binary}"
        )
    return binary


def _run_audiveris(image_path: str) -> str:
    """Run Audiveris on an image and return the path to the exported MusicXML.

    Unlike oemer, Audiveris genuinely needs adequate source resolution — it refuses
    to process an image below ~300 DPI (interline value too small to reliably detect
    staff lines) rather than silently degrading, so a low-resolution input surfaces
    as a clear failure here instead of a garbled result.
    """
    import tempfile

    binary = _ensure_audiveris_installed()
    output_dir = tempfile.mkdtemp(prefix="audiveris_")

    result = subprocess.run(
        [str(binary), "-batch", "-export", "-output", output_dir, image_path],
        capture_output=True, text=True, timeout=_AUDIVERIS_TIMEOUT_SECONDS,
    )

    stem = Path(image_path).stem
    mxl_path = Path(output_dir) / f"{stem}.mxl"
    if not mxl_path.exists():
        # Audiveris can exit 0 even when it rejects every sheet (e.g. resolution too
        # low), so presence of the expected output file is the real success signal,
        # not the exit code.
        tail = (result.stdout or "")[-800:]
        raise RuntimeError(
            "Audiveris did not produce output MusicXML — this usually means the image "
            "resolution was too low for reliable staff-line detection (300+ DPI "
            f"recommended) or no recognizable staves were found. Log tail: {tail}"
        )

    with zipfile.ZipFile(mxl_path) as z:
        xml_names = [n for n in z.namelist() if n.endswith(".xml") and "META-INF" not in n]
        if not xml_names:
            raise RuntimeError(f"Audiveris output {mxl_path} has no MusicXML entry")
        musicxml_content = z.read(xml_names[0]).decode("utf-8")

    result_path = Path(output_dir) / f"{stem}.musicxml"
    result_path.write_text(musicxml_content, encoding="utf-8")
    return str(result_path)


_ENGINE_RUNNERS = {
    "oemer": _run_oemer,
    "audiveris": _run_audiveris,
}


def recognize_image(image_path: str, engine: str = "oemer") -> dict[str, Any]:
    """Process sheet music image and return MusicXML.

    Args:
        image_path: Path to a PNG/JPEG image.
        engine: "oemer" (default) or "audiveris". Audiveris handles multi-staff (SATB)
            scores correctly where oemer either flattens them into one part or crashes
            outright (see docs/HANDOVER.md) — at the cost of a much larger first-use
            download and requiring 300+ DPI source images.
    """
    path = Path(image_path)

    if not path.exists():
        return {"error": f"File not found: {image_path}", "error_code": "FILE_NOT_FOUND"}

    if path.suffix.lower() not in [".png", ".jpg", ".jpeg"]:
        return {
            "error": f"Unsupported format: {path.suffix}. Supported formats: PNG, JPEG",
            "error_code": "UNSUPPORTED_FORMAT",
        }

    run_fn = _ENGINE_RUNNERS.get(engine)
    if run_fn is None:
        return {
            "error": f"Unknown engine: {engine!r}. Supported engines: {sorted(_ENGINE_RUNNERS)}",
            "error_code": "INVALID_PARAMETER",
        }

    start_time = time.time()

    try:
        logger.info(f"Starting OMR processing for: {path} (engine={engine})")
        result_path = run_fn(str(path))

        if not Path(result_path).exists():
            return {
                "error": f"OMR processing completed but output file not found: {result_path}",
                "error_code": "PROCESSING_FAILED",
            }

        with open(result_path, "r", encoding="utf-8") as f:
            musicxml_content = f.read()

        processing_time_ms = int((time.time() - start_time) * 1000)
        xml_metadata = _extract_musicxml_metadata(musicxml_content)

        logger.info(f"OMR processing completed successfully in {processing_time_ms}ms")

        return {
            "musicxml": musicxml_content,
            "metadata": {
                "source": str(path),
                "staves_detected": xml_metadata["staves_detected"],
                "measures": xml_metadata["measures"],
                "processing_time_ms": processing_time_ms,
                "engine": engine,
            }
        }

    except ImportError as e:
        hint = "Please install with: pip install oemer" if engine == "oemer" else str(e)
        return {
            "error": f"{engine} backend not available: {str(e)}. {hint}",
            "error_code": "PROCESSING_FAILED",
        }
    except Exception as e:
        processing_time_ms = int((time.time() - start_time) * 1000)
        logger.error(f"OMR processing failed after {processing_time_ms}ms: {str(e)}")
        return {
            "error": f"OMR processing failed: {str(e)}",
            "error_code": "PROCESSING_FAILED",
            "metadata": {
                "source": str(path),
                "processing_time_ms": processing_time_ms,
                "engine": engine,
            }
        }


def _merge_musicxml_pages(musicxml_pages: list[str]) -> str:
    """Merge per-page MusicXML documents into a single score.

    Appends the measures from each successive page into the matching parts of
    the first page's document (matched by index). Measure numbers are
    renumbered to continue sequentially across pages.
    """
    if len(musicxml_pages) == 1:
        return musicxml_pages[0]

    trees = [_fromstring(page) for page in musicxml_pages]
    base = trees[0]
    base_parts = list(base.findall("part"))

    for page_tree in trees[1:]:
        page_parts = list(page_tree.findall("part"))
        for i, page_part in enumerate(page_parts):
            if i >= len(base_parts):
                break  # extra parts on this page — skip
            base_part = base_parts[i]
            existing = base_part.findall("measure")
            last_num = max((int(m.get("number", 0)) for m in existing), default=0)
            for measure in page_part.findall("measure"):
                old_num = int(measure.get("number", 0))
                measure.set("number", str(last_num + old_num))
                base_part.append(measure)

    return ET.tostring(base, encoding="unicode")


def recognize_images(image_paths: list[str], engine: str = "oemer") -> dict[str, Any]:
    """Process multiple sheet music images in page order and return merged MusicXML.

    Args:
        image_paths: Ordered list of image file paths (or base64 strings).
        engine: "oemer" (default) or "audiveris" — see recognize_image().

    Returns:
        dict with 'musicxml' and 'metadata' (including 'page_count'), or 'error'.
    """
    if not image_paths:
        return {"error": "No images provided", "error_code": "INVALID_PARAMETER"}

    page_results = []
    errors = []

    for i, path in enumerate(image_paths):
        result = recognize_image(path, engine=engine)
        if "error" in result:
            errors.append(f"Page {i + 1} ({path}): {result['error']}")
        else:
            page_results.append(result)

    if errors:
        return {
            "error": f"Failed to process {len(errors)} page(s): {'; '.join(errors)}",
            "error_code": "PROCESSING_FAILED",
        }

    if len(page_results) == 1:
        result = page_results[0]
        result["metadata"]["page_count"] = 1
        return result

    merged_xml = _merge_musicxml_pages([r["musicxml"] for r in page_results])
    xml_meta = _extract_musicxml_metadata(merged_xml)
    total_time = sum(r["metadata"]["processing_time_ms"] for r in page_results)

    return {
        "musicxml": merged_xml,
        "metadata": {
            "page_count": len(page_results),
            "staves_detected": xml_meta["staves_detected"],
            "measures": xml_meta["measures"],
            "processing_time_ms": total_time,
            "engine": engine,
        },
    }


def recognize_image_to_file(input_path: str, output_path: Optional[str] = None, engine: str = "oemer") -> dict[str, Any]:
    """Process sheet music image and save MusicXML to file.

    Args:
        input_path: Path to a PNG/JPEG image.
        output_path: Path for output MusicXML file (auto-generated if omitted).
        engine: "oemer" (default) or "audiveris" — see recognize_image().
    """
    path = Path(input_path)

    if not path.exists():
        return {"error": f"File not found: {input_path}", "error_code": "FILE_NOT_FOUND"}

    if path.suffix.lower() not in [".png", ".jpg", ".jpeg"]:
        return {
            "error": f"Unsupported format: {path.suffix}. Supported formats: PNG, JPEG",
            "error_code": "UNSUPPORTED_FORMAT",
        }

    run_fn = _ENGINE_RUNNERS.get(engine)
    if run_fn is None:
        return {
            "error": f"Unknown engine: {engine!r}. Supported engines: {sorted(_ENGINE_RUNNERS)}",
            "error_code": "INVALID_PARAMETER",
        }

    # Determine output path
    if output_path is None:
        output_path = str(path.with_suffix(".musicxml"))

    start_time = time.time()

    try:
        logger.info(f"Starting OMR processing for: {path} (engine={engine})")
        result_path = run_fn(str(path))

        if not Path(result_path).exists():
            return {
                "error": f"OMR processing completed but output file not found: {result_path}",
                "error_code": "PROCESSING_FAILED",
            }

        # Copy to output path if different
        if str(Path(result_path).resolve()) != str(Path(output_path).resolve()):
            shutil.copy2(result_path, output_path)

        # Read content for metadata extraction
        with open(output_path, "r", encoding="utf-8") as f:
            musicxml_content = f.read()

        processing_time_ms = int((time.time() - start_time) * 1000)
        xml_metadata = _extract_musicxml_metadata(musicxml_content)

        logger.info(f"OMR processing completed successfully in {processing_time_ms}ms")

        return {
            "output_path": output_path,
            "metadata": {
                "source": str(path),
                "staves_detected": xml_metadata["staves_detected"],
                "measures": xml_metadata["measures"],
                "processing_time_ms": processing_time_ms,
                "engine": engine,
            }
        }

    except ImportError as e:
        hint = "Please install with: pip install oemer" if engine == "oemer" else str(e)
        return {
            "error": f"{engine} backend not available: {str(e)}. {hint}",
            "error_code": "PROCESSING_FAILED",
        }
    except Exception as e:
        processing_time_ms = int((time.time() - start_time) * 1000)
        logger.error(f"OMR processing failed after {processing_time_ms}ms: {str(e)}")
        return {
            "error": f"OMR processing failed: {str(e)}",
            "error_code": "PROCESSING_FAILED",
            "metadata": {
                "source": str(path),
                "processing_time_ms": processing_time_ms,
                "engine": engine,
            }
        }
