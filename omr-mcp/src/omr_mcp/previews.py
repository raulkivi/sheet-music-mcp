"""Source previews for the Recognition Review: the input page as a downscaled JPEG, by job id.

A recognition job gets a random ``job_id``, the recognised score and one stored JPEG per input
page. The app-only ``get_source_preview`` and ``get_recognized_score`` tools look the id up here, so it never sees a path (proposal 5.5, §7).
No MCP imports.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image, ImageOps
from sheet_music_mcp_core.artifacts import DEFAULT_TTL_SECONDS, ArtifactStore
from sheet_music_mcp_core.errors import ProcessingError
from sheet_music_mcp_core.paths import new_output_path

logger = logging.getLogger(__name__)

MAX_PREVIEW_SIDE = 1600
PREVIEW_MIME = "image/jpeg"
_JPEG_QUALITY = 85

_UNKNOWN_JOB_HINT = (
    "Job ids are kept for a limited time and are lost when the server restarts. "
    "Run the recognition again for a new job_id."
)


def write_source_preview(image_path: str | Path) -> Path:
    """Write a JPEG of ``image_path``, at most ``MAX_PREVIEW_SIDE`` px on its long side, into the output root.

    A fresh file inside the output root, rather than the input itself, because the artifact store
    only serves files there and the input may live anywhere. Raises ProcessingError if the image
    cannot be read.
    """
    try:
        with Image.open(image_path) as source:
            image = ImageOps.exif_transpose(source)
            image = _on_white(image)
            image.thumbnail((MAX_PREVIEW_SIDE, MAX_PREVIEW_SIDE))
            target = new_output_path("source-preview", ".jpg", subdir="previews")
            image.save(target, "JPEG", quality=_JPEG_QUALITY)
    except (OSError, ValueError, Image.DecompressionBombError) as e:
        raise ProcessingError(f"Cannot make a preview of the image: {e}", "INVALID_INPUT") from e
    return target


def _on_white(image: Image.Image) -> Image.Image:
    # JPEG has no alpha; converting transparent PNG pixels straight to RGB would turn them black.
    if image.mode in ("RGBA", "LA", "P"):
        rgba = image.convert("RGBA")
        return Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba).convert("RGB")
    return image.convert("RGB")


@dataclass(frozen=True)
class _Job:
    created: float
    musicxml: str
    artifact_ids: list[str | None]


class ReviewJobs:
    """Job ids to the recognised score and the stored preview of each page.

    The score lives here, not in ``structuredContent``, so it is not re-sent in results
    (proposal 6.3). Jobs expire after ``ttl_seconds`` like the artifacts they point to, and the
    oldest go first beyond ``max_jobs``; each holds a whole score, hence the small default.
    """

    def __init__(
        self,
        max_jobs: int = 16,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        if max_jobs < 1:
            raise ValueError("max_jobs must be at least 1")
        self._max = max_jobs
        self._ttl = ttl_seconds
        self._clock = clock
        self._jobs: OrderedDict[str, _Job] = OrderedDict()
        self._lock = threading.Lock()

    def register(self, store: ArtifactStore, musicxml: str, previews: list[Path | None]) -> str:
        """Store each page's preview file (None: no preview), keep the score, return the job id."""
        artifact_ids = [self._store_page(store, path) for path in previews]
        job_id = secrets.token_urlsafe(16)
        with self._lock:
            now = self._clock()
            self._purge(now)
            self._jobs[job_id] = _Job(now, musicxml, artifact_ids)
            while len(self._jobs) > self._max:
                self._jobs.popitem(last=False)
        return job_id

    def musicxml(self, job_id: object) -> str:
        """The recognised score of the job; INVALID_PARAMETER if the job is unknown or expired."""
        return self._job(job_id).musicxml

    def available_pages(self, job_id: str) -> list[bool]:
        """Per page, whether a preview can be fetched."""
        return [artifact_id is not None for artifact_id in self._job(job_id).artifact_ids]

    def artifact_id(self, job_id: object, page: object) -> str:
        """The artifact holding page ``page`` (1-based) of the job; INVALID_PARAMETER if there is none."""
        artifact_ids = self._job(job_id).artifact_ids
        # bool is an int subclass; True as a page number is a caller bug, not page 1.
        if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= len(artifact_ids):
            raise ProcessingError(
                f"page must be a whole number from 1 to {len(artifact_ids)}", "INVALID_PARAMETER"
            )
        artifact_id = artifact_ids[page - 1]
        if artifact_id is None:
            raise ProcessingError(f"Page {page} has no preview", "INVALID_PARAMETER")
        return artifact_id

    def _job(self, job_id: object) -> _Job:
        with self._lock:
            self._purge(self._clock())
            job = self._jobs.get(job_id) if isinstance(job_id, str) else None
        if job is None:
            # The id is not echoed: it is caller-chosen text and may be crafted to look like a path.
            raise ProcessingError("Unknown or expired job_id", "INVALID_PARAMETER", hint=_UNKNOWN_JOB_HINT)
        return job

    def _purge(self, now: float) -> None:
        # Insertion order is creation order, so expired jobs are all at the front.
        while self._jobs and now - next(iter(self._jobs.values())).created >= self._ttl:
            self._jobs.popitem(last=False)

    @staticmethod
    def _store_page(store: ArtifactStore, path: Path | None) -> str | None:
        if path is None:
            return None
        try:
            return store.put(path, PREVIEW_MIME)
        except ProcessingError as e:
            logger.warning("Source preview not stored: %s", e)
            return None
