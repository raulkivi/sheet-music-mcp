"""The reference/target score pair the comparison tools take (docs/conventions.md, Score References).

Each side is given inline (``reference_xml`` / ``target_xml``) or as a file path
(``reference_path`` / ``target_path``), exactly one of each. Paths are read through the shared read
policy in ``sheet_music_mcp_core.references.load_score``; this module only names the pair, builds
its schema and keeps the server's own check of inline text.
"""

from __future__ import annotations

from dataclasses import dataclass

from sheet_music_mcp_core.errors import ProcessingError
from sheet_music_mcp_core.references import (
    exactly_one,
    load_score,
    score_input_properties,
)

from .utils import validate_musicxml

__all__ = ["INPUT_PARAMETERS", "REFERENCE", "SIDES", "TARGET", "ScoreSide", "load_pair", "pair_schema"]


@dataclass(frozen=True)
class ScoreSide:
    """One side of the comparison: its inline and path parameter names."""

    inline: str
    path: str
    what: str
    inline_description: str

    def properties(self) -> dict:
        """Schema properties for this side, keeping the server's own inline description."""
        properties = score_input_properties(self.inline, self.path, what=self.what)
        properties[self.inline] = {
            "type": "string",
            "description": f"{self.inline_description}. Give this or '{self.path}', not both.",
        }
        return properties

    async def load(self, arguments: dict, ctx) -> str:
        """The MusicXML text of this side. Raises ProcessingError.

        Inline text keeps the prefixed ``reference_xml: ...`` check it always had; a file was
        already checked to be well-formed MusicXML by ``load_score``.
        """
        text = await load_score(arguments, ctx, inline=self.inline, path=self.path)
        if arguments.get(self.inline) is not None:
            ok, err = validate_musicxml(text)
            if not ok:
                raise ProcessingError(f"{self.inline}: {err}", "INVALID_INPUT")
        return text


REFERENCE = ScoreSide(
    "reference_xml", "reference_path", "the reference score", "Reference MusicXML document as a string"
)
TARGET = ScoreSide(
    "target_xml",
    "target_path",
    "the target score",
    "Target MusicXML document as a string, compared against the reference",
)
SIDES = (REFERENCE, TARGET)
INPUT_PARAMETERS = [name for side in SIDES for name in (side.inline, side.path)]


def pair_schema(extra_properties: dict | None = None) -> dict:
    """The input schema of a tool taking the pair, plus its own ``extra_properties``."""
    properties: dict = {}
    for side in SIDES:
        properties.update(side.properties())
    properties.update(extra_properties or {})
    return {
        "type": "object",
        "properties": properties,
        "allOf": [exactly_one(side.inline, side.path) for side in SIDES],
    }


async def load_pair(arguments: dict, ctx) -> tuple[str, str]:
    """The reference and target MusicXML texts, reference first. Raises ProcessingError."""
    reference = await REFERENCE.load(arguments, ctx)
    target = await TARGET.load(arguments, ctx)
    return reference, target
