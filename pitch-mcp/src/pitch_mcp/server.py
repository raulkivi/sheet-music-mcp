import asyncio
import json
import logging
import os

import jsonschema
import mcp.server.stdio
from mcp.server import Server
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, TextContent, Tool

from .engine import (
    ProcessingError,
    analyze_recording,
    get_position,
    health_check,
    load_score,
    start_monitoring,
    stop_monitoring,
)
from .utils import validate_audio_path, validate_musicxml, validate_session_id

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def list_tools():
    return [
        Tool(
            name="analyze_recording",
            description=(
                "Analyse a pre-recorded WAV file against a reference score. "
                "Returns per-note pitch accuracy and a summary histogram."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "audio_path": {
                        "type": "string",
                        "description": "Absolute path to a 16-bit PCM WAV file",
                    },
                    "musicxml": {
                        "type": "string",
                        "description": "MusicXML document as a string",
                    },
                    "part_id": {
                        "type": "string",
                        "description": "Part ID to compare against (e.g. 'Soprano')",
                    },
                },
                "required": ["audio_path", "musicxml", "part_id"],
            },
        ),
        Tool(
            name="load_score",
            description=(
                "Load a reference MusicXML score into a named session. "
                "Returns a session_id to use with start_monitoring."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "musicxml": {
                        "type": "string",
                        "description": "MusicXML document as a string",
                    },
                    "part_id": {
                        "type": "string",
                        "description": "Part ID to monitor (e.g. 'Soprano')",
                    },
                },
                "required": ["musicxml", "part_id"],
            },
        ),
        Tool(
            name="start_monitoring",
            description=(
                "Open the microphone and begin pitch detection against the loaded score. "
                "Requires a session_id from load_score."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID from load_score",
                    },
                    "tempo_bpm": {
                        "type": "integer",
                        "description": "Override tempo in BPM (default: score tempo)",
                    },
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="get_current_position",
            description=(
                "Poll the current score position and pitch accuracy. "
                "Call repeatedly while monitoring. Returns measure, beat, and accuracy."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID from load_score",
                    },
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="stop_monitoring",
            description=(
                "Stop the microphone and return a session summary. "
                "The session is cleaned up after this call."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID from load_score",
                    },
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="list_capabilities",
            description="List supported formats, tools, and backend information for this server",
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="health_check",
            description=(
                "Check that all runtime dependencies are available and report their status. "
                "Use this to verify the server is set up correctly. "
                "Returns status for offline analysis (librosa/pYIN) and real-time monitoring "
                "(sounddevice/portaudio). Missing portaudio is a warning, not an error — "
                "offline analysis still works without it."
            ),
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
    ]


def _error(message: str, code: str) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps({"error": message, "error_code": code}))]


