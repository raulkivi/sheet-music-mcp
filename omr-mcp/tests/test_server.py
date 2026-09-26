"""Tests for OMR MCP server module."""

import asyncio
import json
import time
from importlib.metadata import version as package_version
from types import SimpleNamespace

import pytest

from omr_mcp.server import _detect_input_format


class TestDetectInputFormat:
    """Tests for input format detection."""

    def test_explicit_path_hint(self):
        assert _detect_input_format("/some/path/image.png", "path") == "path"

    def test_explicit_base64_hint(self):
        assert _detect_input_format("/some/path/image.png", "base64") == "base64"

    def test_auto_detect_path(self):
        assert _detect_input_format("/home/user/image.png", None) == "path"
        assert _detect_input_format("./relative/path.jpg", None) == "path"
        assert _detect_input_format("C:\\Windows\\path.png", None) == "path"

    def test_auto_detect_base64_data_url(self):
        base64_data = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        assert _detect_input_format(base64_data, None) == "base64"

    def test_auto_detect_long_base64(self):
        # Long string without path separators should be detected as base64
        long_base64 = "A" * 600
        assert _detect_input_format(long_base64, None) == "base64"


class TestServerToolSchemas:
    """Tests for MCP server tool definitions."""

    def test_list_tools_returns_all_tools(self):
        from omr_mcp.server import list_tools

        tools = asyncio.run(list_tools())
        tool_names = [t.name for t in tools]

        assert "recognize_sheet" in tool_names
        assert "recognize_sheet_to_file" in tool_names
        assert "recognize_sheets" in tool_names
        assert "list_capabilities" in tool_names
        assert "list_supported_formats" in tool_names  # kept as deprecated alias

    def test_recognize_sheet_schema(self):
        from omr_mcp.server import list_tools

        tools = asyncio.run(list_tools())
        recognize_sheet = next(t for t in tools if t.name == "recognize_sheet")

        schema = recognize_sheet.input_schema
        assert "image" in schema["properties"]
        assert "format" in schema["properties"]
        assert "engine" in schema["properties"]
        assert schema["properties"]["engine"]["enum"] == ["oemer", "audiveris"]
        assert schema["required"] == ["image"]

    def test_recognize_sheet_to_file_schema(self):
        from omr_mcp.server import list_tools

        tools = asyncio.run(list_tools())
        tool = next(t for t in tools if t.name == "recognize_sheet_to_file")

        schema = tool.input_schema
        assert "input_path" in schema["properties"]
        assert "output_path" in schema["properties"]
        assert "engine" in schema["properties"]
        assert schema["required"] == ["input_path"]

    def test_recognize_sheets_schema(self):
        from omr_mcp.server import list_tools

        tools = asyncio.run(list_tools())
        tool = next(t for t in tools if t.name == "recognize_sheets")

        schema = tool.input_schema
        assert "images" in schema["properties"]
        assert schema["properties"]["images"]["type"] == "array"
        assert "engine" in schema["properties"]
        assert schema["required"] == ["images"]

    def test_list_capabilities_tool(self):
        from omr_mcp.server import call_tool

        result = asyncio.run(
            call_tool("list_capabilities", {})
        )
        assert len(result) == 1

        data = json.loads(result[0].text)
        assert data["server"] == "omr-mcp"
        assert data["version"] == package_version("omr-mcp")
        assert "input_formats" in data
        assert "output_formats" in data
        assert "tools" in data
        assert "backend" in data
        assert "png" in data["input_formats"]
        assert "musicxml" in data["output_formats"]
        assert "list_capabilities" in data["tools"]
        assert "engines" in data
        assert data["engines"]["oemer"]["status"] == "ok"
        assert data["engines"]["audiveris"]["status"] in ("ok", "not_installed")

    def test_list_supported_formats_tool(self):
        """Deprecated alias — should return the same payload as list_capabilities."""
        from omr_mcp.server import call_tool

        result = asyncio.run(
            call_tool("list_supported_formats", {})
        )
        assert len(result) == 1

        data = json.loads(result[0].text)
        assert "input_formats" in data
        assert "output_formats" in data
        assert "png" in data["input_formats"]
        assert "musicxml" in data["output_formats"]

    def test_recognize_sheets_empty_list_returns_error(self):
        from omr_mcp.server import call_tool

        result = asyncio.run(
            call_tool("recognize_sheets", {"images": []})
        )
        data = json.loads(result[0].text)
        assert data.get("error_code") == "INVALID_PARAMETER"
        assert "No images provided" in data["error"]

    def test_recognize_sheets_invalid_images_param_returns_error(self):
        from omr_mcp.server import call_tool

        result = asyncio.run(
            call_tool("recognize_sheets", {"images": "not-a-list"})
        )
        data = json.loads(result[0].text)
        assert "error" in data


