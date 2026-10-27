"""MusicXML files and score descriptions (docs/conventions.md, Score References: describe_score).

Parses with ``defusedxml``, never music21, and has no MCP imports: engines may use it. Error
messages give at most a line and column, never document text.
"""

from __future__ import annotations

import codecs
import os
import re
import zipfile
import zlib
from fractions import Fraction
from pathlib import Path
from typing import Iterable, Iterator
from xml.etree.ElementTree import Element, ParseError

import defusedxml.ElementTree as SafeET
from defusedxml import DefusedXmlException

from .errors import ProcessingError

__all__ = ["SCORE_ROOTS", "ScoreFormatError", "read_score_file", "parse_score", "describe_score", "score_summary"]

SCORE_ROOTS = ("score-partwise", "score-timewise")

_MEMBER_SUFFIXES = (".musicxml", ".xml")
_CONTAINER = "META-INF/container.xml"
_CONTAINER_MAX_BYTES = 64 * 1024
_BYTE_DECLARATION = re.compile(rb"""^\s*<\?xml[^>]*?encoding\s*=\s*["']([A-Za-z0-9._:-]{1,40})["']""")
_TEXT_DECLARATION = re.compile(r"""^(\s*<\?xml\b[^>]*?)\s+encoding\s*=\s*(["'])[^"']*\2""")

_STEPS = "CDEFGAB"
_SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
# Diatonic steps for a chromatic transposition without <diatonic>, by semitones mod 12.
_DIATONIC_STEPS = (0, 1, 1, 2, 2, 3, 3, 4, 5, 5, 6, 6)
# Position of the tonic on the line of fifths, relative to the major key with the same signature.
_MODE_OFFSETS = {
    "major": 0, "ionian": 0, "minor": 3, "aeolian": 3, "dorian": 2,
    "phrygian": 4, "lydian": -1, "mixolydian": 1, "locrian": 5,
}
_CLEFS = {
    ("G", "2", 0): "treble",
    ("G", "2", -1): "treble_8vb",
    ("F", "4", 0): "bass",
    ("C", "3", 0): "alto",
    ("C", "4", 0): "tenor",
}
_DEFAULT_CLEF_LINES = {"G": "2", "F": "4", "C": "3"}
_BEAT_UNITS = {
    "maxima": 32, "long": 16, "breve": 8, "whole": 4, "half": 2, "quarter": 1, "eighth": 0.5,
    "16th": 0.25, "32nd": 0.125, "64th": 0.0625, "128th": 0.03125, "256th": 0.015625,
}
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


class ScoreFormatError(ProcessingError):
    """The score is not well-formed MusicXML, or not a readable ``.mxl`` (INVALID_INPUT)."""

    def __init__(self, message: str, *, hint: str | None = None):
        super().__init__(message, "INVALID_INPUT", hint=hint)


# --- Reading files ---------------------------------------------------------------------------


def read_score_file(path: str | os.PathLike, *, max_bytes: int) -> str:
    """Return the MusicXML text of a ``.musicxml``, ``.xml`` or ``.mxl`` file.

    ``.mxl``: the rootfile named in ``META-INF/container.xml``, otherwise the first ``.musicxml`` or
    ``.xml`` member outside ``META-INF/``. A member whose uncompressed size exceeds ``max_bytes`` is
    rejected from its header before extracting, and every read is bounded, so neither a large file
    nor a zip bomb is loaded (FILE_TOO_LARGE). The text is decoded from its BOM or declared
    encoding (default UTF-8) and a BOM is removed. Bad archives or undecodable text: INVALID_INPUT.
    Callers confine the path first (``paths.confine_read_path``).
    """
    path = Path(path)
    data = _read_mxl(path, max_bytes) if path.suffix.lower() == ".mxl" else _read_plain(path, max_bytes)
    return _decode(data)


def _read_plain(path: Path, max_bytes: int) -> bytes:
    try:
        with path.open("rb") as file:
            data = file.read(max_bytes + 1)
    except OSError:
        raise _not_found(path) from None
    if len(data) > max_bytes:
        raise _too_large(max_bytes)
    return data


def _read_mxl(path: Path, max_bytes: int) -> bytes:
    try:
        with zipfile.ZipFile(path) as archive:
            member = _score_member(archive)
            if member.file_size > max_bytes:
                raise _too_large(max_bytes)
            with archive.open(member) as file:
                data = file.read(max_bytes + 1)
    except ProcessingError:
        raise
    except FileNotFoundError:
        raise _not_found(path) from None
    except (zipfile.BadZipFile, zlib.error, OSError, EOFError, RuntimeError, NotImplementedError, ValueError):
        # Corrupt or truncated archives, CRC mismatches, encryption, unsupported compression.
        raise ScoreFormatError("The file is not a valid .mxl (compressed MusicXML) archive") from None
    if len(data) > max_bytes:
        raise _too_large(max_bytes)
    return data


