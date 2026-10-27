"""Measure ranges (docs/conventions.md, Measure Ranges).

``select_measures`` cuts a score down to a range of printed measure numbers before an engine
parses it, keeping the key, time, clef, divisions, transposition and tempo in force at the start.
Parses with ``scores.parse_score`` (defusedxml), never music21, and has no MCP imports: engines
may use it. Errors name measure numbers only, never document text.
"""

from __future__ import annotations

import copy
import re
from types import MappingProxyType
from typing import Sequence
from xml.etree import ElementTree
from xml.etree.ElementTree import Element

from .errors import ProcessingError
from .scores import _local, _metronome_bpm, _number, _tidy, parse_score

__all__ = ["MEASURES_PROPERTY", "MeasureRangeError", "parse_range", "printed_numbers", "select_measures"]

MAX_MEASURE = 99999

MEASURES_PROPERTY = MappingProxyType(
    {
        "measures": {
            "type": "array",
            "items": {"type": "integer", "minimum": 0, "maximum": MAX_MEASURE},
            "minItems": 2,
            "maxItems": 2,
            "description": (
                "Inclusive [start, end] range of printed measure numbers, e.g. [17, 24]. A pickup bar is 0."
            ),
        }
    }
)

_SHAPE_HINT = f"Pass [start, end]: two whole numbers from 0 to {MAX_MEASURE}, start first, e.g. [17, 24]."
_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>\n'
# The leading integer of a measure number ("12a" -> 12), bounded so int() stays cheap.
_LEADING_NUMBER = re.compile(r"\d{1,6}(?!\d)")
# Children of <attributes> in MusicXML schema order; carried elements are inserted to keep it.
_ATTRIBUTE_ORDER = (
    "footnote", "level", "divisions", "key", "time", "staves", "part-symbol", "instruments", "clef",
    "staff-details", "transpose", "for-part", "directive", "measure-style",
)
# Elements that apply to every staff unless they carry a staff ``number``.
_ALL_STAVES = ("key", "time", "transpose")
# Children of a measure that take time: anything before the first of them is at its start.
_TIMED = ("note", "backup", "forward")

# Keep the conventional prefix for xlink attributes (credit images, links) when serializing.
ElementTree.register_namespace("xlink", "http://www.w3.org/1999/xlink")


class MeasureRangeError(ProcessingError):
    """A measure range is malformed or outside the score (INVALID_PARAMETER)."""

    def __init__(self, message: str, *, hint: str):
        super().__init__(message, "INVALID_PARAMETER", hint=hint)


def parse_range(value, *, param: str = "measures") -> tuple[int, int] | None:
    """``[start, end]`` (list or tuple of ints, ``0 <= start <= end <= 99999``) as a tuple.

    None stays None. For values the top-level input schema does not check: direct engine calls
    and ``options`` objects. Raises MeasureRangeError.
    """
    if value is None:
        return None
    start, end = _pair(value, param)
    if start > end:
        raise MeasureRangeError(f"{param} start ({start}) is after its end ({end}).", hint=_SHAPE_HINT)
    return start, end


def printed_numbers(root: Element) -> list[int]:
    """The printed number of each measure of the first part, in written order.

    The leading integer of ``number`` ("12a" -> 12). A first measure marked ``implicit="yes"`` (a
    pickup) is 0. A number without a leading integer ("X1", "") takes the previous measure's
    number, or 0 for the first measure. Timewise scores use the top-level measures.
    """
    numbers: list[int] = []
    for position, measure in enumerate(_first_part_measures(root)):
        if position == 0 and measure.get("implicit") == "yes":
            numbers.append(0)
        elif match := _LEADING_NUMBER.match(measure.get("number", "").strip()):
            numbers.append(int(match.group()))
        else:
            numbers.append(numbers[-1] if numbers else 0)
    return numbers


def select_measures(text: str | bytes, measures: Sequence[int] | None) -> str | bytes:
    """The score cut down to the measures whose printed number is within ``measures``.

    Every part keeps the measures at the positions kept in the first part. The first kept measure
    (of each run of kept measures) gets the divisions, key, time, clefs, staves, transposition
    and tempo in force before it, where it does not set them itself; its ``<print>`` breaks are
    dropped unless it is the score's first measure. Header elements are kept and bars are taken
    as written (repeats are not expanded). Returns MusicXML text with an XML declaration, or
    ``text`` unchanged when ``measures`` is None. Raises MeasureRangeError or ScoreFormatError.
    """
    if measures is None:
        return text
    start, end = _pair(measures, "measures")
    root = parse_score(text)
    keep = _kept_positions(printed_numbers(root), start, end)
    if _local(root.tag) == "score-partwise":
        for part in root.findall("part"):
            part_measures = part.findall("measure")
            _carry_state(part_measures, keep)
            _remove_others(part, part_measures, keep)
    else:
        top_measures = root.findall("measure")
        for containers in _timewise_parts(top_measures).values():
            _carry_state(containers, keep)
        _remove_others(root, top_measures, keep)
    return _DECLARATION + ElementTree.tostring(root, encoding="unicode")


# --- Ranges ----------------------------------------------------------------------------------


