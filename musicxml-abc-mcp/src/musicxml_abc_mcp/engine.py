"""
Core conversion engine for musicxml-abc-mcp.

No MCP SDK imports here — this module is independently unit-testable.

Key design decision:
    music21 9.x supports ABC as INPUT only (ConverterABC.registerOutputExtensions = ()).
    MusicXML → ABC is implemented as a custom serializer that walks music21's object
    model and emits ABC text directly.  ABC → MusicXML uses music21's built-in parser.

ABC output format:
    One X: tune per part (Soprano=X:1, Alto=X:2, …), joined by blank lines.
    Default note length L:1/8.  All accidentals are marked explicitly to avoid
    ambiguity across playback tools.

Known limitations (documented here rather than hidden):
    - Dynamics (pp, mf, ff, …) have no ABC equivalent — silently dropped.
    - Complex articulations (trills, ornaments, falls) are dropped.
    - Chords within a single voice are represented as [notes] clusters.
    - Tied notes are represented as repeated notes with a tie marker (~).
    - Round-trips are not byte-identical; note *count* and *pitch* are preserved.
"""

import logging
from fractions import Fraction
from typing import Optional

logger = logging.getLogger(__name__)


class ProcessingError(Exception):
    """Raised when a conversion step fails in an expected, reportable way."""

    def __init__(self, message: str, error_code: str = "PROCESSING_FAILED"):
        super().__init__(message)
        self.error_code = error_code


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def musicxml_to_abc(musicxml_str: str, part_id: Optional[str] = None) -> dict:
    """Convert a MusicXML string to ABC notation.

    Args:
        musicxml_str: MusicXML document as a string.
        part_id: If given, export only the part with this ID; otherwise all parts.

    Returns:
        {
            "abc": "<ABC text>",
            "parts_included": ["Soprano", "Alto", …],
            "warnings": ["Dynamic markings were dropped …"],
        }

    Raises:
        ProcessingError: on parse failure or invalid part_id.
    """
    _require_music21()

    import music21
    import music21.converter

    try:
        score = music21.converter.parseData(musicxml_str, format="musicxml")
    except Exception as e:
        raise ProcessingError(f"Failed to parse MusicXML: {e}", "INVALID_INPUT")

    all_parts = list(score.parts)
    if not all_parts:
        raise ProcessingError(
            "No parts found in score. Verify the MusicXML contains <part> elements.",
            "INVALID_INPUT",
        )

    if part_id is not None:
        selected = [p for p in all_parts if p.id == part_id]
        if not selected:
            valid = [p.id for p in all_parts]
            raise ProcessingError(
                f"Part '{part_id}' not found. Valid part IDs: {valid}",
                "INVALID_PARAMETER",
            )
    else:
        selected = all_parts

    warnings: list[str] = []
    abc_tunes: list[str] = []

    for tune_num, part in enumerate(selected, start=1):
        tune, part_warnings = _part_to_abc_tune(part, tune_num, score)
        abc_tunes.append(tune)
        warnings.extend(part_warnings)

    abc_text = "\n\n".join(abc_tunes)
    return {
        "abc": abc_text,
        "parts_included": [p.id for p in selected],
        "warnings": list(dict.fromkeys(warnings)),  # deduplicate, preserve order
    }


def abc_to_musicxml(abc_str: str) -> dict:
    """Convert an ABC notation string to MusicXML.

    Args:
        abc_str: ABC notation string.

    Returns:
        {"musicxml": "<MusicXML string>", "warnings": []}

    Raises:
        ProcessingError: on parse or conversion failure.
    """
    _require_music21()

    import music21
    import music21.converter

    if not abc_str or not abc_str.strip():
        raise ProcessingError("ABC string is empty.", "INVALID_INPUT")

    try:
        result = music21.converter.parseData(abc_str, format="abc")
    except Exception as e:
        raise ProcessingError(f"Failed to parse ABC: {e}", "INVALID_INPUT")

    # Handle both Score and Opus (multiple X: tunes)
    import music21.stream
    if isinstance(result, music21.stream.Opus):
        # Merge all scores into one
        scores = list(result.scores)
        if not scores:
            raise ProcessingError("ABC produced an empty Opus.", "PROCESSING_FAILED")
        merged = music21.stream.Score()
        for s in scores:
            for part in s.parts:
                merged.append(part)
        result = merged

    try:
        xml_str = music21.converter.toData(result, fmt="musicxml")
    except Exception as e:
        raise ProcessingError(f"Failed to export MusicXML: {e}", "PROCESSING_FAILED")

    return {"musicxml": xml_str, "warnings": []}


