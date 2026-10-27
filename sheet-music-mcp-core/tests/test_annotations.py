"""Tool annotation presets (docs/conventions.md, Tool Annotations and Titles)."""

import pytest
from mcp.types import ToolAnnotations

from sheet_music_mcp_core import annotations
from sheet_music_mcp_core.annotations import (
    READ_ONLY,
    READ_ONLY_DOWNLOADS,
    SESSION_STATE,
    WRITES_FILE,
    WRITES_FILE_DOWNLOADS,
)


def test_read_only():
    assert dict(READ_ONLY) == {"read_only_hint": True, "open_world_hint": False}


def test_read_only_downloads():
    assert dict(READ_ONLY_DOWNLOADS) == {"read_only_hint": True, "open_world_hint": True}


def test_writes_file():
    assert dict(WRITES_FILE) == {
        "read_only_hint": False,
        "destructive_hint": False,
        "idempotent_hint": False,
        "open_world_hint": False,
    }


def test_writes_file_downloads():
    assert dict(WRITES_FILE_DOWNLOADS) == {**dict(WRITES_FILE), "open_world_hint": True}


def test_session_state_is_never_read_only():
    assert dict(SESSION_STATE) == {
        "read_only_hint": False,
        "destructive_hint": False,
        "idempotent_hint": False,
        "open_world_hint": False,
    }


@pytest.mark.parametrize(
    "preset", [READ_ONLY, READ_ONLY_DOWNLOADS, WRITES_FILE, WRITES_FILE_DOWNLOADS, SESSION_STATE]
)
def test_presets_build_tool_annotations(preset):
    built = ToolAnnotations(**preset)

    assert built.read_only_hint is preset["read_only_hint"]


def test_presets_cannot_be_mutated():
    with pytest.raises(TypeError):
        READ_ONLY["read_only_hint"] = False  # type: ignore[index]


def test_module_exports_only_the_five_presets():
    assert set(annotations.__all__) == {
        "READ_ONLY",
        "READ_ONLY_DOWNLOADS",
        "WRITES_FILE",
        "WRITES_FILE_DOWNLOADS",
        "SESSION_STATE",
    }
