"""The health_check standard report: the raw engine dict mapped to HealthCheck rows
(sheet_music_mcp_core.health), plus the Setup Doctor wiring in server.py."""

import json

import jsonschema
from sheet_music_mcp_core.health import (
    HEALTH_OUTPUT_SCHEMA,
    HealthCheck,
    health_report,
)

import comparer_mcp.server as server
from comparer_mcp.health import DOC, build_health_report, health_checks

DOC_URL = "https://github.com/raulkivi/sheet-music-mcp/blob/main/comparer-mcp/TROUBLESHOOTING.md"

SETUP_DOCTOR_URI = "ui://comparer/setup-doctor"


def _raw(checks: dict) -> dict:
    return {"status": "ok", "checks": checks, "summary": "All systems operational."}


MUSIC21_OK = {"ok": True, "version": "10.4", "error": None}
MUSIC21_FAIL = {"ok": False, "version": None, "error": "No module named 'music21'"}
SELF_COMPARE_OK = {"ok": True}
SELF_COMPARE_FAIL = {"ok": False, "error": "boom"}


class TestHealthChecks:
    def test_music21_ok_carries_the_version(self):
        checks = health_checks(_raw({"music21": MUSIC21_OK, "self_compare": SELF_COMPARE_OK}))

        assert checks[0] == HealthCheck("music21", "ok", version="10.4")

    def test_music21_ok_with_no_version_stays_none(self):
        checks = health_checks(_raw({"music21": {"ok": True, "version": None}}))

        assert checks == [HealthCheck("music21", "ok")]

    def test_music21_fail_gets_hint_fix_and_docs(self):
        checks = health_checks(_raw({"music21": MUSIC21_FAIL}))

        assert checks == [
            HealthCheck(
                "music21",
                "fail",
                hint="music21 is not installed: No module named 'music21'",
                fix_snippet="uv sync",
                doc_url=DOC_URL,
            )
        ]

    def test_self_compare_ok(self):
        checks = health_checks(_raw({"music21": MUSIC21_OK, "self_compare": SELF_COMPARE_OK}))

        assert checks[1] == HealthCheck("Self-comparison", "ok")

    def test_self_compare_fail_gets_hint_and_docs_but_no_fix(self):
        checks = health_checks(
            _raw({"music21": MUSIC21_OK, "self_compare": SELF_COMPARE_FAIL})
        )

        assert checks[1] == HealthCheck(
            "Self-comparison",
            "fail",
            hint="Comparing a score with itself failed: boom",
            doc_url=DOC_URL,
        )

    def test_self_compare_absent_drops_the_row(self):
        checks = health_checks(_raw({"music21": MUSIC21_OK}))

        assert checks == [HealthCheck("music21", "ok", version="10.4")]

    def test_rows_keep_the_specified_order(self):
        checks = health_checks(_raw({"music21": MUSIC21_OK, "self_compare": SELF_COMPARE_OK}))

        assert [check.name for check in checks] == ["music21", "Self-comparison"]


class TestBuildHealthReport:
    def test_is_the_core_report_over_the_mapped_checks(self):
        raw = _raw({"music21": MUSIC21_OK, "self_compare": SELF_COMPARE_OK})

        assert build_health_report(raw) == health_report(health_checks(raw))

    def test_all_ok_is_ready(self):
        raw = _raw({"music21": MUSIC21_OK, "self_compare": SELF_COMPARE_OK})

        assert build_health_report(raw)["status"] == "ready"

    def test_any_fail_is_not_ready(self):
        raw = _raw({"music21": MUSIC21_FAIL, "self_compare": SELF_COMPARE_OK})

        assert build_health_report(raw)["status"] == "not_ready"

    def test_report_validates_against_the_schema(self):
        for raw in (
            _raw({"music21": MUSIC21_OK, "self_compare": SELF_COMPARE_OK}),
            _raw({"music21": MUSIC21_FAIL}),
            _raw({"music21": MUSIC21_OK, "self_compare": SELF_COMPARE_FAIL}),
        ):
            jsonschema.validate(build_health_report(raw), HEALTH_OUTPUT_SCHEMA)


class TestServerWiring:
    async def test_health_check_tool_declares_the_report_schema(self):
        tools = {tool.name: tool for tool in await server.list_tools()}

        assert tools["health_check"].output_schema == HEALTH_OUTPUT_SCHEMA

    def test_setup_doctor_resource_points_at_the_core_asset(self):
        doctor = server.SETUP_DOCTOR

        assert doctor.uri == SETUP_DOCTOR_URI
        assert doctor.asset == "setup-doctor.html"

    async def test_health_check_links_setup_doctor_when_packaged(self, packaged_ui):
        tools = {tool.name: tool for tool in await server.list_tools()}

        assert tools["health_check"].meta == {"ui": {"resourceUri": SETUP_DOCTOR_URI}}

    async def test_no_setup_doctor_link_without_a_ui_build(self):
        tools = {tool.name: tool for tool in await server.list_tools()}

        assert tools["health_check"].meta is None

    def test_default_registry_registers_both_apps(self):
        # A source checkout has no built HTML, so meta_for resolves to None rather than raising
        # "not registered".
        registry = server.DEFAULT_UI_REGISTRY

        assert registry.meta_for(server.DIFF_VIEWER) is None
        assert registry.meta_for(server.SETUP_DOCTOR) is None

    async def test_call_tool_result_keeps_the_text_and_adds_the_report(self, monkeypatch):
        raw = _raw({"music21": MUSIC21_OK, "self_compare": SELF_COMPARE_OK})
        monkeypatch.setattr(server, "health_check", lambda: raw)

        result = await server.call_tool_result("health_check", {})

        assert not result.is_error
        assert result.content[0].text == json.dumps(raw, indent=2)
        assert result.structured_content == build_health_report(raw)
        jsonschema.validate(result.structured_content, HEALTH_OUTPUT_SCHEMA)

    async def test_text_content_matches_the_real_engine(self):
        raw = server.health_check()
        result = await server.call_tool_result("health_check", {})

        assert result.content[0].text == json.dumps(raw, indent=2)
        assert result.structured_content == build_health_report(raw)
