"""Replace some bars of one part with ABC, keeping the rest of the score (C16, ``apply_abc_edit``).

The score is edited as text: only the ``<measure>`` elements of the target part inside the range
are swapped for new ones, so every other byte (other parts, the header, DOCTYPE, comments and
formatting) is kept as it was. A replaced bar keeps its own shell from the original (measure
attributes, ``<print>`` layout, leading ``<attributes>``, barlines, tempo and rehearsal marks);
its notes and any ABC decorations come from the ABC, and what it loses is reported as warnings.
ABC bars are cut at their bar lines (``abc_bars``) and converted one at a time.

No MCP imports: unit-testable without the MCP stack.
"""

from __future__ import annotations

import copy
import logging
import math
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Sequence
from xml.etree import ElementTree
from xml.etree.ElementTree import Element
from xml.parsers import expat

from sheet_music_mcp_core.errors import ProcessingError
from sheet_music_mcp_core.measures import printed_numbers, select_measures
from sheet_music_mcp_core.parts import PartInfo, resolve_part
from sheet_music_mcp_core.scores import parse_score

from .abc_bars import split_bars
from .engine import abc_to_musicxml

__all__ = ["MAX_ABC_CHARS", "MAX_EDIT_BARS", "apply_abc_edit"]

logger = logging.getLogger(__name__)

# 64 KiB of ABC is about 20x a long hymn (a few KB) yet bounds memory and the line scanner.
MAX_ABC_CHARS = 65536
# Each bar costs one music21 parse (tens of ms); 64 bars is a full page of a choral part
# and bounds one call to a few seconds. Longer passages are edited in several calls.
MAX_EDIT_BARS = 64
_SPLIT_HINT = "Split the edit into smaller calls: pass fewer bars and the matching shorter measures range."

_TIMED = ("note", "backup", "forward")
# Content of an ABC bar that the original score decides instead: key, time, clef and divisions
# (attributes), layout (print) and bar lines.
_SHELL_TAGS = ("attributes", "print", "barline")
# Directions that belong to the whole score, not to the edited part's music.
_SCORE_DIRECTIONS = ("rehearsal", "segno", "coda", "metronome")
# Children of <attributes> that may precede <divisions>, in schema order.
_BEFORE_DIVISIONS = ("footnote", "level")
_DECLARED_ENCODING = re.compile(r"""^(\s*<\?xml\b[^>]*?\bencoding\s*=\s*)(["'])([^"']*)\2""")
_INTEGER = re.compile(r"[+-]?\d{1,9}")
_ABC_HINT = "Check the ABC with validate_abc, then pass one tune (X:, M:, L:, K: headers) for one part."


