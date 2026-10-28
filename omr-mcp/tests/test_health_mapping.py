"""The standard health report for omr-mcp: engine raw dict -> HealthCheck rows (omr_mcp.health)
and the Setup Doctor wiring in server.py (structuredContent, output schema, tool link)."""

import asyncio
import json

import jsonschema
import pytest
from sheet_music_mcp_core.health import HEALTH_OUTPUT_SCHEMA

import omr_mcp.server as server
from omr_mcp.health import DOC, build_health_report, health_checks


def raw(**overrides):
    """A full engine health_check() dict; each check can be swapped out."""
    checks = {
        "oemer": {"status": "ok", "version": "0.2.1"},
        "model_cache": {"status": "ok", "path": "/models", "note": "Model cache found."},
        "audiveris": {
            "status": "not_installed",
            "path": None,
            "note": "Optional alternate engine. Not required.",
        },
    }
    checks.update(overrides)
    return {"status": "ok", "checks": checks}


def named(checks):
    return {c.name: c.to_dict() for c in checks}


class TestOemerRow:
    def test_ok_with_version(self):
        [oemer] = [c for c in health_checks(raw()) if c.name == "oemer"]

        assert oemer.to_dict() == {"name": "oemer", "status": "ok", "version": "0.2.1"}

    def test_ok_with_unknown_version_has_no_version(self):
        [oemer] = [c for c in health_checks(raw(oemer={"status": "ok", "version": "unknown"}))
                   if c.name == "oemer"]

        assert "version" not in oemer.to_dict()

    def test_ok_without_version_has_no_version(self):
        [oemer] = [c for c in health_checks(raw(oemer={"status": "ok"})) if c.name == "oemer"]

        assert "version" not in oemer.to_dict()

    def test_missing_is_a_fail_with_fix_snippet(self):
        [oemer] = [c for c in health_checks(raw(oemer={"status": "missing",
                                                       "error": "No module named 'oemer'"}))
                   if c.name == "oemer"]

        assert oemer.to_dict() == {
            "name": "oemer",
            "status": "fail",
            "hint": "oemer is not installed: No module named 'oemer'",
            "fix_snippet": "uv sync",
            "doc_url": DOC,
        }


class TestModelCacheRow:
    def test_ok(self):
        [cache] = [c for c in health_checks(raw()) if c.name == "oemer model cache"]

        assert cache.to_dict() == {"name": "oemer model cache", "status": "ok"}

    def test_missing_is_a_warn_without_fix_snippet(self):
        [cache] = [c for c in health_checks(raw(model_cache={"status": "missing",
                                                             "note": "Model cache not found."}))
                   if c.name == "oemer model cache"]

        assert cache.to_dict() == {
            "name": "oemer model cache",
            "status": "warn",
            "hint": "Model cache not found.",
            "doc_url": DOC,
        }


class TestAudiverisRow:
    def test_ok_with_version(self):
        [audiveris] = [c for c in health_checks(raw(audiveris={"status": "ok",
                                                               "version": "5.11.0"}))
                       if c.name == "Audiveris (optional)"]

        assert audiveris.to_dict() == {
            "name": "Audiveris (optional)", "status": "ok", "version": "5.11.0"
        }

    def test_ok_with_unknown_version_has_no_version(self):
        [audiveris] = [c for c in health_checks(raw(audiveris={"status": "ok",
                                                               "version": "unknown"}))
                       if c.name == "Audiveris (optional)"]

        assert "version" not in audiveris.to_dict()

    def test_ok_without_version_has_no_version(self):
        [audiveris] = [c for c in health_checks(raw(audiveris={"status": "ok"}))
                       if c.name == "Audiveris (optional)"]

        assert "version" not in audiveris.to_dict()

    def test_not_installed_is_ok_with_the_note(self):
        [audiveris] = [c for c in health_checks(raw()) if c.name == "Audiveris (optional)"]

        assert audiveris.to_dict() == {
            "name": "Audiveris (optional)",
            "status": "ok",
            "hint": "Optional alternate engine. Not required.",
        }

    def test_any_other_status_is_a_warn(self):
        [audiveris] = [c for c in health_checks(raw(audiveris={"status": "broken",
                                                               "note": "Corrupt install.",
                                                               "error": "boom"}))
                       if c.name == "Audiveris (optional)"]

        assert audiveris.to_dict() == {
            "name": "Audiveris (optional)",
            "status": "warn",
            "hint": "Corrupt install.",
            "doc_url": DOC,
        }

    def test_any_other_status_falls_back_to_the_error(self):
        [audiveris] = [c for c in health_checks(raw(audiveris={"status": "broken",
                                                               "error": "boom"}))
                       if c.name == "Audiveris (optional)"]

        assert audiveris.to_dict()["hint"] == "boom"