def _score_member(archive: zipfile.ZipFile) -> zipfile.ZipInfo:
    rootfile = _container_rootfile(archive)
    if rootfile is not None and rootfile in archive.namelist():
        return archive.getinfo(rootfile)
    for info in archive.infolist():
        name = info.filename
        if not info.is_dir() and not name.startswith("META-INF/") and name.lower().endswith(_MEMBER_SUFFIXES):
            return info
    raise ScoreFormatError("The .mxl archive contains no MusicXML score")


def _container_rootfile(archive: zipfile.ZipFile) -> str | None:
    """The first rootfile in ``META-INF/container.xml``, or None if there is no usable one."""
    try:
        info = archive.getinfo(_CONTAINER)
        if info.file_size > _CONTAINER_MAX_BYTES:
            return None
        with archive.open(info) as file:
            container = SafeET.fromstring(file.read(_CONTAINER_MAX_BYTES + 1))
    except (KeyError, ParseError, DefusedXmlException, zipfile.BadZipFile, zlib.error, OSError, EOFError,
            RuntimeError, NotImplementedError, ValueError):
        return None
    for element in container.iter():
        if _local(element.tag) == "rootfile" and element.get("full-path"):
            return element.get("full-path")
    return None


def _decode(data: bytes) -> str:
    declared = False
    if data.startswith(codecs.BOM_UTF8):
        encoding = "utf-8-sig"
    elif data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        encoding = "utf-32"
    elif data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        encoding = "utf-16"
    elif data.startswith(b"<\x00?\x00"):
        encoding = "utf-16-le"
    elif data.startswith(b"\x00<\x00?"):
        encoding = "utf-16-be"
    elif match := _BYTE_DECLARATION.match(data):
        encoding, declared = match.group(1).decode("ascii"), True
    else:
        encoding = "utf-8"
    try:
        return data.decode(encoding).removeprefix("\ufeff")
    except LookupError:
        raise ScoreFormatError("The score declares an unknown text encoding") from None
    except UnicodeDecodeError:
        if declared:
            raise ScoreFormatError("The score text does not match its declared encoding") from None
        raise ScoreFormatError("The score is not valid UTF-8 text") from None


def _not_found(path: Path) -> ProcessingError:
    return ProcessingError(f"Score file does not exist or cannot be read: {path}", "FILE_NOT_FOUND")


def _too_large(max_bytes: int) -> ProcessingError:
    return ProcessingError(f"The score is larger than the limit of {max_bytes} bytes", "FILE_TOO_LARGE")


# --- Parsing ---------------------------------------------------------------------------------


def parse_score(text: str | bytes) -> Element:
    """Parse MusicXML safely and return the root element (``score-partwise`` or ``score-timewise``).

    Entity declarations and external references are refused, so entity-expansion and XXE attacks
    fail. Bytes are decoded like files (BOM, then declared encoding, then UTF-8). Raises
    ScoreFormatError (INVALID_INPUT) without echoing document text.
    """
    if isinstance(text, bytes):
        text = _decode(text)
    # Parse UTF-8 bytes without the encoding declaration: a str keeping a declaration such as
    # UTF-16 can fail to parse on some Python versions.
    data = _TEXT_DECLARATION.sub(r"\1", text.removeprefix("\ufeff"), count=1).encode("utf-8")
    try:
        root = SafeET.fromstring(data)
    except DefusedXmlException:
        raise ScoreFormatError("The score declares entities or external references, which are not allowed") from None
    except ParseError as error:
        line, column = error.position
        raise ScoreFormatError(f"Score is not well-formed XML at line {line}, column {column}") from None
    except (ValueError, LookupError):
        raise ScoreFormatError("The score text could not be decoded") from None
    if _local(root.tag) not in SCORE_ROOTS:
        raise ScoreFormatError("Not a MusicXML score: the root element must be score-partwise or score-timewise")
    return root


# --- Describing ------------------------------------------------------------------------------


