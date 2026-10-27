import asyncio
import json
import logging
import os

import mcp.server.stdio
from mcp.server import Server
from mcp.types import TextContent, Tool, ToolAnnotations
from sheet_music_mcp_core.annotations import READ_ONLY, WRITES_FILE
from sheet_music_mcp_core.content import error_content, file_link, processing_error_content
from sheet_music_mcp_core.params import aliased
from sheet_music_mcp_core.wiring import make_handlers

from . import __version__
from .engine import ProcessingError, extract_midi, parse_parts, resolve_part_ids, synthesize_midi
from .utils import generate_output_path, validate_musicxml, validate_tempo_factor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Sent to the client at initialize (docs/conventions.md, Server Instructions).
INSTRUCTIONS = (
    "Renders chosen voice parts of a MusicXML score to a WAV practice track. "
    "Call synthesize with parts as IDs, names or voices (e.g. 'P1', 'Alto', 'S'; default: all "
    "parts) and tempo_factor (0.75 = 75% speed); get_parts lists the parts. Needs an SF2 "
    "soundfont in SYNTH_SOUNDFONT_PATH; run health_check if synthesis fails."
)


async def list_tools():
    return [
        Tool(
            name="get_parts",
            title="List voice parts",
            annotations=ToolAnnotations(**READ_ONLY),
            description="List all voice parts available in a MusicXML score",
            input_schema={
                "type": "object",
                "properties": {
                    "musicxml": {
                        "type": "string",
                        "description": "MusicXML document as a string",
                    }
                },
                "required": ["musicxml"],
            },
        ),
        Tool(
            name="synthesize",
            title="Play voice parts",
            annotations=ToolAnnotations(**WRITES_FILE),
            description=(
                "Synthesize audio from a MusicXML score. "
                "Optionally select specific voice parts and adjust the tempo."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "musicxml": {
                        "type": "string",
                        "description": "MusicXML document as a string",
                    },
                    "parts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Parts to include, each a part ID, name or voice "
                            "(e.g. 'P1', 'Soprano', 'S'). Default: all parts."
                        ),
                    },
                    "part_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "(Deprecated: use `parts`) Parts to include.",
                    },
                    "tempo_factor": {
                        "type": "number",
                        "description": (
                            "Tempo multiplier: 1.0 = score tempo, 0.75 = 75% speed. "
                            "Valid range: 0.25–4.0. Default: 1.0"
                        ),
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Path to write WAV file (auto-generated if omitted)",
                    },
                },
                "required": ["musicxml"],
            },
        ),
        Tool(
            name="list_capabilities",
            title="Synth capabilities",
            annotations=ToolAnnotations(**READ_ONLY),
            description="List supported formats and available tools for this synthesis server",
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="health_check",
            title="Synth health check",
            annotations=ToolAnnotations(**READ_ONLY),
            description=(
                "Check whether all runtime dependencies are available and correctly configured. "
                "Returns a human-readable status summary. Call this first to verify the server "
                "is ready before attempting synthesis."
            ),
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
    ]


