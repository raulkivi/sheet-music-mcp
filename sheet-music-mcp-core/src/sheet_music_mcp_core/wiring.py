"""Handler wiring for ``Server(name, on_list_tools=..., on_call_tool=..., on_list_resources=...,
on_read_resource=...)``.

mcp 2.x low-level handlers neither validate input nor catch tool errors; these handlers keep the
1.x decorator behaviour clients rely on.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Protocol

import jsonschema
from jsonschema.exceptions import best_match
from jsonschema.validators import validator_for
from mcp import MCPError
from mcp.types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    CallToolRequestParams,
    CallToolResult,
    ListResourcesResult,
    ListToolsResult,
    ReadResourceRequestParams,
    ReadResourceResult,
    Resource,
    Tool,
)

from .content import error_content, processing_error_content
from .errors import ProcessingError, error_payload

_logger = logging.getLogger(__name__)

_ALTERNATIVES = ("anyOf", "oneOf")

ListTools = Callable[[], Awaitable[list[Tool]]]
CallTool = Callable[..., Awaitable["list | CallToolResult"]]


class ResourceProvider(Protocol):
    """What the resource handlers serve; ``ui.UiRegistry`` is one."""

    def list_resources(self) -> list[Resource]: ...

    def read(self, uri: str) -> ReadResourceResult: ...


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


def make_resource_handlers(provider: ResourceProvider, *, logger: logging.Logger | None = None):
    """Return ``(on_list_resources, on_read_resource)`` for ``Server(...)``.

    A failed read reaches the client as a JSON-RPC error whose ``data`` is the
    ``{error, error_code}`` envelope plus the ``uri``: RESOURCE_NOT_FOUND as INVALID_PARAMS
    (-32602, as the spec asks), anything else as INTERNAL_ERROR. Failures are logged to ``logger``.
    """
    log = logger or _logger

    async def on_list_resources(ctx, params) -> ListResourcesResult:
        return ListResourcesResult(resources=provider.list_resources())

    async def on_read_resource(ctx, params: ReadResourceRequestParams) -> ReadResourceResult:
        uri = str(params.uri)
        try:
            return provider.read(uri)
        except Exception as e:
            log.error("Resource %s failed: %s", uri, e)
            # The SDK forwards only an MCPError's message; any other exception becomes an
            # opaque "Internal server error".
            raise _resource_error(e, uri) from e

    return on_list_resources, on_read_resource


def _resource_error(error: Exception, uri: str) -> MCPError:
    if isinstance(error, ProcessingError):
        payload = error.to_payload()
    else:
        payload = error_payload(str(error), "PROCESSING_FAILED")
    code = INVALID_PARAMS if payload["error_code"] == "RESOURCE_NOT_FOUND" else INTERNAL_ERROR
    return MCPError(code, str(error), data={**payload, "uri": uri})


def _describe(error: jsonschema.ValidationError) -> str:
    """The validation message, without echoing the arguments for "one of" requirements.

    jsonschema's anyOf/oneOf message repeats the whole instance, which for these tools is a full
    MusicXML score; name the alternative parameters instead. A oneOf that several alternatives
    match ("both given") asks for only one. Nested failures are described by their innermost
    failing anyOf/oneOf (an allOf member's failure already arrives as that member's own error).
    """
    error = _innermost_alternative(error) or error
    if error.validator in _ALTERNATIVES:
        alternatives = [
            name
            for subschema in error.validator_value
            for name in subschema.get("required", [])
        ]
        if alternatives:
            names = ", ".join(f"'{name}'" for name in alternatives)
            if error.validator == "oneOf" and _matches_several(error):
                return f"give only one of these parameters: {names}"
            return f"one of these parameters is required: {names}"
        return f"arguments do not match any allowed combination ({error.validator})"
    return error.message


def _innermost_alternative(error: jsonschema.ValidationError) -> jsonschema.ValidationError | None:
    """The deepest failing anyOf/oneOf in ``error`` and its context, or None if there is none."""
    nested = list(error.context or ())
    if isinstance(error.cause, jsonschema.ValidationError):
        nested.append(error.cause)
    if nested:
        # best_match ranks anyOf/oneOf as weak matches, so try its pick first, then the rest.
        preferred = best_match(nested)
        for candidate in [preferred, *(e for e in nested if e is not preferred)]:
            inner = _innermost_alternative(candidate)
            if inner is not None:
                return inner
    return error if error.validator in _ALTERNATIVES else None


def _matches_several(error: jsonschema.ValidationError) -> bool:
    """Whether more than one oneOf alternative accepts the instance (rather than none)."""
    validator = validator_for(error.schema)
    return sum(validator(subschema).is_valid(error.instance) for subschema in error.validator_value) > 1


def _error_result(content: list) -> CallToolResult:
    """An isError result carrying the {error, error_code} envelope (docs/conventions.md)."""
    return CallToolResult(content=content, is_error=True)
