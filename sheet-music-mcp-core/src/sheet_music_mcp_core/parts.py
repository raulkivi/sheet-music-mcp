"""Voice-part selection (docs/conventions.md, Part Selection).

Each server converts its parsed parts to ``PartInfo`` (``music21_part_infos`` for music21 scores)
and resolves the model's request here. No MCP imports and no music21 import: engines may use it.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence

from .errors import ProcessingError

_ROLE_ALIASES = {
    "soprano": ("s", "sop", "soprano", "soprani", "sopran", "cantus", "canto", "tr", "treble", "trebles"),
    "mezzo-soprano": ("ms", "mez", "mezzo", "mezzo soprano", "mezzosoprano"),
    "alto": ("a", "alt", "alto", "alti", "contralto", "altus"),
    "countertenor": ("ct", "countertenor", "counter tenor", "countertenors", "contratenor", "contra tenor"),
    "tenor": ("t", "ten", "tenor", "tenori"),
    "baritone": ("bar", "bari", "bariton", "baritone", "baritono"),
    "bass": ("b", "bas", "bass", "bassi", "basso", "bassus"),
}
_ROLE_BY_ALIAS = {alias: role for role, aliases in _ROLE_ALIASES.items() for alias in aliases}
_ROLE_LABELS = {
    "soprano": "S", "mezzo-soprano": "Ms", "alto": "A", "countertenor": "Ct",
    "tenor": "T", "baritone": "Bar", "bass": "B",
}
_ROMAN = {"i": "1", "ii": "2", "iii": "3", "iv": "4"}
_HINT = "Pass one of the listed part names or IDs."


@dataclass(frozen=True)
class PartInfo:
    id: str
    name: str
    abbreviation: str = ""


class PartSelectionError(ProcessingError):
    """A part request matched no part, or several where one was required."""

    def __init__(self, message: str, choices: list[str]):
        super().__init__(message, "INVALID_PARAMETER", hint=_HINT, choices=choices)


def resolve_parts(requested: Sequence[str], available: Sequence[PartInfo]) -> list[str]:
    """Return the IDs of the parts matching each request, in request order, without duplicates."""
    resolved: list[str] = []
    for request in requested:
        for part in _match(request, available):
            if part.id not in resolved:
                resolved.append(part.id)
    return resolved


def resolve_part(requested: str, available: Sequence[PartInfo]) -> str:
    """Return the ID of the one part matching ``requested``; reject ambiguous requests."""
    matches = _match(requested, available)
    if len(matches) > 1:
        raise PartSelectionError(
            f"Part '{requested}' matches {len(matches)} parts; choose one.",
            [_label(p) for p in matches],
        )
    return matches[0].id


def _match(request: str, available: Sequence[PartInfo]) -> list[PartInfo]:
    # Tier 1: exact ID.
    exact = [p for p in available if p.id == request]
    if exact:
        return exact

    normalised = _normalise(request)
    if normalised:
        # Tier 2: name, abbreviation or ID after normalising.
        named = [
            p
            for p in available
            if normalised in (_normalise(p.name), _normalise(p.abbreviation), _normalise(p.id))
        ]
        if named:
            return named

        # Tier 3: voice role, optionally with a divisi number.
        wanted = _role(normalised)
        if wanted is not None:
            role, number = wanted
            by_role = [
                p
                for p in available
                if (found := _role(_normalise(p.name))) is not None
                and found[0] == role
                and (number is None or found[1] == number)
            ]
            if by_role:
                return by_role

    raise PartSelectionError(f"Part '{request}' not found.", [_label(p) for p in available])


def voice_label(name: str | None) -> str | None:
    """Short voice label for a part name ("Soprano 1" -> "S1", "Alto II" -> "A2"), or None
    when the name is not a voice role."""
    found = _role(_normalise(name)) if name else None
    if found is None:
        return None
    role, number = found
    return _ROLE_LABELS[role] + (number or "")


def music21_part_infos(parts: Iterable) -> list[PartInfo]:
    """One PartInfo per music21 part, in score order, with a stable and unique ID.

    music21 replaces ``part.id`` with the part name, repeats it for same-named parts and gives
    unnamed parts a new integer on every parse, so the ID is the MusicXML score-part id kept as
    ``instrument.partId`` (``"P1"``). Parts without one get ``"P<position>"``. Staves of one
    multi-staff part share a score-part id and keep music21's staff ids (``"P3-Staff1"``).
    Engines must select parts by position against this list, never by ``part.id``.
    """
    parts = list(parts)
    xml_ids = [_musicxml_part_id(part) or f"P{position}" for position, part in enumerate(parts, 1)]
    xml_id_counts = Counter(xml_ids)
    music21_id_counts = Counter(getattr(part, "id", None) for part in parts)

    infos: list[PartInfo] = []
    seen: set[str] = set()
    occurrence: Counter = Counter()
    for position, (part, xml_id) in enumerate(zip(parts, xml_ids), 1):
        part_id = xml_id
        if xml_id_counts[xml_id] > 1:
            occurrence[xml_id] += 1
            music21_id = getattr(part, "id", None)
            if isinstance(music21_id, str) and music21_id and music21_id_counts[music21_id] == 1:
                part_id = music21_id
            else:
                part_id = f"{xml_id}-{occurrence[xml_id]}"
        if part_id in seen:
            part_id = f"{part_id}-{position}"
        seen.add(part_id)
        infos.append(
            PartInfo(
                part_id,
                getattr(part, "partName", None) or "",
                getattr(part, "partAbbreviation", None) or "",
            )
        )
    return infos


def _musicxml_part_id(part) -> str | None:
    get_instrument = getattr(part, "getInstrument", None)
    instrument = get_instrument(returnDefault=False) if get_instrument else None
    part_id = getattr(instrument, "partId", None)
    return part_id if isinstance(part_id, str) and part_id else None


def _normalise(text: str) -> str:
    words = re.sub(r"[^\w\s]", " ", text.casefold()).split()
    return " ".join(_ROMAN.get(word, word) for word in words)


def _role(normalised: str) -> tuple[str, str | None] | None:
    """Split 'alto 1' / 'a1' / 'alto' into (role, divisi number or None)."""
    match = re.fullmatch(r"(.*?) ?(\d+)?", normalised)
    base, number = match.group(1), match.group(2)
    role = _ROLE_BY_ALIAS.get(base)
    return (role, number) if role is not None else None


def _label(part: PartInfo) -> str:
    return f"{part.name} ({part.id})" if part.name else part.id