async def call_tool(name: str, arguments: dict):
    if name == "get_parts":
        musicxml = arguments.get("musicxml", "")

        ok, err = validate_musicxml(musicxml)
        if not ok:
            return error_content(err, "INVALID_INPUT")

        try:
            parts = parse_parts(musicxml)
            return [TextContent(type="text", text=json.dumps({"parts": parts}, indent=2))]
        except ProcessingError as e:
            return processing_error_content(e)
        except Exception as e:
            logger.error("get_parts unexpected error: %s", e)
            return error_content(f"Unexpected error: {e}", "PROCESSING_FAILED")

    elif name == "synthesize":
        musicxml = arguments.get("musicxml", "")
        tempo_factor = arguments.get("tempo_factor", 1.0)
        output_path = arguments.get("output_path")

        ok, err = validate_musicxml(musicxml)
        if not ok:
            return error_content(err, "INVALID_INPUT")

        ok, err = validate_tempo_factor(tempo_factor)
        if not ok:
            return error_content(err, "INVALID_PARAMETER")

        try:
            requested = aliased(arguments, "parts", "part_ids")  # None → all parts
        except ProcessingError as e:
            return processing_error_content(e)
        if requested is not None and not isinstance(requested, list):
            return error_content("parts must be a list of strings", "INVALID_PARAMETER")

        part_ids = None
        if requested is not None:
            try:
                part_ids = resolve_part_ids(musicxml, requested)
            except ProcessingError as e:
                return processing_error_content(e)

        try:
            resolved_output = generate_output_path(output_path)
        except ValueError as e:
            return error_content(str(e), "INVALID_PARAMETER")

        try:
            midi_bytes = extract_midi(musicxml, part_ids, tempo_factor)
        except ProcessingError as e:
            return processing_error_content(e)
        except Exception as e:
            logger.error("extract_midi unexpected error: %s", e)
            return error_content(f"MIDI extraction failed: {e}", "PROCESSING_FAILED")

        try:
            duration = synthesize_midi(midi_bytes, resolved_output)
        except ProcessingError as e:
            return processing_error_content(e)
        except Exception as e:
            logger.error("synthesize_midi unexpected error: %s", e)
            return error_content(f"Synthesis failed: {e}", "PROCESSING_FAILED")

        # Resolve the list of included part IDs for the response
        if part_ids is not None:
            parts_included = part_ids
        else:
            try:
                parts_included = [p["id"] for p in parse_parts(musicxml)]
            except Exception:
                parts_included = []

        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "audio_path": resolved_output,
                        "format": "wav",
                        "duration_seconds": round(duration, 2),
                        "parts_included": parts_included,
                        "tempo_factor": tempo_factor,
                    },
                    indent=2,
                ),
            ),
            # docs/conventions.md, Result Content: link the written file after the JSON.
            *([file_link(resolved_output, "audio/wav")] if os.path.isfile(resolved_output) else []),
        ]

    elif name == "list_capabilities":
        soundfont_path = os.environ.get("SYNTH_SOUNDFONT_PATH", "")
        soundfont_loaded = bool(soundfont_path) and os.path.exists(soundfont_path)

        fluidsynth_available = True
        try:
            import fluidsynth  # noqa: F401
        except (ImportError, OSError):
            fluidsynth_available = False

        backend_version = "unknown"
        try:
            import subprocess
            r = subprocess.run(
                ["fluidsynth", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            # FluidSynth prints e.g. "FluidSynth version 2.3.4\n..."
            first_line = (r.stdout + r.stderr).strip().split("\n")[0]
            backend_version = first_line.replace("FluidSynth version ", "").strip() or "unknown"
        except Exception:
            pass

        result = {
            "server": "synth-mcp",
            "version": __version__,
            "input_formats": ["musicxml"],
            "output_formats": ["wav"],
            "tools": ["get_parts", "synthesize", "list_capabilities", "health_check"],
            "backend": "fluidsynth",
            "backend_version": backend_version,
            "soundfont_loaded": soundfont_loaded,
            "soundfont_path": soundfont_path if soundfont_loaded else None,
            "fluidsynth_available": fluidsynth_available,
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "health_check":
        lines = ["synth-mcp health check\n" + "=" * 22]

        # Soundfont
        soundfont_path = os.environ.get("SYNTH_SOUNDFONT_PATH", "")
        if not soundfont_path:
            sf_status = "MISSING — SYNTH_SOUNDFONT_PATH is not set"
            sf_ok = False
        elif not os.path.exists(soundfont_path):
            sf_status = f"MISSING — file not found at {soundfont_path!r}"
            sf_ok = False
        else:
            sf_status = f"OK — {soundfont_path}"
            sf_ok = True
        lines.append(f"Soundfont:    {sf_status}")

        if not sf_ok:
            lines.append(
                "\n  To fix: download an SF2 soundfont, e.g. TimGM6mb.sf2 from\n"
                "  https://sourceforge.net/projects/timidity/files/\n"
                "  Then add to your LLM client config:\n"
                '    "env": {"SYNTH_SOUNDFONT_PATH": "/path/to/soundfont.sf2"}'
            )

        # FluidSynth Python binding
        fluidsynth_ok = True
        try:
            import fluidsynth  # noqa: F401
        except (ImportError, OSError) as e:
            fluidsynth_ok = False
            lines.append(f"FluidSynth:   MISSING — {e}")
        if fluidsynth_ok:
            lines.append("FluidSynth:   OK")

        # music21
        music21_ok = True
        try:
            import music21  # noqa: F401
        except ImportError as e:
            music21_ok = False
            lines.append(f"music21:      MISSING — {e}")
        if music21_ok:
            lines.append("music21:      OK")

        # Overall status
        all_ok = sf_ok and fluidsynth_ok and music21_ok
        status = "READY" if all_ok else "NOT READY"
        lines.append(f"\nOverall:      {status}")
        if not all_ok:
            lines.append(
                "Fix the issues above, then restart the server and run health_check again."
            )

        return [TextContent(type="text", text="\n".join(lines))]

    raise ValueError(f"Unknown tool: {name}")


_on_list_tools, _on_call_tool = make_handlers(list_tools, call_tool, logger=logger)

app = Server(
    "synth-mcp",
    instructions=INSTRUCTIONS,
    on_list_tools=_on_list_tools,
    on_call_tool=_on_call_tool,
)


def main():
    """Entry point for synth-mcp."""
    soundfont_path = os.environ.get("SYNTH_SOUNDFONT_PATH", "")
    if not soundfont_path:
        logger.warning(
            "SYNTH_SOUNDFONT_PATH is not set — synthesis will fail.\n"
            "  Fix: download TimGM6mb.sf2 from https://sourceforge.net/projects/timidity/files/\n"
            "  Then add to your LLM client config under mcpServers > synth > env:\n"
            '    "SYNTH_SOUNDFONT_PATH": "/path/to/TimGM6mb.sf2"\n'
            "  Run the health_check tool after restarting to confirm everything is ready."
        )
    elif not os.path.exists(soundfont_path):
        logger.warning(
            "Soundfont not found at %r — synthesis will fail.\n"
            "  Fix: verify the file exists at that path, or update SYNTH_SOUNDFONT_PATH.",
            soundfont_path,
        )
    else:
        logger.info("Soundfont: %s", soundfont_path)

    try:
        import fluidsynth  # noqa: F401
        logger.info("FluidSynth library available")
    except (ImportError, OSError) as e:
        logger.warning("FluidSynth library not available: %s", e)

    logger.info(
        "synth-mcp started — tools: get_parts, synthesize, list_capabilities, health_check"
    )

    async def _run():
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