def _pair(value, param: str) -> tuple[int, int]:
    """Two non-bool ints from 0 to 99999, in either order."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise MeasureRangeError(f"{param} must be two measure numbers [start, end].", hint=_SHAPE_HINT)
    if not all(isinstance(item, int) and not isinstance(item, bool) for item in value):
        raise MeasureRangeError(f"{param} must hold whole numbers.", hint=_SHAPE_HINT)
    if not all(0 <= item <= MAX_MEASURE for item in value):
        raise MeasureRangeError(f"{param} must be between 0 and {MAX_MEASURE}.", hint=_SHAPE_HINT)
    return value[0], value[1]


def _kept_positions(numbers: list[int], start: int, end: int) -> set[int]:
    if not numbers:
        raise MeasureRangeError(f"Measures {start}–{end} are not in this score.", hint="This score has no measures.")
    hint = f"This score has measures {numbers[0]}–{numbers[-1]}."
    if start > end:
        raise MeasureRangeError(f"measures start ({start}) is after its end ({end}).", hint=hint)
    if start < numbers[0] or end > numbers[-1]:
        raise MeasureRangeError(f"Measures {start}–{end} are outside this score.", hint=hint)
    keep = {position for position, number in enumerate(numbers) if start <= number <= end}
    if not keep:
        raise MeasureRangeError(f"No measure is numbered {start}–{end}.", hint=hint)
    return keep


def _first_part_measures(root: Element) -> list[Element]:
    if _local(root.tag) == "score-partwise":
        part = root.find("part")
        return part.findall("measure") if part is not None else []
    return root.findall("measure")


def _timewise_parts(measures: list[Element]) -> dict[str, list[Element | None]]:
    """Part ID -> its ``<part>`` in each top-level measure (None where a measure lacks it)."""
    parts: dict[str, list[Element | None]] = {}
    for position, measure in enumerate(measures):
        for part in measure.findall("part"):
            parts.setdefault(part.get("id", ""), [None] * len(measures))[position] = part
    return parts


def _remove_others(parent: Element, children: list[Element], keep: set[int]) -> None:
    for position, child in enumerate(children):
        if position not in keep:
            parent.remove(child)


# --- Carrying state --------------------------------------------------------------------------


class _State:
    """The attributes and tempo in force after a sequence of measures."""

    def __init__(self) -> None:
        self.divisions: Element | None = None
        self.staves: Element | None = None
        self.all_staves: dict[str, dict[str | None, Element]] = {tag: {} for tag in _ALL_STAVES}
        self.clefs: dict[str, Element] = {}
        self.tempo: int | float | None = None

    def read(self, measure: Element) -> None:
        for child in measure:
            if child.tag == "attributes":
                self._read_attributes(child)
            elif (bpm := _tempo(child)) is not None:
                self.tempo = bpm

    def _read_attributes(self, attributes: Element) -> None:
        for child in attributes:
            if child.tag == "divisions":
                self.divisions = child
            elif child.tag == "staves":
                self.staves = child
            elif child.tag == "clef":
                self.clefs[child.get("number", "1")] = child
            elif child.tag in _ALL_STAVES:
                by_staff = self.all_staves[child.tag]
                if child.get("number") is None:
                    by_staff.clear()
                by_staff[child.get("number")] = child

    def carried(self, attributes: Element) -> list[Element]:
        """The state elements ``attributes`` does not set itself."""
        own = {child.tag for child in attributes}
        own_clefs = {clef.get("number", "1") for clef in attributes.findall("clef")}
        elements = [element for element in (self.divisions, self.staves) if element is not None]
        for by_staff in self.all_staves.values():
            elements.extend(by_staff.values())
        elements = [element for element in elements if element.tag not in own]
        elements.extend(clef for number, clef in self.clefs.items() if number not in own_clefs)
        return elements


def _carry_state(containers: list[Element | None], keep: set[int]) -> None:
    """Give the first measure of each run of kept measures the state in force before it.

    One pass: a measure is read after the state is applied to it, which leaves the state as the
    measure itself now sets it.
    """
    state = _State()
    for position, container in enumerate(containers):
        if container is None:
            continue
        if position > 0 and position in keep and position - 1 not in keep:
            _apply(container, state)
        state.read(container)


def _apply(measure: Element, state: _State) -> None:
    for found in measure.findall("print"):
        measure.remove(found)
    attributes = _leading_attributes(measure)
    for element in state.carried(attributes):
        _insert_in_order(attributes, copy.deepcopy(element))
    if len(attributes):
        after_attributes = list(measure).index(attributes) + 1
    else:
        measure.remove(attributes)
        after_attributes = 0
    if state.tempo is not None and not _starts_with_tempo(measure):
        measure.insert(after_attributes, Element("sound", {"tempo": str(state.tempo)}))


def _leading_attributes(measure: Element) -> Element:
    """The ``<attributes>`` before the measure's first note, created as its first child if absent."""
    for child in measure:
        if child.tag in _TIMED:
            break
        if child.tag == "attributes":
            return child
    attributes = Element("attributes")
    measure.insert(0, attributes)
    return attributes


def _insert_in_order(attributes: Element, element: Element) -> None:
    rank = _rank(element.tag)
    position = next((index for index, child in enumerate(attributes) if _rank(child.tag) > rank), len(attributes))
    attributes.insert(position, element)


def _rank(tag: str) -> int:
    return _ATTRIBUTE_ORDER.index(tag) if tag in _ATTRIBUTE_ORDER else len(_ATTRIBUTE_ORDER)


def _starts_with_tempo(measure: Element) -> bool:
    for child in measure:
        if child.tag in _TIMED:
            return False
        if _tempo(child) is not None:
            return True
    return False


def _tempo(element: Element) -> int | float | None:
    """Quarter notes per minute set by a ``<direction>`` or measure-level ``<sound>``, if any."""
    if element.tag == "sound":
        sounds, metronomes = [element], []
    elif element.tag == "direction":
        sounds, metronomes = element.findall("sound"), element.findall("direction-type/metronome")
    else:
        return None
    for sound in sounds:
        if (bpm := _number(sound.get("tempo"))) is not None and bpm > 0:
            return _tidy(bpm)
    for metronome in metronomes:
        if (bpm := _metronome_bpm(metronome)) is not None:
            return bpm
    return None
