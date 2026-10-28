import asyncio
import json
import logging
import os

import mcp.server.stdio
from mcp.server import Server
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations
from sheet_music_mcp_core.annotations import READ_ONLY, SESSION_STATE
from sheet_music_mcp_core.content import error_content, processing_error_content
from sheet_music_mcp_core.measures import MEASURES_PROPERTY
from sheet_music_mcp_core.params import aliased
from sheet_music_mcp_core.references import (
    DESCRIBE_SCORE_TOOL,
    describe_score_tool,
    exactly_one,
    score_input_properties,
)
from sheet_music_mcp_core.references import load_score as read_score
from sheet_music_mcp_core.ui import PackageAssetSource, UiRegistry, UiResource
from sheet_music_mcp_core.wiring import make_handlers, make_resource_handlers

from . import __version__
from .engine import (
    ProcessingError,
    analyze_recording,
    describe_session,
    get_position,
    get_session_score,
    health_check,
    list_sessions,
    load_score,
    start_monitoring,
    start_practice,
    stop_monitoring,
)
from .presenter import (
    ANALYSIS_OUTPUT_SCHEMA,
    POSITION_OUTPUT_SCHEMA,
    SCORE_OUTPUT_SCHEMA,
    SESSION_OUTPUT_SCHEMA,
    present_analysis,
    present_position,
    present_score,
    present_session,
)
from .utils import validate_audio_path, validate_musicxml, validate_session_id

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Sent to the client at initialize (docs/conventions.md, Server Instructions).
INSTRUCTIONS = (
    "Follows a singer through a score from the microphone. Flow: start_practice (score and part "
    "as an ID, name or voice such as 'Alto'; it loads the score and opens the microphone, like "
    "load_score then start_monitoring), get_current_position repeatedly, then stop_monitoring "
    "for the summary and its highlights (where the singer went flat or sharp). "
    "measures: [start, end] (printed bar numbers) practises or analyses only those bars. "
    "Always call stop_monitoring when done: it closes the microphone. Idle sessions close after "
    "PITCH_SESSION_IDLE_MINUTES (default 10); stop_monitoring still returns their summary, and "
    "list_sessions shows the open ones. analyze_recording scores a recorded 16-bit WAV instead. "
    "Real-time monitoring needs PortAudio; see health_check. "
    "Prefer musicxml_path over inline musicxml and pass on the score paths other tools return; "
    "describe_score lists the part IDs cheaply."
)


PRACTICE_COACH = UiResource(
    "ui://pitch/practice-coach",
    "practice-coach.html",
    "Practice Coach",
    "Follows the singer through the score with live pitch feedback, and shows a recording's accuracy.",
)

# Reads the HTML packaged under pitch_mcp/ui/assets/; tests replace ui_registry with in-memory
# assets. Without a UI build the coach is hidden and the tools carry no _meta.ui.
DEFAULT_UI_REGISTRY = UiRegistry([PRACTICE_COACH], PackageAssetSource("pitch_mcp"))
ui_registry = DEFAULT_UI_REGISTRY


