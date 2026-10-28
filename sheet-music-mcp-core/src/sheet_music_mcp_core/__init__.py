"""Shared helpers for the sheet-music MCP servers.

Import submodules directly. ``errors``, ``parts``, ``params``, ``annotations``, ``paths``,
``scores`` and ``measures`` do not import ``mcp`` (nor music21), so engines may use them;
``content``, ``references``, ``ui`` and ``wiring`` do.
"""

__version__ = "0.3.1"
