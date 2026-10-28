"""Engine results to tool results: ``content`` for every client, ``structuredContent`` for apps.

``content`` is exactly what these tools returned before MCP Apps, so text-only clients see no
change (tests/test_content_golden.py). ``structuredContent`` is what the Recognition Review reads;
the engine's metadata stays out of ``content`` so the new ``staff_systems_estimate`` shows up in
the structured side only.
"""

from __future__ import annotations

from mcp.types import TextContent

_PAGE = {
    "type": "object",
    "properties": {
        "index": {"type": "integer", "minimum": 1, "description": "1-based page number, as get_source_preview's page"},
        "staves_detected": {"type": ["integer", "null"], "description": "Parts the engine found on this page"},
        "measures": {"type": ["integer", "null"]},
        "has_preview": {
            "type": "boolean",
            "description": "Whether get_source_preview can serve this page; only for clients that show the app",
        },
    },
    "required": ["index", "staves_detected", "measures"],
}

RECOGNITION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "job_id": {
            "type": "string",
            "description": "Opaque id for get_source_preview and get_recognized_score; only for clients that show the app",
        },
        "metadata": {
            "type": "object",
            "properties": {
                "engine": {"type": "string"},
                "staves_detected": {"type": "integer", "minimum": 0},
                "measures": {"type": "integer", "minimum": 0},
                "processing_time_ms": {"type": "integer", "minimum": 0},
                "page_count": {"type": "integer", "minimum": 1},
                "staff_systems_estimate": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Staves counted on the busiest page image, for clients that show the app; more than staves_detected hints at a flattened choir score",
                },
            },
        },
        "pages": {"type": "array", "items": _PAGE},
    },
    "required": ["metadata", "pages"],
}

SCORE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "job_id": {"type": "string"},
        "musicxml": {"type": "string", "description": "The score the recognition produced"},
    },
    "required": ["job_id", "musicxml"],
}

PREVIEW_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "job_id": {"type": "string"},
        "page": {"type": "integer", "minimum": 1},
        "artifact_id": {"type": "string"},
        "offset": {"type": "integer", "minimum": 0},
        "length": {"type": "integer", "minimum": 0},
        "byte_length": {"type": "integer", "minimum": 0},
        "eof": {"type": "boolean"},
        "data_b64": {"type": "string", "description": "Base64 of this chunk of the JPEG"},
    },
    "required": ["job_id", "page", "artifact_id", "offset", "length", "byte_length", "eof", "data_b64"],
}


def present_recognition(
    result: dict,
    content: list,
    *,
    job_id: str | None = None,
    previews: list[bool] | None = None,
    staff_estimates: list[int | None] | None = None,
) -> tuple[list, dict]:
    """``(content, structured_content)`` for a successful recognize_sheet / recognize_sheets.

    ``content`` is passed through untouched and the score is not repeated in the structured side
    (the app fetches it with ``get_recognized_score``). The summary of ``metadata`` and ``pages``
    is cheap, so every client gets it. The rest is for clients that show the app, and is left out
    when ``job_id`` is None: the id, per-page ``has_preview`` (``previews``, per input page) and
    ``staff_systems_estimate`` (the busiest of ``staff_estimates``, None for an unreadable image).
    """
    metadata = dict(result["metadata"])
    counted = [n for n in staff_estimates or [] if n is not None]
    if counted:
        metadata["staff_systems_estimate"] = max(counted)
    structured = {"metadata": metadata, "pages": _pages(result, previews)}
    if job_id is not None:
        structured["job_id"] = job_id
    return content, structured


def present_score(job_id: str, musicxml: str) -> tuple[list, dict]:
    """``(content, structured_content)`` for the app-only score fetch.

    Only the app reads the MusicXML, so the text block just says what was fetched and keeps the
    document out of any model context.
    """
    size_kb = max(1, round(len(musicxml.encode("utf-8")) / 1024))
    text = f"Recognised score ({size_kb} kB) fetched for the Recognition Review."
    return [TextContent(type="text", text=text)], {"job_id": job_id, "musicxml": musicxml}


def present_preview(job_id: str, page: int, chunk: dict) -> tuple[list, dict]:
    """``(content, structured_content)`` for the app-only preview read.

    Only the app decodes the pixels, so the text block just says which bytes were sent and keeps
    the base64 out of any model context.
    """
    end = chunk["offset"] + chunk["length"]
    text = f"Source preview of page {page} fetched for the Recognition Review (bytes {chunk['offset']}-{end} of {chunk['byte_length']})."
    return [TextContent(type="text", text=text)], {"job_id": job_id, "page": page, **chunk}


def _pages(result: dict, previews: list[bool] | None) -> list[dict]:
    reported = result.get("_pages")
    if reported is None:
        # recognize_sheet reports one page; an engine that gave no per-page detail leaves it unknown.
        count = len(previews) if previews is not None else result["metadata"].get("page_count", 1)
        single = count == 1
        reported = [
            {
                "index": i,
                "staves_detected": result["metadata"].get("staves_detected") if single else None,
                "measures": result["metadata"].get("measures") if single else None,
            }
            for i in range(1, count + 1)
        ]
    if previews is None:
        return [dict(page) for page in reported]
    return [{**page, "has_preview": has} for page, has in zip(reported, previews)]
