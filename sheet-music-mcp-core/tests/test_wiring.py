"""Handler wiring shared by every server: input validation and error results that mcp 2.x
low-level handlers no longer provide themselves (CLAUDE.md, MCP stdio pattern)."""

import asyncio
import logging

from mcp import Client
from mcp.server import Server
from mcp.types import CallToolResult, TextContent, Tool

from sheet_music_mcp_core.wiring import make_handlers

ECHO = Tool(
    name="echo",
    description="Echo a word",
    input_schema={
        "type": "object",
        "properties": {"word": {"type": "string"}},
        "required": ["word"],
    },
)
PART = Tool(
    name="part",
    description="Needs a part under either name",
    input_schema={
        "type": "object",
        "properties": {
            "musicxml": {"type": "string"},
            "part": {"type": "string"},
            "part_id": {"type": "string"},
        },
        "required": ["musicxml"],
        "anyOf": [{"required": ["part"]}, {"required": ["part_id"]}],
    },
)
STRUCTURED = Tool(name="structured", description="Return a full result", input_schema={"type": "object"})


async def _list_tools():
    return [ECHO, PART, STRUCTURED]


async def _call_tool(name, arguments):
    if name == "echo":
        if arguments["word"] == "boom":
            raise RuntimeError("exploded")
        return [TextContent(type="text", text=arguments["word"])]
    if name == "structured":
        return CallToolResult(
            content=[TextContent(type="text", text="{}")], structured_content={"ok": True}
        )
    raise ValueError(f"Unknown tool: {name}")


def _server(call_tool=_call_tool, **kwargs):
    on_list_tools, on_call_tool = make_handlers(_list_tools, call_tool, **kwargs)
    return Server("test", on_list_tools=on_list_tools, on_call_tool=on_call_tool)


def _with_client(server, call):
    async def _go():
        async with Client(server) as client:
            return await call(client)

    return asyncio.run(_go())


def test_lists_tools():
    result = _with_client(_server(), lambda c: c.list_tools())

    assert [t.name for t in result.tools] == ["echo", "part", "structured"]


def test_calls_tool_and_wraps_content():
    result = _with_client(_server(), lambda c: c.call_tool("echo", {"word": "hi"}))

    assert not result.is_error
    assert result.content[0].text == "hi"


def test_rejects_arguments_that_fail_the_schema():
    result = _with_client(_server(), lambda c: c.call_tool("echo", {}))

    assert result.is_error
    assert result.content[0].text.startswith("Input validation error:")


def test_tool_exception_becomes_error_result():
    result = _with_client(_server(), lambda c: c.call_tool("echo", {"word": "boom"}))

    assert result.is_error
    assert result.content[0].text == "exploded"


def test_unknown_tool_becomes_error_result():
    result = _with_client(_server(), lambda c: c.call_tool("nope", {}))

    assert result.is_error
    assert "nope" in result.content[0].text


def test_call_tool_result_is_passed_through():
    result = _with_client(_server(), lambda c: c.call_tool("structured", {}))

    assert not result.is_error
    assert result.structured_content == {"ok": True}


def test_passes_request_context_when_asked():
    seen = {}

    async def call_tool(name, arguments, ctx=None):
        seen["ctx"] = ctx
        return [TextContent(type="text", text="ok")]

    _with_client(_server(call_tool, pass_context=True), lambda c: c.call_tool("echo", {"word": "x"}))

    assert seen["ctx"] is not None
    assert seen["ctx"].request_id is not None


def test_logs_failures_under_the_given_logger(caplog):
    caplog.set_level(logging.ERROR)

    _with_client(
        _server(logger=logging.getLogger("render_mcp.server")),
        lambda c: c.call_tool("echo", {"word": "boom"}),
    )

    [record] = [r for r in caplog.records if "failed" in r.getMessage()]
    assert record.name == "render_mcp.server"
    assert "echo" in record.getMessage()


def test_logs_under_the_core_logger_by_default(caplog):
    caplog.set_level(logging.ERROR)

    _with_client(_server(), lambda c: c.call_tool("echo", {"word": "boom"}))

    [record] = [r for r in caplog.records if "failed" in r.getMessage()]
    assert record.name == "sheet_music_mcp_core.wiring"


def test_missing_alternative_names_the_parameters_without_echoing_arguments():
    score = "<score-partwise>" + "x" * 5000 + "</score-partwise>"

    result = _with_client(_server(), lambda c: c.call_tool("part", {"musicxml": score}))

    assert result.is_error
    text = result.content[0].text
    assert text == "Input validation error: one of these parameters is required: 'part', 'part_id'"
    assert "score-partwise" not in text
