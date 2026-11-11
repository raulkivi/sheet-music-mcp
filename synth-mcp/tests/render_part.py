"""Render one part of a MusicXML score to a WAV with synth-mcp's engine.

Test support for the synth -> pitch round trip (S3). pitch-mcp runs this file with synth-mcp's own
interpreter, so the two servers never share a venv::

    synth-mcp/.venv/bin/python -I synth-mcp/tests/render_part.py SCORE OUT.wav --part P1

Reads the soundfont from ``SYNTH_SOUNDFONT_PATH``, like the server. Exit 0 on success; 1 with the
error on stderr when the engine refuses. Runs by path, so it imports nothing from ``tests``.
"""

import argparse
import sys
from pathlib import Path

from synth_mcp.engine import ProcessingError, extract_midi, synthesize_midi


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("score", type=Path, help="MusicXML file")
    parser.add_argument("output", type=Path, help="WAV file to write")
    parser.add_argument("--part", required=True, help="Part ID, name or voice (P1, Soprano, S)")
    parser.add_argument("--timbre", default="score", help="score, piano, choir or organ")
    args = parser.parse_args(argv)

    try:
        midi = extract_midi(
            args.score.read_text(encoding="utf-8"), [args.part], 1.0, timbre=args.timbre
        )
        synthesize_midi(midi, str(args.output))
    except ProcessingError as e:
        print(f"render_part: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