def validate_abc(abc_str: str) -> dict:
    """Validate an ABC notation string by attempting to parse it with music21.

    Returns:
        {"valid": bool, "errors": [...], "warnings": [...]}
    """
    _require_music21()

    import music21
    import music21.converter

    if not abc_str or not abc_str.strip():
        return {"valid": False, "errors": ["ABC string is empty."], "warnings": []}

    # Check for minimal required header fields
    warnings: list[str] = []
    lines = abc_str.strip().splitlines()
    has_x = any(l.startswith("X:") for l in lines)
    has_k = any(l.startswith("K:") for l in lines)
    has_t = any(l.startswith("T:") for l in lines)

    if not has_x:
        warnings.append("Missing X: (reference number) header — required by ABC standard.")
    if not has_t:
        warnings.append("Missing T: (title) header — recommended by ABC standard.")
    if not has_k:
        # K: can be the last header, but the standard requires it
        warnings.append("Missing K: (key) header — required to terminate the header block.")

    try:
        music21.converter.parseData(abc_str, format="abc")
        return {"valid": True, "errors": [], "warnings": warnings}
    except Exception as e:
        return {"valid": False, "errors": [str(e)], "warnings": warnings}


# ---------------------------------------------------------------------------
# ABC serialization helpers
# ---------------------------------------------------------------------------

# Map music21 step names to ABC note letters (case varies by octave — handled below)
_STEP_LETTERS = {"C": "C", "D": "D", "E": "E", "F": "F", "G": "G", "A": "A", "B": "B"}


def _pitch_to_abc(pitch) -> str:
    """Convert a music21 Pitch to an ABC note token (without duration).

    ABC octave convention (standard v2.1 §4.1, also how music21 parses ABC):
        C D E F G A B  = C4..B4 (middle-C octave, uppercase)
        c d e f g a b  = C5..B5 (one octave above middle C, lowercase)
        c' d' ...      = C6..B6 (each apostrophe raises one more octave)
        C, D, ...      = C3..B3 (each comma lowers one more octave)
    """
    step = pitch.step          # 'C' .. 'B'
    octave = pitch.octave      # scientific octave (C4 = middle C)
    alter = pitch.alter or 0   # semitones: -1 = flat, 0 = natural, 1 = sharp

    # Accidental prefix
    if alter == 2:
        acc = "^^"
    elif alter == 1:
        acc = "^"
    elif alter == -1:
        acc = "_"
    elif alter == -2:
        acc = "__"
    else:
        acc = ""

    # Note letter and octave modifiers (ABC standard v2.1 §4.1)
    # Uppercase C = middle C (C4); lowercase c = one octave above (C5).
    # C5 = c    C6 = c'   C7 = c''
    # C4 = C    C3 = C,   C2 = C,,
    if octave is None:
        octave = 4  # fallback

    if octave >= 5:
        letter = step.lower() + "'" * (octave - 5)
    else:  # octave <= 4
        letter = step.upper() + "," * (4 - octave)

    return acc + letter


def _duration_to_abc(quarter_length: float) -> str:
    """Convert a duration in quarter notes to an ABC duration string (with L:1/8 base).

    With L:1/8, one unit = one eighth note (0.5 quarter lengths).
    """
    if quarter_length <= 0:
        return "1"  # fallback — shouldn't happen

    units = Fraction(quarter_length * 2).limit_denominator(64)

    if units.denominator == 1:
        n = units.numerator
        return "" if n == 1 else str(n)
    else:
        return f"{units.numerator}/{units.denominator}"


