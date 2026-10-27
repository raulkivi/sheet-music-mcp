"""Tool titles, annotation presets and server instructions (docs/conventions.md: Tool
Annotations and Titles, Server Instructions)."""

import asyncio

import pytest
from mcp import Client
from sheet_music_mcp_core.annotations import READ_ONLY, WRITES_FILE

from synth_mcp.server import app, list_tools

EXPECTED = {
    "get_parts": ("List voice parts", READ_ONLY),
    "synthesize": ("Play voice parts", WRITES_FILE),
    "list_capabilities": ("Synth capabilities", READ_ONLY),
    "health_check": ("Synth health check", READ_ONLY),
}

# Phrases the instructions must contain: the routing knowledge the model needs up front.
INSTRUCTION_PHRASES = ('get_parts', 'tempo_factor', 'SYNTH_SOUNDFONT_PATH')


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
