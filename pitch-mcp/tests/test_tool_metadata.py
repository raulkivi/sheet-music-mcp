"""Tool titles, annotation presets and server instructions (docs/conventions.md: Tool
Annotations and Titles, Server Instructions)."""

import asyncio

import pytest
from mcp import Client
from sheet_music_mcp_core.annotations import READ_ONLY, SESSION_STATE

from pitch_mcp.server import app, list_tools

EXPECTED = {
    "analyze_recording": ("Analyze a recording", READ_ONLY),
    "describe_score": ("Describe score", READ_ONLY),
    "load_score": ("Load score for practice", SESSION_STATE),
    "start_monitoring": ("Start listening (microphone)", SESSION_STATE),
    "get_current_position": ("Current singing position", READ_ONLY),
    "stop_monitoring": ("Stop listening", SESSION_STATE),
    "list_sessions": ("Practice sessions", READ_ONLY),
    "list_capabilities": ("Pitch capabilities", READ_ONLY),
    "health_check": ("Pitch health check", READ_ONLY),
}

# Phrases the instructions must contain: the routing knowledge the model needs up front.
INSTRUCTION_PHRASES = (
    'load_score', 'stop_monitoring', 'microphone', 'PITCH_SESSION_IDLE_MINUTES', 'musicxml_path',
    'describe_score',
)


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