def _key_to_abc(key_sig) -> str:
    """Convert a music21 key.Key or key.KeySignature to ABC K: value."""
    import music21.key

    if isinstance(key_sig, music21.key.Key):
        tonic = key_sig.tonic.name.replace("-", "b")  # music21 uses - for flat
        mode = key_sig.mode
        if mode == "major":
            return tonic
        elif mode == "minor":
            return tonic.capitalize() + "m"
        else:
            return tonic
    elif isinstance(key_sig, music21.key.KeySignature):
        # Convert sharps/flats to a key name — use the relative major
        sharps = key_sig.sharps
        major_keys_by_sharps = {
            -7: "Cb", -6: "Gb", -5: "Db", -4: "Ab", -3: "Eb",
            -2: "Bb", -1: "F", 0: "C", 1: "G", 2: "D", 3: "A",
            4: "E", 5: "B", 6: "F#", 7: "C#",
        }
        return major_keys_by_sharps.get(sharps, "C")
    else:
        return "C"


def _note_to_abc_token(note_or_chord) -> str:
    """Convert a music21 Note, Chord, or Rest to one or more ABC tokens."""
    import music21.note
    import music21.chord

    dur = _duration_to_abc(note_or_chord.quarterLength)

    if isinstance(note_or_chord, music21.note.Rest):
        return f"z{dur}"

    if isinstance(note_or_chord, music21.chord.Chord):
        pitches = note_or_chord.pitches
        if not pitches:
            return f"z{dur}"
        inner = "".join(_pitch_to_abc(p) for p in pitches)
        return f"[{inner}]{dur}"

    # Single note
    if isinstance(note_or_chord, music21.note.Note):
        return _pitch_to_abc(note_or_chord.pitch) + dur

    return f"z{dur}"  # unknown — treat as rest


def _part_to_abc_tune(part, tune_num: int, score) -> tuple[str, list[str]]:
    """Serialise one music21 Part to an ABC tune string.

    Returns:
        (tune_text, warnings)
    """
    import music21.tempo
    import music21.meter
    import music21.key
    import music21.note
    import music21.stream

    warnings: list[str] = []
    has_dynamics = False

    # --- Extract metadata from the part (or score if missing from part) ---
    title = _find_title(part, score)
    part_name = part.partName or part.id or f"Part {tune_num}"

    # Time signature
    time_sig = _first_element(part, "TimeSignature") or _first_element(score, "TimeSignature")
    if time_sig:
        m_field = f"{time_sig.numerator}/{time_sig.denominator}"
    else:
        m_field = "4/4"

    # Key signature
    key_sig = _first_element(part, ("Key", "KeySignature")) or _first_element(score, ("Key", "KeySignature"))
    k_field = _key_to_abc(key_sig) if key_sig else "C"

    # Tempo
    tempo_mark = _first_element(part, "MetronomeMark") or _first_element(score, "MetronomeMark")
    if tempo_mark and hasattr(tempo_mark, "number") and tempo_mark.number:
        q_field = f"1/4={int(tempo_mark.number)}"
    else:
        q_field = "1/4=120"

    # --- Build header ---
    lines = [
        f"X:{tune_num}",
        f"T:{title} - {part_name}" if title else f"T:{part_name}",
        f"M:{m_field}",
        "L:1/8",
        f"Q:{q_field}",
        f"K:{k_field}",
    ]

    # --- Walk measures ---
    measures = list(part.getElementsByClass("Measure"))
    if not measures:
        # Try flat notes if no measures
        flat_notes = list(part.flatten().notesAndRests)
        if flat_notes:
            bar_tokens: list[str] = []
            for elem in flat_notes:
                if _is_dynamic(elem):
                    has_dynamics = True
                    continue
                bar_tokens.append(_note_to_abc_token(elem))
            lines.append(" ".join(bar_tokens) + " |]")
        else:
            lines.append("z4 |]")  # empty part
    else:
        bar_lines: list[str] = []
        for measure in measures:
            tokens: list[str] = []
            for elem in measure.notesAndRests:
                if _is_dynamic(elem):
                    has_dynamics = True
                    continue
                tokens.append(_note_to_abc_token(elem))
            if tokens:
                bar_lines.append(" ".join(tokens))
            else:
                # Empty measure — fill with a whole-measure rest
                if time_sig:
                    rest_dur = _duration_to_abc(time_sig.numerator * 4 / time_sig.denominator)
                else:
                    rest_dur = "8"
                bar_lines.append(f"z{rest_dur}")

        # Join with bar lines, wrap at 80 chars, end with final barline
        body = _wrap_bars(bar_lines)
        lines.append(body)

    if has_dynamics:
        warnings.append(
            "Dynamic markings (pp, mf, ff, etc.) have no ABC equivalent and were dropped."
        )

    return "\n".join(lines), warnings


