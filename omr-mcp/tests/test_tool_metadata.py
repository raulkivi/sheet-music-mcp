"""Tool titles, annotation presets and server instructions (docs/conventions.md: Tool
Annotations and Titles, Server Instructions)."""

import asyncio

import pytest
from mcp import Client
from sheet_music_mcp_core.annotations import READ_ONLY, WRITES_FILE_DOWNLOADS

from omr_mcp.server import app, list_tools

EXPECTED = {
    "recognize_sheet": ("Recognize sheet music", WRITES_FILE_DOWNLOADS),
    "recognize_sheet_to_file": ("Recognize sheet music to file", WRITES_FILE_DOWNLOADS),
    "recognize_sheets": ("Recognize multi-page sheet music", WRITES_FILE_DOWNLOADS),
    "list_capabilities": ("OMR capabilities", READ_ONLY),
    "list_supported_formats": ("OMR formats (deprecated)", READ_ONLY),
    "health_check": ("OMR health check", READ_ONLY),
}

# Phrases the instructions must contain: the routing knowledge the model needs up front.
# 'musicxml_path': large results come back as a path to pass on (UX Wave 2).
INSTRUCTION_PHRASES = ('audiveris', '300+ DPI', 'musicxml_path')


def _tools():
    return {tool.name: tool for tool in asyncio.run(list_tools())}


def test_every_tool_has_an_expected_entry():
    assert set(_tools()) == set(EXPECTED)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_title(name):
    assert _tools()[name].title == EXPECTED[name][0]


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_annotation_preset(name):
    annotations = _tools()[name].annotations

    assert annotations is not None
    assert annotations.model_dump(exclude_none=True) == dict(EXPECTED[name][1])


def test_instructions_reach_the_client():
    async def _go():
        async with Client(app) as client:
            return client.instructions

    instructions = asyncio.run(_go())

    assert instructions
    for phrase in INSTRUCTION_PHRASES:
        assert phrase in instructions