class TestReport:
    def test_rows_come_back_in_the_specified_order(self):
        assert [c.name for c in health_checks(raw())] == [
            "oemer", "oemer model cache", "Audiveris (optional)"
        ]

    def test_all_ok_is_ready(self):
        report = build_health_report(raw(audiveris={"status": "ok", "version": "5.11.0"}))

        assert report["status"] == "ready"
        jsonschema.validate(report, HEALTH_OUTPUT_SCHEMA)

    def test_missing_cache_is_degraded(self):
        report = build_health_report(raw(model_cache={"status": "missing", "note": "x"}))

        assert report["status"] == "degraded"

    def test_missing_oemer_is_not_ready(self):
        report = build_health_report(raw(oemer={"status": "missing", "error": "x"}))

        assert report["status"] == "not_ready"

    def test_checks_are_serialised_without_unset_fields(self):
        report = build_health_report(raw())

        assert [c for c in report["checks"]] == [
            {"name": "oemer", "status": "ok", "version": "0.2.1"},
            {"name": "oemer model cache", "status": "ok"},
            {"name": "Audiveris (optional)", "status": "ok",
             "hint": "Optional alternate engine. Not required."},
        ]


class TestServerWiring:
    def _tools(self):
        return {tool.name: tool for tool in asyncio.run(server.list_tools())}

    def test_health_check_declares_the_standard_output_schema(self):
        assert self._tools()["health_check"].output_schema == HEALTH_OUTPUT_SCHEMA

    def test_health_check_links_the_setup_doctor_when_packaged(self, packaged_ui):
        assert self._tools()["health_check"].meta == {
            "ui": {"resourceUri": "ui://omr/setup-doctor"}
        }

    def test_health_check_has_no_link_without_a_ui_build(self):
        assert self._tools()["health_check"].meta is None

    def test_the_setup_doctor_resource_is_listed_when_packaged(self, packaged_ui):
        async def go():
            from mcp import Client

            async with Client(server.app) as client:
                return await client.list_resources()

        listed = asyncio.run(go())

        assert [r.uri for r in listed.resources] == [
            "ui://omr/recognition-review", "ui://omr/setup-doctor"
        ]

    def test_result_has_the_old_text_and_the_standard_structured_content(self, monkeypatch):
        engine_raw = raw(audiveris={"status": "ok", "path": "/bin/Audiveris",
                                    "version": "5.11.0", "note": "Ready to use."})
        monkeypatch.setattr(server, "_engine_health_check", lambda: engine_raw)

        result = asyncio.run(server.call_tool_result("health_check", {}))

        expected_text = (
            "omr-mcp health status: OK\n"
            "\n"
            "  \u2713 oemer: ok (v0.2.1)\n"
            "  \u2713 model_cache: ok\n"
            "      path: /models\n"
            "      Model cache found.\n"
            "  \u2713 audiveris: ok (v5.11.0)\n"
            "      path: /bin/Audiveris\n"
            "      Ready to use."
        )
        assert not result.is_error
        assert len(result.content) == 1
        assert result.content[0].text == expected_text
        assert result.structured_content == build_health_report(engine_raw)
        jsonschema.validate(result.structured_content, HEALTH_OUTPUT_SCHEMA)

    def test_degraded_engine_status_keeps_its_text(self, monkeypatch):
        engine_raw = {
            "status": "degraded",
            "checks": {
                "oemer": {"status": "missing", "error": "No module named 'oemer'"},
                "model_cache": {"status": "missing", "path": None, "note": "Model cache not found."},
                "audiveris": {"status": "not_installed", "path": None, "note": "Optional alternate engine. Not required."},
            },
        }
        monkeypatch.setattr(server, "_engine_health_check", lambda: engine_raw)

        result = asyncio.run(server.call_tool_result("health_check", {}))

        expected_text = (
            "omr-mcp health status: DEGRADED\n"
            "\n"
            "  \u2717 oemer: missing\n"
            "      error: No module named 'oemer'\n"
            "  \u2717 model_cache: missing\n"
            "      Model cache not found.\n"
            "  \u25cb audiveris: not_installed\n"
            "      Optional alternate engine. Not required."
        )
        assert result.content[0].text == expected_text
        assert result.structured_content["status"] == "not_ready"
