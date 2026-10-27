"""Shared helpers for the sheet-music MCP servers.

Import submodules directly. ``errors``, ``parts``, ``params``, ``annotations``, ``paths`` and
``scores`` do not import ``mcp`` (nor music21), so engines may use them; ``content``,
``references`` and ``wiring`` do.
"""

__version__ = "0.2.0"
