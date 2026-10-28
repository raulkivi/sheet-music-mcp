"""Handler wiring shared by every server: input validation and error results that mcp 2.x
low-level handlers no longer provide themselves (CLAUDE.md, MCP stdio pattern)."""

import asyncio
import json
import logging

from mcp import Client, MCPError
from mcp.server import Server
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS, CallToolResult, TextContent, Tool

from sheet_music_mcp_core.errors import ProcessingError
from sheet_music_mcp_core.ui import UI_MIME, InMemoryAssetSource, UiRegistry, UiResource
from sheet_music_mcp_core.wiring import make_handlers, make_resource_handlers

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
        if arguments["word"] == "typed":
            raise ProcessingError("Part 'X' not found.", "INVALID_PARAMETER", hint="h", choices=["Alto (P2)"])
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
    payload = json.loads(result.content[0].text)
    assert payload["error_code"] == "INVALID_PARAMETER"
    assert payload["error"].startswith("Input validation error:")


def test_tool_exception_becomes_error_result():
    result = _with_client(_server(), lambda c: c.call_tool("echo", {"word": "boom"}))

    # docs/conventions.md: every error uses the {error, error_code} envelope
    assert result.is_error
    assert json.loads(result.content[0].text) == {"error": "exploded", "error_code": "PROCESSING_FAILED"}


def test_escaped_processing_error_keeps_its_code_hint_and_choices():
    result = _with_client(_server(), lambda c: c.call_tool("echo", {"word": "typed"}))

    assert result.is_error
    assert json.loads(result.content[0].text) == {
        "error": "Part 'X' not found.",
        "error_code": "INVALID_PARAMETER",
        "hint": "h",
        "choices": ["Alto (P2)"],
    }


def test_unknown_tool_becomes_error_result():
    result = _with_client(_server(), lambda c: c.call_tool("nope", {}))

    assert result.is_error
    payload = json.loads(result.content[0].text)
    assert payload["error_code"] == "PROCESSING_FAILED"
    assert "nope" in payload["error"]


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
    assert json.loads(text) == {
        "error": "Input validation error: one of these parameters is required: 'part', 'part_id'",
        "error_code": "INVALID_PARAMETER",
    }
    assert "score-partwise" not in text


SCORE = "<score-partwise>" + "secret " * 1000 + "</score-partwise>"
ONE_SCORE = Tool(
    name="one_score",
    description="Takes a score inline or by path",
    input_schema={
        "type": "object",
        "properties": {"musicxml": {"type": "string"}, "musicxml_path": {"type": "string"}},
        "oneOf": [{"required": ["musicxml"]}, {"required": ["musicxml_path"]}],
    },
)
TWO_SCORES = Tool(
    name="two_scores",
    description="Takes two scores, each inline or by path",
    input_schema={
        "type": "object",
        "allOf": [
            {"oneOf": [{"required": ["reference_xml"]}, {"required": ["reference_path"]}]},
            {"oneOf": [{"required": ["target_xml"]}, {"required": ["target_path"]}]},
        ],
    },
)


def _validation_message(tool, arguments):
    async def list_tools():
        return [tool]

    async def call_tool(name, args):
        return [TextContent(type="text", text="ok")]

    on_list_tools, on_call_tool = make_handlers(list_tools, call_tool)
    server = Server("test", on_list_tools=on_list_tools, on_call_tool=on_call_tool)
    result = _with_client(server, lambda c: c.call_tool(tool.name, arguments))
    assert result.is_error
    text = result.content[0].text
    assert "secret" not in text
    payload = json.loads(text)
    assert payload["error_code"] == "INVALID_PARAMETER"
    return payload["error"]


def test_one_of_with_both_parameters_asks_for_only_one():
    message = _validation_message(ONE_SCORE, {"musicxml": SCORE, "musicxml_path": "a.musicxml"})

    assert message == "Input validation error: give only one of these parameters: 'musicxml', 'musicxml_path'"


def test_one_of_with_neither_parameter_names_both():
    message = _validation_message(ONE_SCORE, {})

    assert message == "Input validation error: one of these parameters is required: 'musicxml', 'musicxml_path'"


def test_all_of_reports_the_failing_pair_when_both_given():
    # jsonschema reports a failing allOf member as that member's own error, not as an allOf error.
    message = _validation_message(
        TWO_SCORES, {"reference_xml": SCORE, "target_xml": SCORE, "target_path": "t.musicxml"}
    )

    assert message == "Input validation error: give only one of these parameters: 'target_xml', 'target_path'"


def test_all_of_reports_the_failing_pair_when_missing():
    message = _validation_message(TWO_SCORES, {"target_xml": SCORE})

    assert message == "Input validation error: one of these parameters is required: 'reference_xml', 'reference_path'"