async def list_tools():
    return [
        Tool(
            name="analyze_recording",
            title="Analyze a recording",
            annotations=ToolAnnotations(**READ_ONLY),
            description=(
                "Analyse a pre-recorded WAV file against a reference score. "
                "Returns per-note pitch accuracy, a summary histogram and highlights: the worst "
                "runs of flat or sharp notes in plain words. With measures, the recording is "
                "compared against those bars only."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "audio_path": {
                        "type": "string",
                        "description": "Absolute path to a 16-bit PCM WAV file",
                    },
                    **score_input_properties(what="the reference score"),
                    "part": {
                        "type": "string",
                        "description": "Part to compare against: a part ID, name or voice (e.g. 'P1', 'Soprano', 'S')",
                    },
                    "part_id": {
                        "type": "string",
                        "description": "(Deprecated: use `part`) Part to compare against.",
                    },
                    **MEASURES_PROPERTY,
                },
                "required": ["audio_path"],
                "anyOf": [{"required": ["part"]}, {"required": ["part_id"]}],
                **exactly_one(),
            },
            output_schema=ANALYSIS_OUTPUT_SCHEMA,
            meta=ui_registry.meta_for(PRACTICE_COACH),
        ),
        Tool(
            name="load_score",
            title="Load score for practice",
            annotations=ToolAnnotations(**SESSION_STATE),
            description=(
                "Load a reference MusicXML score into a named session. "
                "Returns a session_id to use with start_monitoring. "
                "start_practice does this and start_monitoring in one call."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    **score_input_properties(what="the score to practise"),
                    "part": {
                        "type": "string",
                        "description": "Part to monitor: a part ID, name or voice (e.g. 'P1', 'Soprano', 'S')",
                    },
                    "part_id": {
                        "type": "string",
                        "description": "(Deprecated: use `part`) Part to monitor.",
                    },
                    **MEASURES_PROPERTY,
                },
                "required": [],
                "anyOf": [{"required": ["part"]}, {"required": ["part_id"]}],
                **exactly_one(),
            },
            output_schema=SESSION_OUTPUT_SCHEMA,
            meta=ui_registry.meta_for(PRACTICE_COACH),
        ),
        Tool(
            name="start_practice",
            title="Start practice",
            annotations=ToolAnnotations(**SESSION_STATE),
            description=(
                "Load a score and open the microphone in one call (load_score + "
                "start_monitoring). Returns the session_id with the part, measure count and "
                "duration. Poll get_current_position, then call stop_monitoring for the summary."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    **score_input_properties(what="the score to practise"),
                    "part": {
                        "type": "string",
                        "description": "Part to sing: a part ID, name or voice (e.g. 'P1', 'Soprano', 'S')",
                    },
                    "tempo_bpm": {
                        "type": "integer",
                        "description": "Override tempo in BPM (default: score tempo)",
                    },
                    **MEASURES_PROPERTY,
                },
                "required": ["part"],
                **exactly_one(),
            },
            output_schema=SESSION_OUTPUT_SCHEMA,
            meta=ui_registry.meta_for(PRACTICE_COACH),
        ),
        DESCRIBE_SCORE_TOOL,
        Tool(
            name="start_monitoring",
            title="Start listening (microphone)",
            annotations=ToolAnnotations(**SESSION_STATE),
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
            title="Current singing position",
            annotations=ToolAnnotations(**READ_ONLY),
            description=(
                "Poll the current score position and pitch accuracy. "
                "Call repeatedly while monitoring. Returns measure, beat, and accuracy. "
                "Each call keeps the session from timing out."
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
            output_schema=POSITION_OUTPUT_SCHEMA,
        ),
        Tool(
            name="stop_monitoring",
            title="Stop listening",
            annotations=ToolAnnotations(**SESSION_STATE),
            description=(
                "Stop the microphone and return a session summary. "
                "The session is cleaned up after this call. If the session already closed "
                "after being idle, returns the summary kept then, with timed_out: true."
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
            name="list_sessions",
            title="Practice sessions",
            annotations=ToolAnnotations(**READ_ONLY),
            description=(
                "List the open practice sessions: session_id, part, state ('loaded' or "
                "'monitoring' when the microphone is on) and idle_seconds. Sessions close after "
                "PITCH_SESSION_IDLE_MINUTES idle (default 10, shown as idle_timeout_minutes; 0 = never)."
            ),
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="get_score_for_session",
            title="Score of a practice session",
            annotations=ToolAnnotations(**READ_ONLY),
            description=(
                "For the Practice Coach app only: the MusicXML an open session practises, so the "
                "app can draw it. Takes a session_id, never a path."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID from load_score"},
                },
                "required": ["session_id"],
                "additionalProperties": False,
            },
            output_schema=SCORE_OUTPUT_SCHEMA,
            meta=ui_registry.meta_for(PRACTICE_COACH, app_only=True),
        ),
        Tool(
            name="list_capabilities",
            title="Pitch capabilities",
            annotations=ToolAnnotations(**READ_ONLY),
            description="List supported formats, tools, and backend information for this server",
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="health_check",
            title="Pitch health check",
            annotations=ToolAnnotations(**READ_ONLY),
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


async def _reference_score(arguments: dict, ctx) -> str:
    """The score from `musicxml` or `musicxml_path`, checked like inline MusicXML always was.

    Raises ProcessingError: the core's path errors, or INVALID_INPUT for text that is not MusicXML.
    """
    musicxml = await read_score(arguments, ctx)
    ok, err = validate_musicxml(musicxml)
    if not ok:
        raise ProcessingError(err, "INVALID_INPUT")
    return musicxml


async def _plain_tool(name: str, arguments: dict, ctx=None) -> list:
    if name == "describe_score":
        try:
            return await describe_score_tool(arguments, ctx)
        except ProcessingError as e:
            return processing_error_content(e)

    elif name == "start_monitoring":
        session_id = arguments.get("session_id", "")
        tempo_bpm = arguments.get("tempo_bpm")

        ok, err = validate_session_id(session_id)
        if not ok:
            return error_content(err, "INVALID_INPUT")

        try:
            result = start_monitoring(session_id, tempo_bpm)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except ProcessingError as e:
            return processing_error_content(e)
        except Exception as e:
            logger.error("start_monitoring unexpected error: %s", e)
            return error_content(f"Unexpected error: {e}", "PROCESSING_FAILED")

    elif name == "stop_monitoring":
        session_id = arguments.get("session_id", "")

        ok, err = validate_session_id(session_id)
        if not ok:
            return error_content(err, "INVALID_INPUT")

        try:
            result = stop_monitoring(session_id)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except ProcessingError as e:
            return processing_error_content(e)
        except Exception as e:
            logger.error("stop_monitoring unexpected error: %s", e)
            return error_content(f"Unexpected error: {e}", "PROCESSING_FAILED")

    elif name == "list_sessions":
        result = list_sessions()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "list_capabilities":
        # Check aubio availability
        pitch_backend = _active_backend()
        pitch_backend_version = _backend_version(pitch_backend)

        # Check microphone availability
        mic_available = _check_microphone()

        result = {
            "server": "pitch-mcp",
            "version": __version__,
            "input_formats": ["musicxml", "mxl", "wav"],
            "input_parameters": ["musicxml", "musicxml_path", "measures"],
            "output_formats": ["json"],
            "tools": [
                "analyze_recording",
                "load_score",
                "start_practice",
                "describe_score",
                "start_monitoring",
                "get_current_position",
                "stop_monitoring",
                "list_sessions",
                "get_score_for_session",
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


def _error(content: list) -> CallToolResult:
    # isError, so clients skip output_schema validation of the absent structured content.
    return CallToolResult(content=content, is_error=True)


def _result(presented: tuple[list, dict]) -> CallToolResult:
    content, structured = presented
    return CallToolResult(content=content, structured_content=structured)


async def _analyze_recording(arguments: dict, ctx) -> CallToolResult:
    # audio_path is not confined to the read roots (Wave 2 covers scores only, W2-3).
    audio_path = arguments.get("audio_path", "")
    ok, err = validate_audio_path(audio_path)
    if not ok:
        code = "FILE_NOT_FOUND" if "not found" in err else "UNSUPPORTED_FORMAT"
        return _error(error_content(err, code))

    try:
        musicxml = await _reference_score(arguments, ctx)
        part_id = aliased(arguments, "part", "part_id")
    except ProcessingError as e:
        return _error(processing_error_content(e))
    if not part_id:
        return _error(error_content("part is required.", "INVALID_INPUT"))

    try:
        result = analyze_recording(audio_path, musicxml, part_id, **_measures(arguments))
        return _result(present_analysis(result))
    except ProcessingError as e:
        return _error(processing_error_content(e))
    except Exception as e:
        logger.error("analyze_recording unexpected error: %s", e)
        return _error(error_content(f"Unexpected error: {e}", "PROCESSING_FAILED"))


async def _load_score(arguments: dict, ctx) -> CallToolResult:
    try:
        musicxml = await _reference_score(arguments, ctx)
        part_id = aliased(arguments, "part", "part_id")
    except ProcessingError as e:
        return _error(processing_error_content(e))
    if not part_id:
        return _error(error_content("part is required.", "INVALID_INPUT"))

    try:
        result = load_score(musicxml, part_id, **_measures(arguments))
        return _result(present_session(result, describe_session(result["session_id"])))
    except ProcessingError as e:
        return _error(processing_error_content(e))
    except Exception as e:
        logger.error("load_score unexpected error: %s", e)
        return _error(error_content(f"Unexpected error: {e}", "PROCESSING_FAILED"))


async def _start_practice(arguments: dict, ctx) -> CallToolResult:
    try:
        musicxml = await _reference_score(arguments, ctx)
    except ProcessingError as e:
        return _error(processing_error_content(e))
    part_id = arguments.get("part")
    if not part_id:
        return _error(error_content("part is required.", "INVALID_INPUT"))

    try:
        result = start_practice(
            musicxml, part_id, tempo_bpm=arguments.get("tempo_bpm"), **_measures(arguments)
        )
        return _result(present_session(result, describe_session(result["session_id"])))
    except ProcessingError as e:
        return _error(processing_error_content(e))
    except Exception as e:
        logger.error("start_practice unexpected error: %s", e)
        return _error(error_content(f"Unexpected error: {e}", "PROCESSING_FAILED"))


async def _get_current_position(arguments: dict, ctx) -> CallToolResult:
    session_id = arguments.get("session_id", "")

    ok, err = validate_session_id(session_id)
    if not ok:
        return _error(error_content(err, "INVALID_INPUT"))

    try:
        return _result(present_position(get_position(session_id)))
    except ProcessingError as e:
        return _error(processing_error_content(e))
    except Exception as e:
        logger.error("get_current_position unexpected error: %s", e)
        return _error(error_content(f"Unexpected error: {e}", "PROCESSING_FAILED"))


async def _get_score_for_session(arguments: dict, ctx) -> CallToolResult:
    session_id = arguments.get("session_id", "")

    ok, err = validate_session_id(session_id)
    if not ok:
        return _error(error_content(err, "INVALID_INPUT"))

    try:
        return _result(present_score(get_session_score(session_id)))
    except ProcessingError as e:
        return _error(processing_error_content(e))
    except Exception as e:
        logger.error("get_score_for_session unexpected error: %s", e)
        return _error(error_content(f"Unexpected error: {e}", "PROCESSING_FAILED"))


_RESULT_TOOLS = {
    "analyze_recording": _analyze_recording,
    "load_score": _load_score,
    "start_practice": _start_practice,
    "get_current_position": _get_current_position,
    "get_score_for_session": _get_score_for_session,
}


async def call_tool(name: str, arguments: dict, ctx=None) -> list:
    """The tool's content blocks: what every client sees, structured content aside."""
    return (await call_tool_result(name, arguments, ctx)).content


async def call_tool_result(name: str, arguments: dict, ctx=None) -> CallToolResult:
    """The full result the server sends, ``structuredContent`` included."""
    if name in _RESULT_TOOLS:
        return await _RESULT_TOOLS[name](arguments, ctx)
    return CallToolResult(content=await _plain_tool(name, arguments, ctx))


def _measures(arguments: dict) -> dict:
    """``{"measures": ...}`` when the call names a range, else nothing: the engine call without
    one is exactly the one earlier releases made."""
    return {"measures": arguments["measures"]} if arguments.get("measures") is not None else {}


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


class _CurrentUiRegistry:
    """Serves whichever registry ``ui_registry`` holds at request time, so tests can swap it."""

    def list_resources(self):
        return ui_registry.list_resources()

    def read(self, uri: str):
        return ui_registry.read(uri)


_on_list_tools, _on_call_tool = make_handlers(list_tools, call_tool_result, pass_context=True, logger=logger)
_on_list_resources, _on_read_resource = make_resource_handlers(_CurrentUiRegistry(), logger=logger)

app = Server(
    "pitch-mcp",
    instructions=INSTRUCTIONS,
    on_list_tools=_on_list_tools,
    on_call_tool=_on_call_tool,
    on_list_resources=_on_list_resources,
    on_read_resource=_on_read_resource,
)


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