def describe_score(text: str | bytes) -> dict:
    """Title, composer, key, time, tempo, parts, measures, lyrics and duration of a score.

    Parts are ``{id, name, abbreviation, clef, range: {low, high}}`` in part-list order, with the
    MusicXML score-part IDs the part resolver uses. Ranges are sounding pitches such as ``"F#4"``.
    Measures and duration come from the first part. Raises ScoreFormatError.
    """
    root = parse_score(text)
    music = _music_by_part(root)
    first = next(iter(music.values()), [])
    tempo = _tempo(music)
    quarters = float(_duration_quarters(first))
    return {
        "title": _title(root),
        "composer": _text(root.find("identification/creator[@type='composer']")),
        "key": _key(music),
        "time": _time(music),
        "tempo_bpm": tempo,
        "parts": _parts(root, music),
        "measures": len(first),
        "has_lyrics": next(root.iter("lyric"), None) is not None,
        "duration_quarters": round(quarters, 3),
        "duration_seconds": round(quarters * 60 / tempo, 2) if tempo else None,
    }


def score_summary(text: str | bytes) -> dict:
    """The short form returned next to a score path: ``{title, parts: [{id, name, range}],
    measures, key, time, tempo_bpm}``."""
    description = describe_score(text)
    return {
        "title": description["title"],
        "parts": [{key: part[key] for key in ("id", "name", "range")} for part in description["parts"]],
        "measures": description["measures"],
        "key": description["key"],
        "time": description["time"],
        "tempo_bpm": description["tempo_bpm"],
    }


def _music_by_part(root: Element) -> dict[str, list[Element]]:
    """Part ID -> the part's measure contents in order; timewise scores are regrouped by part."""
    music: dict[str, list[Element]] = {}
    if _local(root.tag) == "score-partwise":
        for part in root.findall("part"):
            music.setdefault(part.get("id", ""), []).extend(part.findall("measure"))
    else:
        for measure in root.findall("measure"):
            for part in measure.findall("part"):
                music.setdefault(part.get("id", ""), []).append(part)
    return music


def _elements(music: dict[str, list[Element]], tag: str) -> Iterator[Element]:
    """Elements named ``tag`` in part order, then measure order, for either score layout."""
    for measures in music.values():
        for measure in measures:
            yield from measure.iter(tag)


def _title(root: Element) -> str | None:
    for found in (root.find("work/work-title"), root.find("movement-title"), root.find("credit/credit-words")):
        if (title := _text(found)) is not None:
            return title
    return None


def _parts(root: Element, music: dict[str, list[Element]]) -> list[dict]:
    listed = {score_part.get("id", ""): score_part for score_part in root.findall("part-list/score-part")}
    parts = []
    for part_id in [*listed, *(part_id for part_id in music if part_id not in listed)]:
        score_part = listed.get(part_id)
        measures = music.get(part_id, [])
        parts.append(
            {
                "id": part_id,
                "name": _text(score_part.find("part-name")) if score_part is not None else None,
                "abbreviation": _text(score_part.find("part-abbreviation")) if score_part is not None else None,
                "clef": _clef(measures),
                "range": _range(measures),
            }
        )
    return parts


def _key(music: dict[str, list[Element]]) -> str | None:
    for key in _elements(music, "key"):
        fifths = _int(_text(key.find("fifths")))
        if fifths is None:
            continue
        mode = (_text(key.find("mode")) or "major").lower()
        offset = _MODE_OFFSETS.get(mode)
        if offset is None:
            # A mode without a tonic (e.g. "none"): describe the signature instead.
            count = abs(fifths)
            if count == 0:
                return "no sharps or flats"
            kind = "sharp" if fifths > 0 else "flat"
            return f"{count} {kind}{'s' if count > 1 else ''}"
        position = fifths + offset + 1  # F=0, C=1, G=2 ... on the line of fifths
        return f"{'FCGDAEB'[position % 7]}{_accidental(position // 7)} {mode}"
    return None


def _time(music: dict[str, list[Element]]) -> str | None:
    for time in _elements(music, "time"):
        beats, beat_type = _text(time.find("beats")), _text(time.find("beat-type"))
        if beats and beat_type:
            return f"{beats}/{beat_type}"
    return None


def _tempo(music: dict[str, list[Element]]) -> int | float | None:
    """The first ``<sound tempo>``, else the first ``<metronome>`` in quarter notes per minute."""
    for sound in _elements(music, "sound"):
        if (bpm := _number(sound.get("tempo"))) is not None and bpm > 0:
            return _tidy(bpm)
    for metronome in _elements(music, "metronome"):
        per_minute = _number(_text(metronome.find("per-minute")))
        if not per_minute:
            continue
        unit = _BEAT_UNITS.get(_text(metronome.find("beat-unit")) or "quarter", 1)
        dots = len(metronome.findall("beat-unit-dot"))
        return _tidy(per_minute * unit * (2 - 0.5**dots))
    return None


