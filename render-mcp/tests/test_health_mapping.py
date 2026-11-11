"""engine.get_health_status() -> the standard health report (sheet_music_mcp_core.health),
and the health_check wiring: structured content, output schema, Setup Doctor link."""

import asyncio
import importlib.metadata
from unittest.mock import patch

import pytest
from mcp import Client
from sheet_music_mcp_core.health import HEALTH_OUTPUT_SCHEMA, health_report

import render_mcp.server as server
from render_mcp.health import DOC, build_health_report, health_checks
from render_mcp.server import app, call_tool_result, list_tools

SETUP_DOCTOR_URI = "ui://render/setup-doctor"


def _status(backend="verovio", verovio=True, cairosvg=True, notes=()):
    """The dict shape engine.get_health_status() returns, with the fields under test."""
    return {
        "server": "render-mcp",
        "status": "ok" if backend is not None else "degraded",
        "backend": backend,
        "musescore_available": backend == "musescore",
        "verovio_available": verovio,
        "cairosvg_available": cairosvg,
        "notes": list(notes),
    }


def _expected_text(status: dict) -> str:
    """The health_check text lines, which must stay byte-identical to the old output."""
    lines = [
        f"render-mcp status: {status['status'].upper()}",
        f"  Backend:   {status['backend'] or 'none'}",
        f"  MuseScore: {'\u2713' if status['musescore_available'] else '\u2717'}",
        f"  Verovio:   {'\u2713' if status['verovio_available'] else '\u2717'}",
        f"  cairosvg:  {'\u2713' if status['cairosvg_available'] else '\u2717'}",
    ]
    if status["notes"]:
        lines.append("")
        lines.append("Warnings:")
        for note in status["notes"]:
            lines.append(f"  - {note}")
    return "\n".join(lines)


def _by_name(checks):
    return {check.name: check for check in checks}


class TestBackendRow:
    @patch("importlib.metadata.version", return_value="9.9.9")
    def test_verovio_reports_the_backend_version(self, _version):
        backend = _by_name(health_checks(_status()))["Rendering backend"]
        assert (backend.name, backend.status, backend.version) == ("Rendering backend", "ok", "9.9.9")
        assert backend.hint is None and backend.fix_snippet is None and backend.doc_url is None

    @patch(
        "importlib.metadata.version",
        side_effect=importlib.metadata.PackageNotFoundError("verovio"),
    )
    def test_missing_verovio_metadata_keeps_the_version_none(self, _version):
        backend = _by_name(health_checks(_status()))["Rendering backend"]
        assert backend.version is None

    def test_musescore_has_no_version(self):
        [backend] = health_checks(_status(backend="musescore", verovio=False))
        assert (backend.name, backend.status, backend.version) == ("Rendering backend", "ok", None)

    def test_no_backend_is_a_fail_row(self):
        [backend] = health_checks(_status(backend=None, verovio=False))
        assert (backend.name, backend.status) == ("Rendering backend", "fail")
        assert backend.hint == "No rendering backend found; render_to_pdf and render_to_image fail."
        assert backend.fix_snippet == "uv add verovio cairosvg"
        assert backend.doc_url == DOC


class TestCairosvgRow:
    def test_row_only_when_verovio_is_available(self):
        assert [c.name for c in health_checks(_status(verovio=False))] == ["Rendering backend"]

    def test_ok_row(self):
        check = _by_name(health_checks(_status()))["cairosvg"]
        assert check.status == "ok"
        assert check.hint is None and check.fix_snippet is None and check.doc_url is None

    def test_musescore_backend_still_gets_the_row(self):
        checks = health_checks(_status(backend="musescore", verovio=True, cairosvg=False))
        assert [c.name for c in checks] == ["Rendering backend", "cairosvg"]

    def test_warn_row(self):
        check = _by_name(health_checks(_status(cairosvg=False)))["cairosvg"]
        assert check.status == "warn"
        assert check.hint == "PNG and PDF output via Verovio will fail; SVG still works."
        assert check.fix_snippet == "sudo apt install libcairo2"
        assert check.doc_url == DOC


class TestOverallStatus:
    """health_report derives it; the mapping never sets it."""

    def test_ready(self):
        assert build_health_report(_status())["status"] == "ready"

    def test_degraded(self):
        assert build_health_report(_status(cairosvg=False))["status"] == "degraded"

    def test_not_ready(self):
        assert build_health_report(_status(backend=None, verovio=False))["status"] == "not_ready"


class TestServerWiring:
    async def test_structured_content_is_the_standard_report(self, monkeypatch):
        status = _status(cairosvg=False)
        monkeypatch.setattr(server, "get_health_status", lambda: status)

        result = await call_tool_result("health_check", {})

        assert result.structured_content == health_report(health_checks(status))
        assert result.structured_content["status"] == "degraded"

    async def test_text_content_stays_byte_identical(self, monkeypatch):
        status = _status(cairosvg=False, notes=["some warning"])
        monkeypatch.setattr(server, "get_health_status", lambda: status)

        result = await call_tool_result("health_check", {})

        assert [block.type for block in result.content] == ["text"]
        assert result.content[0].text == _expected_text(status)

    async def test_tool_declares_the_health_output_schema(self):
        tools = {tool.name: tool for tool in await list_tools()}
        # The Tool model deep-copies the schema, so compare by value.
        assert tools["health_check"].output_schema == HEALTH_OUTPUT_SCHEMA

    async def test_links_the_setup_doctor_when_packaged(self, packaged_ui):
        tools = {tool.name: tool for tool in await list_tools()}
        assert tools["health_check"].meta == {"ui": {"resourceUri": SETUP_DOCTOR_URI}}

    async def test_no_link_without_a_ui_build(self):
        tools = {tool.name: tool for tool in await list_tools()}
        assert tools["health_check"].meta is None

    def test_client_call_validates_against_the_schema(self, monkeypatch):
        status = _status(backend=None, verovio=False)
        monkeypatch.setattr(server, "get_health_status", lambda: status)

        async def _go():
            async with Client(app) as client:
                return await client.call_tool("health_check", {})

        result = asyncio.run(_go())

        assert not result.is_error
        assert result.structured_content["status"] == "not_ready"
