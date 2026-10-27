"""Deprecated parameter names (docs/conventions.md, Deprecated Parameter Names).

No MCP imports.
"""

from __future__ import annotations

import logging
from typing import Any

from .errors import ProcessingError

logger = logging.getLogger(__name__)

# Deprecated names already warned about in this process; one warning each is enough.
_warned: set[str] = set()


def aliased(arguments: dict, name: str, deprecated: str) -> Any:
    """Return the value passed as ``name`` or its deprecated alias, or None if neither.

    Raises ProcessingError(INVALID_PARAMETER) when both are passed with different values.
    """
    value = arguments.get(name)
    old_value = arguments.get(deprecated)

    if old_value is None:
        return value
    if value is not None:
        if value != old_value:
            raise ProcessingError(
                f"'{name}' and its deprecated alias '{deprecated}' were both given with "
                "different values.",
                "INVALID_PARAMETER",
                hint=f"Pass only '{name}'.",
            )
        return value

    if deprecated not in _warned:
        _warned.add(deprecated)
        logger.warning("Parameter '%s' is deprecated; use '%s' instead.", deprecated, name)
    return old_value
