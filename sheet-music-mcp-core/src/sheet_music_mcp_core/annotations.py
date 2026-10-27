"""Tool annotation presets (docs/conventions.md, Tool Annotations and Titles).

Plain read-only mappings, so this module has no MCP import. Use them as
``Tool(..., annotations=ToolAnnotations(**READ_ONLY))``.
"""

from types import MappingProxyType

__all__ = ["READ_ONLY", "READ_ONLY_DOWNLOADS", "WRITES_FILE", "WRITES_FILE_DOWNLOADS", "SESSION_STATE"]

READ_ONLY = MappingProxyType({"read_only_hint": True, "open_world_hint": False})

# Read-only, but the first call may download models or an engine.
READ_ONLY_DOWNLOADS = MappingProxyType({"read_only_hint": True, "open_world_hint": True})

# Writes a new output file; never overwrites, so not destructive.
WRITES_FILE = MappingProxyType(
    {
        "read_only_hint": False,
        "destructive_hint": False,
        "idempotent_hint": False,
        "open_world_hint": False,
    }
)

WRITES_FILE_DOWNLOADS = MappingProxyType({**WRITES_FILE, "open_world_hint": True})

# Creates, changes or ends server-side sessions, or opens a device such as the microphone.
SESSION_STATE = MappingProxyType(
    {
        "read_only_hint": False,
        "destructive_hint": False,
        "idempotent_hint": False,
        "open_world_hint": False,
    }
)
