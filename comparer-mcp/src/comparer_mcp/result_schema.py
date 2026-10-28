"""JSON Schema for the result dataclasses, derived from their type hints.

Generated rather than hand-written so the tools' ``output_schema`` cannot drift from
``models.py`` (proposal AC-C1). No MCP imports.
"""

from __future__ import annotations

import types
import typing
from dataclasses import fields, is_dataclass

_SCALARS = {str: "string", bool: "boolean", int: "integer", float: "number"}


def json_schema_for(model: type) -> dict:
    """The schema of ``asdict(model(...))``: every field is present, optional ones may be null."""
    hints = typing.get_type_hints(model)
    return {
        "type": "object",
        "properties": {f.name: _schema_of(hints[f.name]) for f in fields(model)},
        "required": [f.name for f in fields(model)],
    }


def _schema_of(hint) -> dict:
    if hint in _SCALARS:
        return {"type": _SCALARS[hint]}
    if is_dataclass(hint):
        return json_schema_for(hint)
    origin = typing.get_origin(hint)
    args = typing.get_args(hint)
    if origin is list:
        return {"type": "array", "items": _schema_of(args[0])}
    if origin in (typing.Union, types.UnionType):
        return {"anyOf": [_schema_of(arg) if arg is not type(None) else {"type": "null"} for arg in args]}
    raise TypeError(f"No JSON Schema mapping for {hint!r}")
