"""Handler wiring for ``Server(name, on_list_tools=..., on_call_tool=...)``.

mcp 2.x low-level handlers neither validate input nor catch tool errors; these handlers keep the
1.x decorator behaviour clients rely on.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

import jsonschema
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, TextContent, Tool

_logger = logging.getLogger(__name__)

ListTools = Callable[[], Awaitable[list[Tool]]]
CallTool = Callable[..., Awaitable["list | CallToolResult"]]


def make_handlers(
    list_tools: ListTools,
    call_tool: CallTool,
    *,
    pass_context: bool = False,
    logger: logging.Logger | None = None,
):
    """Return ``(on_list_tools, on_call_tool)`` for ``Server(...)``.

    ``call_tool(name, arguments)`` returns a list of content blocks or a full ``CallToolResult``.
    With ``pass_context=True`` it is called as ``call_tool(name, arguments, ctx)``, for tools that
    need the request context (progress notifications). Failures are logged to ``logger``, the
    server's own logger (docs/conventions.md: logger name = package name).
    """
    log = logger or _logger

    async def on_list_tools(ctx, params) -> ListToolsResult:
        return ListToolsResult(tools=await list_tools())

    async def on_call_tool(ctx, params: CallToolRequestParams) -> CallToolResult:
        arguments = params.arguments or {}
        tool = next((t for t in await list_tools() if t.name == params.name), None)
        if tool is not None:
            try:
                jsonschema.validate(instance=arguments, schema=tool.input_schema)
            except jsonschema.ValidationError as e:
                return _error_result(f"Input validation error: {e.message}")
        try:
            if pass_context:
                result = await call_tool(params.name, arguments, ctx)
            else:
                result = await call_tool(params.name, arguments)
        except Exception as e:
            log.error("Tool %s failed: %s", params.name, e)
            return _error_result(str(e))
        if isinstance(result, CallToolResult):
            return result
        return CallToolResult(content=result)

    return on_list_tools, on_call_tool


def _error_result(message: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=message)], is_error=True)
