"""MCP protocol wiring through an in-memory client. The mcp 2.x low-level
handlers must keep what the 1.x decorators did: validate arguments against the
tool's input schema and return tool failures as isError results."""

import asyncio

from mcp import Client

from musicxml_abc_mcp.server import app, list_tools


def _with_client(call):
    async def _go():
        async with Client(app) as client:
            return await call(client)

    return asyncio.run(_go())


def test_lists_the_same_tools_as_list_tools():
    expected = {tool.name for tool in asyncio.run(list_tools())}

    result = _with_client(lambda client: client.list_tools())

    assert {tool.name for tool in result.tools} == expected


def test_calls_a_tool_through_the_protocol():
    result = _with_client(lambda client: client.call_tool("list_capabilities", {}))

    assert not result.is_error
    assert result.content[0].type == "text"


def test_rejects_arguments_that_fail_the_input_schema():
    tool = next(t for t in asyncio.run(list_tools()) if t.input_schema.get("required"))

    result = _with_client(lambda client: client.call_tool(tool.name, {}))

    assert result.is_error
    assert "Input validation error" in result.content[0].text


def test_returns_an_unknown_tool_as_an_error_result():
    result = _with_client(lambda client: client.call_tool("no_such_tool", {}))

    assert result.is_error
    assert "no_such_tool" in result.content[0].text