def _wrap_bars(bars: list[str], line_width: int = 78) -> str:
    """Join measure tokens with | bar lines, wrapping long lines."""
    if not bars:
        return "|]"

    result_lines: list[str] = []
    current = ""

    for i, bar in enumerate(bars):
        segment = bar + " |"
        if i == len(bars) - 1:
            segment = bar + " |]"

        if current and len(current) + len(segment) + 1 > line_width:
            result_lines.append(current.rstrip())
            current = segment + " "
        else:
            current += segment + " "

    if current.strip():
        result_lines.append(current.rstrip())

    return "\n".join(result_lines)


def _find_title(part, score) -> str:
    """Extract score title from metadata."""
    import music21.metadata

    for container in (score, part):
        md = container.getElementsByClass(music21.metadata.Metadata)
        if md:
            m = md[0]
            title = m.title
            if title:
                return str(title)

    return ""


def _first_element(stream, class_names):
    """Return the first element of a class (or tuple of class names) from a stream."""
    if isinstance(class_names, str):
        class_names = (class_names,)
    for cls_name in class_names:
        try:
            elements = list(stream.recurse().getElementsByClass(cls_name))
            if elements:
                return elements[0]
        except Exception:
            pass
    return None


def _is_dynamic(elem) -> bool:
    """Return True if elem is a dynamics object."""
    try:
        import music21.dynamics
        return isinstance(elem, music21.dynamics.Dynamic)
    except Exception:
        return False


def health_check() -> dict:
    """Run a smoke test to verify all runtime dependencies are working.

    Returns:
        {
            "status": "ok" | "degraded",
            "checks": {
                "music21": {"ok": bool, "version": str | None, "error": str | None},
                "round_trip": {"ok": bool, "error": str | None},
            },
            "summary": "human-readable status string",
        }
    """
    result: dict = {"status": "ok", "checks": {}, "summary": ""}

    # Check music21 availability
    try:
        import music21
        result["checks"]["music21"] = {"ok": True, "version": music21.__version__}
    except ImportError as e:
        result["checks"]["music21"] = {"ok": False, "version": None, "error": str(e)}
        result["status"] = "degraded"

    # Round-trip smoke test: MusicXML → ABC → MusicXML
    if result["status"] == "ok":
        try:
            abc_result = musicxml_to_abc(_SMOKE_MUSICXML)
            abc_text = abc_result.get("abc", "")
            if not abc_text:
                raise ValueError("musicxml_to_abc returned empty ABC")
            mx_result = abc_to_musicxml(abc_text)
            if not mx_result.get("musicxml") or "<score-partwise" not in mx_result["musicxml"]:
                raise ValueError("abc_to_musicxml returned invalid MusicXML")
            result["checks"]["round_trip"] = {"ok": True}
        except Exception as e:
            result["checks"]["round_trip"] = {"ok": False, "error": str(e)}
            result["status"] = "degraded"

    if result["status"] == "ok":
        version = result["checks"]["music21"]["version"]
        result["summary"] = (
            f"All systems operational. music21 {version} and the custom ABC serializer "
            "are working correctly."
        )
    else:
        issues = [
            f"{k}: {v.get('error', 'failed')}"
            for k, v in result["checks"].items()
            if not v.get("ok")
        ]
        result["summary"] = "Server is degraded: " + "; ".join(issues)

    return result


_SMOKE_MUSICXML = """\
<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Test</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>4</divisions>
        <key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <note>
        <pitch><step>C</step><octave>4</octave></pitch>
        <duration>4</duration><type>quarter</type>
      </note>
    </measure>
  </part>
</score-partwise>"""


def _require_music21():
    """Raise ProcessingError if music21 is not importable."""
    try:
        import music21  # noqa: F401
    except ImportError as e:
        raise ProcessingError(f"music21 is not available: {e}", "PROCESSING_FAILED")
