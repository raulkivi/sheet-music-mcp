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
        "has_preview": {"type": "boolean", "description": "Whether get_source_preview can serve this page"},
    },
    "required": ["index", "staves_detected", "measures", "has_preview"],
}

RECOGNITION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "job_id": {"type": "string", "description": "Opaque id for get_source_preview"},
        "musicxml": {"type": "string", "description": "The recognised score, whatever the return mode"},
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
                    "description": "Staves counted on the busiest page image; more than staves_detected hints at a flattened choir score",
                },
            },
        },
        "pages": {"type": "array", "items": _PAGE},
    },
    "required": ["job_id", "musicxml", "metadata", "pages"],
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
    result: dict, content: list, *, job_id: str, previews: list[bool], staff_estimates: list[int | None]
) -> tuple[list, dict]:
    """``(content, structured_content)`` for a successful recognize_sheet / recognize_sheets.

    ``content`` is passed through untouched. ``previews`` says per input page whether a preview was
    stored; ``staff_estimates`` is the staff count per page image (None: unreadable).
    """
    metadata = dict(result["metadata"])
    counted = [n for n in staff_estimates if n is not None]
    if counted:
        metadata["staff_systems_estimate"] = max(counted)
    return content, {
        "job_id": job_id,
        "musicxml": result["musicxml"],
        "metadata": metadata,
        "pages": _pages(result, previews),
    }


def present_preview(job_id: str, page: int, chunk: dict) -> tuple[list, dict]:
    """``(content, structured_content)`` for the app-only preview read.

    Only the app decodes the pixels, so the text block just says which bytes were sent and keeps
    the base64 out of any model context.
    """
    end = chunk["offset"] + chunk["length"]
    text = f"Source preview of page {page} fetched for the Recognition Review (bytes {chunk['offset']}-{end} of {chunk['byte_length']})."
    return [TextContent(type="text", text=text)], {"job_id": job_id, "page": page, **chunk}


def _pages(result: dict, previews: list[bool]) -> list[dict]:
    reported = result.get("_pages")
    if reported is None:
        # recognize_sheet reports one page; an engine that gave no per-page detail leaves it unknown.
        single = len(previews) == 1
        reported = [
            {
                "index": i,
                "staves_detected": result["metadata"].get("staves_detected") if single else None,
                "measures": result["metadata"].get("measures") if single else None,
            }
            for i in range(1, len(previews) + 1)
        ]
    return [{**page, "has_preview": has} for page, has in zip(reported, previews)]

