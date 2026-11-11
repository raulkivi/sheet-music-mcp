"""Engine results to tool results: ``content`` for every client, ``structuredContent`` for apps.

``content`` of ``get_parts`` and ``synthesize`` is exactly what these tools returned before MCP
Apps, so text-only clients see no change (tests/test_content_golden.py, AC-S4). The structured
side is what the Practice Player reads. The two app-only tools keep a one-line text block: only
the app reads their data, and the base64 audio or the MusicXML must stay out of model context.
"""

from __future__ import annotations

import json

from mcp.types import TextContent

_PART = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "Stable MusicXML score-part id"},
        "name": {"type": "string"},
        "included": {"type": "boolean", "description": "Whether the part is in the rendered track"},
        "gain": {"type": "number", "minimum": 0, "description": "Volume used: 0.0 silent, 1.0 normal, 2.0 max"},
    },
    "required": ["id", "name", "included", "gain"],
}

SYNTH_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "audio_id": {"type": "string", "description": "Opaque handle; read the WAV with read_audio_chunk"},
        "duration_seconds": {"type": "number", "minimum": 0},
        "sample_rate": {"type": "integer", "minimum": 1},
        "channels": {"type": "integer", "minimum": 1},
        "byte_length": {"type": "integer", "minimum": 0, "description": "Size of the WAV file"},
        "parts": {"type": "array", "items": _PART, "description": "Every part of the score, in score order"},
        "tempo_factor": {"type": "number"},
    },
    "required": ["audio_id", "duration_seconds", "sample_rate", "channels", "byte_length", "parts", "tempo_factor"],
}

PARTS_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "parts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "measure_count": {"type": "integer", "minimum": 0},
                },
                "required": ["id", "name", "measure_count"],
            },
        },
    },
    "required": ["parts"],
}

CHUNK_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "artifact_id": {"type": "string"},
        "offset": {"type": "integer", "minimum": 0},
        "length": {"type": "integer", "minimum": 0, "description": "Bytes returned in this chunk"},
        "byte_length": {"type": "integer", "minimum": 0, "description": "Size of the whole WAV"},
        "eof": {"type": "boolean"},
        "data_b64": {"type": "string", "description": "This chunk, base64-encoded"},
    },
    "required": ["artifact_id", "offset", "length", "byte_length", "eof", "data_b64"],
}

SCORE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "audio_id": {"type": "string"},
        "musicxml": {"type": "string", "description": "The score the audio was rendered from"},
    },
    "required": ["audio_id", "musicxml"],
}


def present_parts(parts: dict) -> tuple[list, dict]:
    """``(content, structured_content)`` for get_parts: the same ``{"parts": [...]}`` twice."""
    return _json_text(parts), dict(parts)


def present_track(content: list, *, audio_id: str, duration: float, wav_format: tuple[int, int],
                  byte_length: int, parts: list[dict], tempo_factor: float) -> tuple[list, dict]:
    """``(content, structured_content)`` for synthesize; ``content`` passes through unchanged."""
    sample_rate, channels = wav_format
    return content, {
        "audio_id": audio_id,
        "duration_seconds": round(duration, 2),
        "sample_rate": sample_rate,
        "channels": channels,
        "byte_length": byte_length,
        "parts": parts,
        "tempo_factor": float(tempo_factor),
    }


def present_chunk(chunk: dict) -> tuple[list, dict]:
    """``(content, structured_content)`` for the app-only audio chunk read."""
    end = chunk["offset"] + chunk["length"]
    text = f"Audio bytes {chunk['offset']}-{end} of {chunk['byte_length']} sent to the Practice Player."
    return [TextContent(type="text", text=text)], dict(chunk)


def present_score(score: dict) -> tuple[list, dict]:
    """``(content, structured_content)`` for the app-only score fetch."""
    size_kb = max(1, round(len(score["musicxml"].encode("utf-8")) / 1024))
    text = f"Score ({size_kb} kB) fetched for the Practice Player."
    return [TextContent(type="text", text=text)], dict(score)


def _json_text(data: dict) -> list:
    return [TextContent(type="text", text=json.dumps(data, indent=2))]