async def call_tool(name: str, arguments: dict):
    if name == "analyze_recording":
        audio_path = arguments.get("audio_path", "")
        musicxml = arguments.get("musicxml", "")
        part_id = arguments.get("part_id", "")

        ok, err = validate_audio_path(audio_path)
        if not ok:
            code = "FILE_NOT_FOUND" if "not found" in err else "UNSUPPORTED_FORMAT"
            return _error(err, code)

        ok, err = validate_musicxml(musicxml)
        if not ok:
            return _error(err, "INVALID_INPUT")

        if not part_id:
            return _error("part_id is required.", "INVALID_INPUT")

        try:
            result = analyze_recording(audio_path, musicxml, part_id)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except ProcessingError as e:
            return _error(str(e), e.error_code)
        except Exception as e:
            logger.error("analyze_recording unexpected error: %s", e)
            return _error(f"Unexpected error: {e}", "PROCESSING_FAILED")

    elif name == "load_score":
        musicxml = arguments.get("musicxml", "")
        part_id = arguments.get("part_id", "")

        ok, err = validate_musicxml(musicxml)
        if not ok:
            return _error(err, "INVALID_INPUT")

        if not part_id:
            return _error("part_id is required.", "INVALID_INPUT")

        try:
            result = load_score(musicxml, part_id)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except ProcessingError as e:
            return _error(str(e), e.error_code)
        except Exception as e:
            logger.error("load_score unexpected error: %s", e)
            return _error(f"Unexpected error: {e}", "PROCESSING_FAILED")

    elif name == "start_monitoring":
        session_id = arguments.get("session_id", "")
        tempo_bpm = arguments.get("tempo_bpm")

        ok, err = validate_session_id(session_id)
        if not ok:
            return _error(err, "INVALID_INPUT")

        try:
            result = start_monitoring(session_id, tempo_bpm)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except ProcessingError as e:
            return _error(str(e), e.error_code)
        except Exception as e:
            logger.error("start_monitoring unexpected error: %s", e)
            return _error(f"Unexpected error: {e}", "PROCESSING_FAILED")

    elif name == "get_current_position":
        session_id = arguments.get("session_id", "")

        ok, err = validate_session_id(session_id)
        if not ok:
            return _error(err, "INVALID_INPUT")

        try:
            result = get_position(session_id)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except ProcessingError as e:
            return _error(str(e), e.error_code)
        except Exception as e:
            logger.error("get_current_position unexpected error: %s", e)
            return _error(f"Unexpected error: {e}", "PROCESSING_FAILED")

    elif name == "stop_monitoring":
        session_id = arguments.get("session_id", "")

        ok, err = validate_session_id(session_id)
        if not ok:
            return _error(err, "INVALID_INPUT")

        try:
            result = stop_monitoring(session_id)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except ProcessingError as e:
            return _error(str(e), e.error_code)
        except Exception as e:
            logger.error("stop_monitoring unexpected error: %s", e)
            return _error(f"Unexpected error: {e}", "PROCESSING_FAILED")

    elif name == "list_capabilities":
        # Check aubio availability
        pitch_backend = _active_backend()
        pitch_backend_version = _backend_version(pitch_backend)

        # Check microphone availability
        mic_available = _check_microphone()

        result = {
            "server": "pitch-mcp",
            "version": "0.2.0",
            "input_formats": ["musicxml", "wav"],
            "output_formats": ["json"],
            "tools": [
                "analyze_recording",
                "load_score",
                "start_monitoring",
                "get_current_position",
                "stop_monitoring",
                "list_capabilities",
                "health_check",
            ],
            "pitch_backend": pitch_backend,
            "pitch_backend_version": pitch_backend_version,
            "microphone_available": mic_available,
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "health_check":
        result = health_check()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    raise ValueError(f"Unknown tool: {name}")


def _active_backend() -> str:
    import os
    return os.environ.get("PITCH_BACKEND", "librosa").lower()


def _backend_version(backend: str) -> str:
    try:
        if backend == "librosa":
            import librosa
            return getattr(librosa, "__version__", "unknown")
        elif backend == "crepe":
            import crepe
            return getattr(crepe, "__version__", "unknown")
    except Exception:
        pass
    return "unavailable"


def _check_microphone() -> bool:
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        return any(d["max_input_channels"] > 0 for d in devices)
    except Exception:
        return False


def _error_result(message: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=message)], is_error=True)


async def _on_list_tools(ctx, params) -> ListToolsResult:
    return ListToolsResult(tools=await list_tools())


async def _on_call_tool(ctx, params: CallToolRequestParams) -> CallToolResult:
    # mcp 2.x low-level handlers neither validate input nor catch tool errors;
    # keep the 1.x decorator behaviour clients rely on.
    arguments = params.arguments or {}
    tool = next((t for t in await list_tools() if t.name == params.name), None)
    if tool is not None:
        try:
            jsonschema.validate(instance=arguments, schema=tool.input_schema)
        except jsonschema.ValidationError as e:
            return _error_result(f"Input validation error: {e.message}")
    try:
        return CallToolResult(content=await call_tool(params.name, arguments))
    except Exception as e:
        logger.error("Tool %s failed: %s", params.name, e)
        return _error_result(str(e))


app = Server("pitch-mcp", on_list_tools=_on_list_tools, on_call_tool=_on_call_tool)


def main():
    """Entry point for pitch-mcp."""
    logger.info("pitch-mcp starting up…")

    # Run health check at startup and log results
    status = health_check()
    if status["status"] == "ok":
        librosa_ver = status["offline_analysis"]["librosa_version"]
        logger.info(
            "pitch-mcp ready — librosa %s (offline analysis) + sounddevice (real-time monitoring)",
            librosa_ver,
        )
    elif status["status"] == "degraded":
        librosa_ver = status["offline_analysis"]["librosa_version"]
        logger.info("pitch-mcp ready — librosa %s (offline analysis only)", librosa_ver)
        logger.warning(
            "Real-time monitoring unavailable: sounddevice/portaudio not found. "
            "Install libportaudio2 to enable microphone features."
        )
    else:
        logger.error(
            "pitch-mcp startup problem: %s",
            status["summary"],
        )

    async def _run():
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