def apply_abc_edit(musicxml_str: str, part: str, measures: Sequence[int], abc: str) -> dict:
    """Replace ``measures`` (inclusive printed bar numbers) of ``part`` with the bars of ``abc``.

    Returns ``{"part", "measures", "measures_replaced", "warnings", "musicxml"}``. ``part`` is the
    resolved MusicXML part ID; ``warnings`` follows docs/conventions.md (Warnings). Raises
    ProcessingError: INVALID_PARAMETER for a bad range or part, INVALID_INPUT for a score or ABC
    that cannot be used. Nothing is returned on error, so no partial score is ever written.
    """
    if measures is None:
        raise ProcessingError("measures is required.", "INVALID_PARAMETER", hint="Pass [start, end], e.g. [12, 14].")
    if len(abc or "") > MAX_ABC_CHARS:
        raise ProcessingError(
            f"The ABC is longer than {MAX_ABC_CHARS} characters.", "INVALID_PARAMETER", hint=_SPLIT_HINT
        )
    # Checks the score and the range with the same errors and hints as every other measures tool.
    select_measures(musicxml_str, measures)
    start, end = measures
    root = parse_score(musicxml_str)
    if root.tag != "score-partwise":
        raise ProcessingError(
            "apply_abc_edit needs a partwise score.",
            "INVALID_INPUT",
            hint="Export the score as partwise MusicXML (MuseScore, Audiveris and music21 do).",
        )

    numbers = printed_numbers(root)
    positions = [position for position, number in enumerate(numbers) if start <= number <= end]
    part_id = resolve_part(part, _part_infos(root))
    originals = _part_measures(root, part_id)
    if positions[-1] >= len(originals):
        raise ProcessingError(f"Part {part_id} has fewer measures than the first part.", "INVALID_INPUT")

    tunes = split_bars(abc)
    if len(tunes) > MAX_EDIT_BARS:
        raise ProcessingError(
            f"The ABC has {len(tunes)} bars; one edit takes at most {MAX_EDIT_BARS}.",
            "INVALID_PARAMETER",
            hint=_SPLIT_HINT,
        )
    if len(tunes) != len(positions):
        raise ProcessingError(
            f"The ABC has {len(tunes)} bars but measures {start}–{end} are {len(positions)} bars.",
            "INVALID_INPUT",
            hint=f"Give exactly {len(positions)} bars separated by '|'; the ABC has {len(tunes)}.",
        )

    bars = [_abc_bar(tune, index) for index, tune in enumerate(tunes, 1)]
    _join_ties(bars)
    edits = dict(zip(positions, bars))
    warnings = [
        warning
        for position, bar in edits.items()
        for warning in _warnings(originals[position], bar.measure, numbers[position], part_id)
    ]
    divisions = _divisions(originals)
    _check_lengths(originals, edits, divisions, numbers, part_id, warnings)
    replacements = _replacements(originals, edits, divisions)
    text = _splice(musicxml_str, part_id, replacements)
    return {
        "part": part_id,
        "measures": [start, end],
        "measures_replaced": len(positions),
        "warnings": warnings,
        "musicxml": text,
    }


# --- Reading the score and the ABC -------------------------------------------------------------


def _part_infos(root: Element) -> list[PartInfo]:
    """Parts by MusicXML score-part ID, as describe_score and the part resolver see them."""
    infos = [
        PartInfo(
            score_part.get("id", ""),
            (score_part.findtext("part-name") or "").strip(),
            (score_part.findtext("part-abbreviation") or "").strip(),
        )
        for score_part in root.findall("part-list/score-part")
    ]
    listed = {info.id for info in infos}
    infos.extend(PartInfo(p.get("id", ""), "") for p in root.findall("part") if p.get("id", "") not in listed)
    return infos


def _part_measures(root: Element, part_id: str) -> list[Element]:
    for found in root.findall("part"):
        if found.get("id") == part_id:
            return found.findall("measure")
    raise ProcessingError(f"Part {part_id} is listed but has no music.", "INVALID_INPUT")


@dataclass(frozen=True)
class _Bar:
    """One ABC bar as MusicXML: a ``<measure>`` holding its content, in its own divisions."""

    measure: Element
    divisions: int


def _abc_bar(tune: str, index: int) -> _Bar:
    """Convert one bar tune (from ``split_bars``) with music21."""
    try:
        converted = abc_to_musicxml(tune)["musicxml"]
    except ProcessingError as error:
        # music21's text can echo input or internals: log it, show a fixed message.
        logger.warning("apply_abc_edit: bar %d failed to parse: %s", index, error)
        raise ProcessingError(
            f"Bar {index} of the ABC could not be parsed; check the bar syntax.", "INVALID_INPUT", hint=_ABC_HINT
        ) from None
    parts = parse_score(converted).findall("part")
    divisions = next((_int(found.text) for part in parts for found in part.iter("divisions")), None)
    if len(parts) != 1 or not divisions:
        raise ProcessingError(f"Bar {index} of the ABC holds no notes or rests.", "INVALID_INPUT", hint=_ABC_HINT)
    # music21 may still give one bar several measures; their content runs on in one voice.
    measure = Element("measure")
    measure.extend(child for found in parts[0].findall("measure") for child in found)
    return _Bar(measure, divisions)


