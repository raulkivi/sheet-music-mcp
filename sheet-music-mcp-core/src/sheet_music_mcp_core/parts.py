"""Voice-part selection (docs/conventions.md, Part Selection).

Each server converts its parsed parts to ``PartInfo`` and resolves the model's request here.
No MCP imports and no music21: engines may use it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from .errors import ProcessingError

_ROLE_ALIASES = {
    "soprano": ("s", "sop", "soprano", "soprani", "sopran", "cantus", "canto"),
    "mezzo-soprano": ("ms", "mez", "mezzo", "mezzo soprano", "mezzosoprano"),
    "alto": ("a", "alt", "alto", "alti", "contralto", "altus"),
    "tenor": ("t", "ten", "tenor", "tenori"),
    "baritone": ("bar", "bari", "bariton", "baritone", "baritono"),
    "bass": ("b", "bas", "bass", "bassi", "basso", "bassus"),
}
_ROLE_BY_ALIAS = {alias: role for role, aliases in _ROLE_ALIASES.items() for alias in aliases}
_ROMAN = {"i": "1", "ii": "2", "iii": "3", "iv": "4"}
_HINT = "Pass one of the listed part names or IDs."


@dataclass(frozen=True)
class PartInfo:
    id: str
    name: str


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
        # Tier 2: name or ID after normalising.
        named = [p for p in available if normalised in (_normalise(p.name), _normalise(p.id))]
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
