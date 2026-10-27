"""Handler wiring for ``Server(name, on_list_tools=..., on_call_tool=...)``.

mcp 2.x low-level handlers neither validate input nor catch tool errors; these handlers keep the
1.x decorator behaviour clients rely on.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

import jsonschema
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, Tool

from .content import error_content, processing_error_content
from .errors import ProcessingError

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

    Validation failures (INVALID_PARAMETER) and exceptions a tool did not handle itself
    (PROCESSING_FAILED, or a ProcessingError's own code, hint and choices) come back as ``isError``
    results carrying the ``{error, error_code}`` envelope.

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
                return _error_result(
                    error_content(f"Input validation error: {_describe(e)}", "INVALID_PARAMETER")
                )
        try:
            if pass_context:
                result = await call_tool(params.name, arguments, ctx)
            else:
                result = await call_tool(params.name, arguments)
        except Exception as e:
            log.error("Tool %s failed: %s", params.name, e)
            if isinstance(e, ProcessingError):
                return _error_result(processing_error_content(e))
            return _error_result(error_content(str(e), "PROCESSING_FAILED"))
        if isinstance(result, CallToolResult):
            return result
        return CallToolResult(content=result)

    return on_list_tools, on_call_tool


def _describe(error: jsonschema.ValidationError) -> str:
    """The validation message, without echoing the arguments for "one of" requirements.

    jsonschema's anyOf/oneOf message repeats the whole instance, which for these tools is a full
    MusicXML score; name the alternative parameters instead.
    """
    if error.validator in ("anyOf", "oneOf"):
        alternatives = [
            name
            for subschema in error.validator_value
            for name in subschema.get("required", [])
        ]
        if alternatives:
            names = ", ".join(f"'{name}'" for name in alternatives)
            return f"one of these parameters is required: {names}"
        return f"arguments do not match any allowed combination ({error.validator})"
    return error.message


def _error_result(content: list) -> CallToolResult:
    """An isError result carrying the {error, error_code} envelope (docs/conventions.md)."""
    return CallToolResult(content=content, is_error=True)