def _join_ties(bars: list[_Bar]) -> None:
    """Each bar was converted alone, so a tie across a bar line lost its stop: add it to the
    matching note at the start of the next bar."""
    for bar, following in zip(bars, bars[1:]):
        opening = _group(bar.measure, last=True)
        closing = {_pitch(note): note for note in _group(following.measure, last=False)}
        for note in opening:
            target = closing.get(_pitch(note))
            started = any(tie.get("type") == "start" for tie in note.findall("tie"))
            if started and target is not None and target.find("tie[@type='stop']") is None:
                _add_tie_stop(target)


def _group(measure: Element, *, last: bool) -> list[Element]:
    """The notes sounding together at the measure's first (or last) note: one note or a chord."""
    notes = [child for child in measure if child.tag == "note"]
    if not notes:
        return []
    if last:
        end = len(notes) - 1
        begin = end
        while begin > 0 and notes[begin].find("chord") is not None:
            begin -= 1
        return notes[begin : end + 1]
    end = 1
    while end < len(notes) and notes[end].find("chord") is not None:
        end += 1
    return notes[:end]


def _pitch(note: Element) -> tuple:
    step, alter, octave = (note.findtext(f"pitch/{name}", "").strip() for name in ("step", "alter", "octave"))
    return step, alter or "0", octave


def _add_tie_stop(note: Element) -> None:
    children = list(note)
    after = max(i for i, child in enumerate(children) if child.tag in ("duration", "tie", "chord", "pitch")) + 1
    note.insert(after, Element("tie", {"type": "stop"}))
    notations = note.find("notations")
    if notations is None:
        notations = Element("notations")
        index = next((i for i, child in enumerate(note) if child.tag in ("lyric", "play", "listen")), len(note))
        note.insert(index, notations)
    notations.append(Element("tied", {"type": "stop"}))


# --- Warnings ----------------------------------------------------------------------------------


_DROPPED = (
    (".//dynamics", "DYNAMICS_DROPPED", "dynamics"),
    (".//lyric", "LYRICS_DROPPED", "lyrics"),
    (".//articulations", "ARTICULATION_DROPPED", "articulations"),
)


def _warnings(original: Element, bar: Element, number: int, part_id: str) -> list[dict]:
    """What the score had in this bar that the edit no longer has."""
    return [
        _warning(code, f"Measure {number} had {what} in the score; the edit has none, so they were removed.", number, part_id)
        for path, code, what in _DROPPED
        if original.find(path) is not None and bar.find(path) is None
    ]


def _check_lengths(originals, edits, divisions, numbers, part_id, warnings) -> None:
    for position, bar in edits.items():
        before = Fraction(_length(originals[position]), divisions[position][0])
        after = Fraction(_length(bar.measure), bar.divisions)
        if before != after:
            number = numbers[position]
            message = (
                f"Measure {number} lasts {_quarters(after)} quarter notes in the edit "
                f"but {_quarters(before)} in the score."
            )
            warnings.append(_warning("MEASURE_DURATION_MISMATCH", message, number, part_id))


def _warning(code: str, message: str, number: int, part_id: str) -> dict:
    return {"code": code, "severity": "warning", "message": message, "measure": number, "part": part_id}


def _length(measure: Element) -> int:
    """The measure's length in its divisions: the furthest point its notes reach."""
    position = longest = 0
    for child in measure:
        duration = _int(child.findtext("duration")) or 0
        if child.tag == "note" and child.find("chord") is None and child.find("grace") is None:
            position += duration
        elif child.tag == "forward":
            position += duration
        elif child.tag == "backup":
            position -= duration
        longest = max(longest, position)
    return longest