def test_one_of_alongside_an_any_of():
    tool = Tool(
        name="pitch",
        description="Score plus part",
        input_schema={
            "type": "object",
            "oneOf": [{"required": ["musicxml"]}, {"required": ["musicxml_path"]}],
            "anyOf": [{"required": ["part"]}, {"required": ["part_id"]}],
        },
    )

    message = _validation_message(tool, {"musicxml": SCORE, "musicxml_path": "a.musicxml", "part": "S"})

    assert message == "Input validation error: give only one of these parameters: 'musicxml', 'musicxml_path'"


def test_nested_one_of_inside_an_error_context_is_described():
    """An anyOf whose alternatives hold a oneOf: describe the innermost failing oneOf."""
    import jsonschema

    from sheet_music_mcp_core.wiring import _describe

    schema = {
        "type": "object",
        "anyOf": [
            {"oneOf": [{"required": ["musicxml"]}, {"required": ["musicxml_path"]}]},
            {"required": ["session_id"]},
        ],
    }
    [error] = jsonschema.Draft202012Validator(schema).iter_errors({"musicxml": SCORE, "musicxml_path": "a"})
    assert error.validator == "anyOf"  # the raw error is the outer anyOf

    assert _describe(error) == "give only one of these parameters: 'musicxml', 'musicxml_path'"


def test_raw_all_of_errors_are_the_inner_one_of_errors():
    import jsonschema

    from sheet_music_mcp_core.wiring import _describe

    errors = list(jsonschema.Draft202012Validator(TWO_SCORES.input_schema).iter_errors({"reference_xml": SCORE}))

    assert [_describe(e) for e in errors] == [
        "one of these parameters is required: 'target_xml', 'target_path'"
    ]


# --- Resource handlers (MCP Apps UI resources) ------------------------------------------------

HTML = "<!doctype html><title>viewer</title>"
VIEWER = UiResource("ui://test/viewer", "viewer.html", "Score Viewer")
PLAYER = UiResource("ui://test/player", "player.html", "Practice Player")


def _resource_server(registry=None, **kwargs):
    registry = registry or UiRegistry([VIEWER, PLAYER], InMemoryAssetSource({"viewer.html": HTML}))
    on_list_resources, on_read_resource = make_resource_handlers(registry, **kwargs)
    return Server("test", on_list_resources=on_list_resources, on_read_resource=on_read_resource)


def _read_error(server, uri):
    """The MCPError a read raises, caught inside the session (outside it arrives as a TaskGroup error)."""

    async def read(client):
        try:
            await client.read_resource(uri)
        except MCPError as e:
            return e
        raise AssertionError("read_resource did not raise")

    return _with_client(server, read)


def test_lists_only_packaged_ui_resources():
    result = _with_client(_resource_server(), lambda c: c.list_resources())

    assert [(r.uri, r.mime_type) for r in result.resources] == [("ui://test/viewer", UI_MIME)]


def test_reads_a_ui_resource():
    result = _with_client(_resource_server(), lambda c: c.read_resource("ui://test/viewer"))

    [contents] = result.contents
    assert (contents.mime_type, contents.text) == (UI_MIME, HTML)


def test_missing_asset_is_an_internal_error_naming_the_build_step():
    error = _read_error(_resource_server(), "ui://test/player")

    assert error.code == INTERNAL_ERROR
    assert "npm run build" in error.message
    assert error.data["error_code"] == "UI_ASSET_MISSING"
    assert "npm run build" in error.data["hint"]
    assert error.data["uri"] == "ui://test/player"


def test_unknown_resource_is_invalid_params():
    # The 2026-07-28 spec (and the SDK's MCPServer) report an unknown resource as -32602.
    error = _read_error(_resource_server(), "ui://test/nope")

    assert error.code == INVALID_PARAMS
    assert error.data == {
        "error": "Unknown resource: ui://test/nope",
        "error_code": "RESOURCE_NOT_FOUND",
        "uri": "ui://test/nope",
    }


def test_unexpected_registry_failure_keeps_its_message():
    class Broken:
        def list_resources(self):
            return []

        def read(self, uri):
            raise OSError("disk gone")

    error = _read_error(_resource_server(Broken()), "ui://test/viewer")

    # Unwired, the SDK would send only an opaque "Internal server error".
    assert (error.code, error.message) == (INTERNAL_ERROR, "disk gone")
    assert error.data["error_code"] == "PROCESSING_FAILED"


def test_logs_resource_failures_under_the_given_logger(caplog):
    caplog.set_level(logging.ERROR)

    _read_error(_resource_server(logger=logging.getLogger("render_mcp.server")), "ui://test/player")

    [record] = [r for r in caplog.records if "failed" in r.getMessage()]
    assert record.name == "render_mcp.server"
    assert "ui://test/player" in record.getMessage()


def test_logs_resource_failures_under_the_core_logger_by_default(caplog):
    caplog.set_level(logging.ERROR)

    _read_error(_resource_server(), "ui://test/nope")

    [record] = [r for r in caplog.records if "failed" in r.getMessage()]
    assert record.name == "sheet_music_mcp_core.wiring"