def _clef(measures: Iterable[Element]) -> str | None:
    clef = next((found for measure in measures for found in measure.iter("clef")), None)
    if clef is None:
        return None
    sign = _text(clef.find("sign")) or ""
    if sign == "percussion":
        return "percussion"
    line = _text(clef.find("line")) or _DEFAULT_CLEF_LINES.get(sign, "")
    octave = _int(_text(clef.find("clef-octave-change"))) or 0
    return _CLEFS.get((sign, line, octave), f"{sign}{line}")


def _range(measures: Iterable[Element]) -> dict | None:
    """Lowest and highest sounding pitch, compared by MIDI number; None without pitches."""
    low = high = None
    shift = (0, 0.0)
    for measure in measures:
        for element in measure.iter():
            if element.tag == "transpose":
                shift = _transposition(element)
            elif element.tag == "note" and (pitch := element.find("pitch")) is not None:
                sounding = _sounding(pitch, shift)
                if sounding is None:
                    continue
                if low is None or sounding[0] < low[0]:
                    low = sounding
                if high is None or sounding[0] > high[0]:
                    high = sounding
    return {"low": low[1], "high": high[1]} if low else None


def _transposition(transpose: Element) -> tuple[int, float]:
    """(diatonic steps, semitones) from written to sounding pitch."""
    chromatic = _signed(_text(transpose.find("chromatic")))
    if chromatic is None:
        return (0, 0.0)
    diatonic = _int(_text(transpose.find("diatonic")))
    if diatonic is None:
        whole = round(chromatic)
        diatonic = 7 * (whole // 12) + _DIATONIC_STEPS[whole % 12]
    octaves = _int(_text(transpose.find("octave-change"))) or 0
    return (diatonic + 7 * octaves, chromatic + 12 * octaves)


def _sounding(pitch: Element, shift: tuple[int, float]) -> tuple[float, str] | None:
    """(MIDI number, name such as "Bb3") of a written pitch after transposition."""
    step = _text(pitch.find("step"))
    octave = _int(_text(pitch.find("octave")))
    alter = _signed(_text(pitch.find("alter"))) or 0.0
    if step not in _SEMITONES or octave is None:
        return None
    diatonic, chromatic = shift
    midi = (octave + 1) * 12 + _SEMITONES[step] + alter + chromatic
    index = _STEPS.index(step) + 7 * octave + diatonic
    step, octave = _STEPS[index % 7], index // 7
    accidental = round(midi - ((octave + 1) * 12 + _SEMITONES[step]))
    return midi, f"{step}{_accidental(accidental)}{octave}"


def _duration_quarters(measures: Iterable[Element]) -> Fraction:
    """Sum of each measure's furthest position: chord notes do not advance, backup steps back."""
    divisions = Fraction(1)
    total = Fraction(0)
    for measure in measures:
        position = furthest = start = Fraction(0)
        for element in measure:
            if element.tag == "attributes":
                found = _fraction(_text(element.find("divisions")))
                if found:
                    divisions = found
            elif element.tag == "note":
                if element.find("grace") is not None:
                    continue
                length = (_fraction(_text(element.find("duration"))) or 0) / divisions
                if element.find("chord") is not None:
                    furthest = max(furthest, start + length)
                else:
                    start = position
                    position += length
                    furthest = max(furthest, position)
            elif element.tag == "backup":
                position = max(Fraction(0), position - (_fraction(_text(element.find("duration"))) or 0) / divisions)
            elif element.tag == "forward":
                position += (_fraction(_text(element.find("duration"))) or 0) / divisions
                furthest = max(furthest, position)
        total += furthest
    return total


# --- Small helpers ---------------------------------------------------------------------------


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _text(element: Element | None) -> str | None:
    """Stripped text, or None when the element or its text is missing or blank."""
    if element is None or element.text is None:
        return None
    return element.text.strip() or None


def _int(text: str | None) -> int | None:
    try:
        return int(text) if text is not None else None
    except ValueError:
        return None


def _signed(text: str | None) -> float | None:
    try:
        return float(text) if text is not None else None
    except ValueError:
        return None


def _fraction(text: str | None) -> Fraction | None:
    try:
        value = Fraction(text) if text is not None else None
    except (ValueError, ZeroDivisionError):
        return None
    return value if value is not None and value > 0 else None


def _number(text: str | None) -> float | None:
    """The first unsigned number in ``text`` ("c. 96" -> 96.0)."""
    match = _NUMBER.search(text) if text else None
    return float(match.group()) if match else None


def _tidy(value: float) -> int | float:
    value = round(value, 2)
    return int(value) if value == int(value) else value


def _accidental(alter: int) -> str:
    return "#" * alter if alter > 0 else "b" * -alter