class TestEngineRouting:
    """Tests that call_tool()'s optional engine= argument reaches the underlying
    omr_engine calls, and defaults to 'oemer' when omitted."""

    def test_recognize_sheet_defaults_to_oemer(self, tmp_path, monkeypatch):
        import omr_mcp.server as srv

        captured = {}
        def _fake_recognize_image(path, engine="oemer"):
            captured["engine"] = engine
            return {"musicxml": "<score-partwise/>", "metadata": {"engine": engine}}
        monkeypatch.setattr(srv, "recognize_image", _fake_recognize_image)

        asyncio.run(srv.call_tool("recognize_sheet", {"image": str(tmp_path / "x.png"), "format": "path"}))
        assert captured["engine"] == "oemer"

    def test_recognize_sheet_forwards_explicit_engine(self, tmp_path, monkeypatch):
        import omr_mcp.server as srv

        captured = {}
        def _fake_recognize_image(path, engine="oemer"):
            captured["engine"] = engine
            return {"musicxml": "<score-partwise/>", "metadata": {"engine": engine}}
        monkeypatch.setattr(srv, "recognize_image", _fake_recognize_image)

        asyncio.run(srv.call_tool(
            "recognize_sheet", {"image": str(tmp_path / "x.png"), "format": "path", "engine": "audiveris"}
        ))
        assert captured["engine"] == "audiveris"

    def test_recognize_sheet_to_file_forwards_engine(self, tmp_path, monkeypatch):
        import omr_mcp.server as srv

        captured = {}
        def _fake_recognize_image_to_file(input_path, output_path, engine="oemer"):
            captured["engine"] = engine
            return {"output_path": "out.musicxml", "metadata": {"engine": engine}}
        monkeypatch.setattr(srv, "recognize_image_to_file", _fake_recognize_image_to_file)

        asyncio.run(srv.call_tool(
            "recognize_sheet_to_file", {"input_path": str(tmp_path / "x.png"), "engine": "audiveris"}
        ))
        assert captured["engine"] == "audiveris"

    def test_recognize_sheets_forwards_engine(self, tmp_path, monkeypatch):
        import omr_mcp.server as srv

        captured = {}
        def _fake_recognize_images(paths, engine="oemer"):
            captured["engine"] = engine
            return {"musicxml": "<score-partwise/>", "metadata": {"engine": engine, "page_count": 1}}
        monkeypatch.setattr(srv, "recognize_images", _fake_recognize_images)

        asyncio.run(srv.call_tool(
            "recognize_sheets", {"images": [str(tmp_path / "x.png")], "engine": "audiveris"}
        ))
        assert captured["engine"] == "audiveris"


class _FakeSession:
    """Minimal stand-in for ServerSession, recording sent progress notifications."""

    def __init__(self):
        self.notifications = []

    async def send_progress_notification(self, progress_token, progress, total=None, message=None, related_request_id=None):
        self.notifications.append((progress_token, progress, message))


def _request_context(*, progress_token=None):
    """Fake of the ServerRequestContext mcp 2.x passes to a tool handler: `meta` is a
    dict with the client's progress token under `progress_token`."""
    session = _FakeSession()
    meta = {"progress_token": progress_token} if progress_token else None
    ctx = SimpleNamespace(request_id="test-request", meta=meta, session=session)
    return ctx, session


class TestRunWithProgress:
    """Tests for the progress-notification wrapper around long-running engine calls."""

    def test_no_request_context_runs_and_returns_result(self):
        # Matches how unit tests call call_tool() directly, with no live MCP request.
        from omr_mcp.server import _run_with_progress

        result = asyncio.run(_run_with_progress(lambda: 42, message_prefix="test"))
        assert result == 42

    def test_no_progress_token_runs_without_notifications(self):
        from omr_mcp.server import _run_with_progress

        ctx, session = _request_context(progress_token=None)
        result = asyncio.run(_run_with_progress(lambda: 42, ctx=ctx, message_prefix="test"))
        assert result == 42
        assert session.notifications == []

    def test_progress_token_sends_heartbeat_notifications(self):
        from omr_mcp.server import _run_with_progress

        def _slow():
            time.sleep(0.2)
            return "done"

        ctx, session = _request_context(progress_token="tok-1")
        result = asyncio.run(
            _run_with_progress(_slow, ctx=ctx, message_prefix="Working", interval_seconds=0.05)
        )
        assert result == "done"
        assert len(session.notifications) >= 2
        assert all(token == "tok-1" for token, _progress, _message in session.notifications)
        assert all("Working" in message for _token, _progress, message in session.notifications)

    def test_call_tool_forwards_the_request_context(self, monkeypatch, tmp_path):
        import omr_mcp.server as srv

        captured = {}

        async def _fake_run_with_progress(fn, *args, ctx=None, message_prefix, **kwargs):
            captured["ctx"] = ctx
            return {"musicxml": "<score-partwise/>", "metadata": {}}

        monkeypatch.setattr(srv, "_run_with_progress", _fake_run_with_progress)
        ctx, _session = _request_context(progress_token="tok-1")

        asyncio.run(srv.call_tool("recognize_sheet", {"image": str(tmp_path / "x.png")}, ctx))
        assert captured["ctx"] is ctx

    def test_exception_from_fn_propagates(self):
        from omr_mcp.server import _run_with_progress

        def _boom():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            asyncio.run(_run_with_progress(_boom, message_prefix="test"))