def _quarters(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{float(value):g}"


# --- Building the new bars ---------------------------------------------------------------------


def _divisions(measures: list[Element]) -> list[tuple[int, int]]:
    """(divisions at the measure's first note, divisions after the measure) for each measure."""
    current = 1  # MusicXML requires divisions before the first note; 1 if a score omits them
    found = []
    for measure in measures:
        leading = _leading(measure, "attributes")
        if leading is not None and (value := _int(leading.findtext("divisions"))):
            current = value
        at_start = current
        for attributes in measure.findall("attributes"):
            if value := _int(attributes.findtext("divisions")):
                current = value
        found.append((at_start, current))
    return found


def _replacements(originals, edits, divisions) -> dict[int, Element]:
    """Position -> new measure: the edited bars, plus any bar after them that must restore the
    part's divisions."""
    replacements: dict[int, Element] = {}
    in_force: int | None = None  # divisions in force in the new score before this measure
    for position, original in enumerate(originals):
        if position in edits:
            own = divisions[position][0]
            bar = edits[position]
            content = [child for child in bar.measure if not _from_original(child)]
            scale = _finer(content, own, bar.divisions)
            _rescale(content, Fraction(own * scale, bar.divisions))
            replacements[position] = _edited_measure(original, content, own * scale, in_force)
            in_force = own * scale
            continue
        expected = divisions[position - 1][1] if position else None
        if in_force is not None and in_force != expected and _leading_divisions(original) is None:
            replacements[position] = _with_divisions(original, expected)
        in_force = divisions[position][1]
    return replacements


def _from_original(child: Element) -> bool:
    """ABC content the original score decides: shell elements and the header's tempo."""
    if child.tag in _SHELL_TAGS:
        return True
    if child.tag == "sound":
        return child.get("tempo") is not None
    return child.tag == "direction" and (
        child.find("direction-type/metronome") is not None or child.find("sound[@tempo]") is not None
    )


def _finer(content: list[Element], divisions: int, abc_divisions: int) -> int:
    """The smallest factor that makes every ABC duration a whole number of the part's divisions."""
    factor = 1
    for value in _timings(content):
        denominator = Fraction(_int(value.text) * divisions, abc_divisions).denominator
        factor = factor * denominator // math.gcd(factor, denominator)
    return factor


def _rescale(content: list[Element], ratio: Fraction) -> None:
    for value in _timings(content):
        value.text = str(int(_int(value.text) * ratio))


def _timings(content: list[Element]):
    for child in content:
        for found in child.iter():
            if found.tag in ("duration", "offset") and _int(found.text) is not None:
                yield found


def _edited_measure(original: Element, content: list[Element], divisions: int, in_force: int | None) -> Element:
    """The original bar's shell around the ABC bar's content."""
    measure = Element("measure", dict(original.attrib))
    leading = _kept_leading(original)
    trailing = [child for child in original.findall("barline") if child.get("location") != "left"]
    measure.extend(_copy(leading) + content + _copy(trailing))
    attributes = _leading(measure, "attributes")
    if attributes is not None and attributes.find("divisions") is not None:
        attributes.find("divisions").text = str(divisions)
    elif in_force != divisions:
        _set_divisions(measure, divisions)
    return measure


def _kept_leading(original: Element) -> list[Element]:
    """Children before the first note that the edit keeps: layout, attributes, left bar lines,
    tempo, rehearsal marks."""
    kept = []
    for child in original:
        if child.tag in _TIMED:
            break
        if child.tag in ("print", "attributes", "sound") or _is_score_direction(child):
            kept.append(child)
        elif child.tag == "barline" and child.get("location") == "left":
            kept.append(child)
    return kept


def _is_score_direction(child: Element) -> bool:
    if child.tag != "direction":
        return False
    kinds = {found.tag for found in child.findall("direction-type/*")}
    return bool(kinds & set(_SCORE_DIRECTIONS)) or child.find("sound[@tempo]") is not None


def _with_divisions(original: Element, divisions: int) -> Element:
    measure = _copy([original])[0]
    _set_divisions(measure, divisions)
    return measure


def _set_divisions(measure: Element, divisions: int) -> None:
    """Give the measure's leading ``<attributes>`` (created if absent) these divisions."""
    attributes = _leading(measure, "attributes")
    if attributes is None:
        attributes = Element("attributes")
        index = next(
            (i for i, child in enumerate(measure) if child.tag not in ("print", "barline")), len(measure)
        )
        measure.insert(index, attributes)
    element = attributes.find("divisions")
    if element is None:
        element = Element("divisions")
        index = sum(1 for child in attributes if child.tag in _BEFORE_DIVISIONS)
        attributes.insert(index, element)
    element.text = str(divisions)


def _leading(measure: Element, tag: str) -> Element | None:
    """The first ``tag`` child before the measure's first note, if any."""
    for child in measure:
        if child.tag in _TIMED:
            return None
        if child.tag == tag:
            return child
    return None


def _leading_divisions(measure: Element) -> Element | None:
    attributes = _leading(measure, "attributes")
    return attributes.find("divisions") if attributes is not None else None


def _copy(elements: list[Element]) -> list[Element]:
    return [copy.deepcopy(element) for element in elements]


# --- Writing -----------------------------------------------------------------------------------


def _splice(text: str, part_id: str, replacements: dict[int, Element]) -> str:
    """``text`` with the part's measures at the given positions replaced; every other byte kept."""
    data = text.removeprefix("\ufeff").encode("utf-8")
    spans = _measure_spans(data, part_id)
    for position in sorted(replacements, reverse=True):
        begin, finish = spans[position]
        new = _serialize(replacements[position], _indent_of(data, begin)).encode("utf-8")
        data = data[:begin] + new + data[finish:]
    return _utf8_declaration(data.decode("utf-8"))


def _measure_spans(data: bytes, part_id: str) -> list[tuple[int, int]]:
    """Byte span of each ``<measure>`` of the first ``<part id=part_id>``, end tag included.

    The score was already parsed with defusedxml, so it declares no entities. A measure ends
    where the next parser event starts.
    """
    parser = expat.ParserCreate(encoding="utf-8")  # overrides the declared encoding: data is UTF-8
    spans: list[list[int]] = []
    state = {"depth": 0, "inside": False, "done": False, "open": None}

    def close(*_):
        if state["open"] is not None:
            spans[state["open"]][1] = parser.CurrentByteIndex
            state["open"] = None

    def on_start(name, attributes):
        close()
        state["depth"] += 1
        if state["depth"] == 2 and name == "part" and not state["done"]:
            state["inside"] = attributes.get("id") == part_id
        elif state["depth"] == 3 and state["inside"] and name == "measure":
            spans.append([parser.CurrentByteIndex, -1])

    def on_end(name):
        close()
        if state["depth"] == 3 and state["inside"] and name == "measure":
            state["open"] = len(spans) - 1
        elif state["depth"] == 2 and state["inside"]:
            state["inside"], state["done"] = False, True
        state["depth"] -= 1

    parser.StartElementHandler = on_start
    parser.EndElementHandler = on_end
    parser.CharacterDataHandler = close
    parser.CommentHandler = close
    parser.ProcessingInstructionHandler = close
    parser.StartCdataSectionHandler = close
    parser.Parse(data, True)
    return [(begin, end) for begin, end in spans]


def _indent_of(data: bytes, begin: int) -> str | None:
    """The indentation unit of the line a measure starts on (measures sit at depth 2), or None
    for a score written without line breaks."""
    newline = data.rfind(b"\n", 0, begin)
    prefix = data[newline + 1 : begin]
    if newline < 0 or prefix.strip() or not prefix:
        return None
    text = prefix.decode("utf-8")
    return text[: max(len(text) // 2, 1)]


def _serialize(measure: Element, unit: str | None) -> str:
    for element in measure.iter():
        if len(element) and (element.text is None or not element.text.strip()):
            element.text = None
        if element.tail is not None and not element.tail.strip():
            element.tail = None
    if unit is not None:
        ElementTree.indent(measure, space=unit, level=2)
    measure.tail = None
    return ElementTree.tostring(measure, encoding="unicode")


def _utf8_declaration(text: str) -> str:
    """The text is returned as UTF-8, so an XML declaration naming another encoding is updated."""
    match = _DECLARED_ENCODING.match(text)
    if match is None or match.group(3).lower().replace("-", "") == "utf8":
        return text
    return text[: match.start(3)] + "UTF-8" + text[match.end(3) :]


def _int(text: str | None) -> int | None:
    # Score text is untrusted: accept short integers only, so int() stays cheap.
    if text is None or not (match := _INTEGER.fullmatch(text.strip())):
        return None
    return int(match.group())
