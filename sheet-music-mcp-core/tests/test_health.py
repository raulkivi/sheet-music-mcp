"""The standard health_check report and the Setup Doctor app (mcp-apps-ux-proposal.md §5.7)."""

import asyncio
import json

import jsonschema
import pytest
from jsonschema.validators import validator_for
from mcp import Client
from mcp.server import Server
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

from sheet_music_mcp_core.health import (
    HEALTH_OUTPUT_SCHEMA,
    HealthCheck,
    health_report,
    setup_doctor_resource,
)

SOUNDFONT = HealthCheck(
    "Soundfont",
    "fail",
    hint="SYNTH_SOUNDFONT_PATH is not set.",
    fix_snippet='"env": {"SYNTH_SOUNDFONT_PATH": "/path/to/TimGM6mb.sf2"}',
    doc_url="https://github.com/raulkivi/sheet-music-mcp/blob/main/synth-mcp/TROUBLESHOOTING.md",
)
MUSIC21 = HealthCheck("music21", "ok", version="9.1.0")
PORTAUDIO = HealthCheck("Server microphone", "warn", hint="libportaudio2 is missing.")


class TestHealthCheck:
    def test_is_immutable(self):
        with pytest.raises(AttributeError):
            MUSIC21.status = "fail"

    @pytest.mark.parametrize("status", ["ready", "error", "OK", "missing", None])
    def test_status_must_be_ok_warn_or_fail(self, status):
        with pytest.raises(ValueError, match="status"):
            HealthCheck("music21", status)

    @pytest.mark.parametrize("name", ["", "   ", None])
    def test_name_is_required(self, name):
        with pytest.raises(ValueError, match="name"):
            HealthCheck(name, "ok")

    def test_to_dict_omits_unset_fields(self):
        assert MUSIC21.to_dict() == {"name": "music21", "status": "ok", "version": "9.1.0"}

    def test_to_dict_keeps_every_set_field(self):
        assert SOUNDFONT.to_dict() == {
            "name": "Soundfont",
            "status": "fail",
            "hint": "SYNTH_SOUNDFONT_PATH is not set.",
            "fix_snippet": '"env": {"SYNTH_SOUNDFONT_PATH": "/path/to/TimGM6mb.sf2"}',
            "doc_url": "https://github.com/raulkivi/sheet-music-mcp/blob/main/synth-mcp/TROUBLESHOOTING.md",
        }


class TestHealthReport:
    def test_all_ok_is_ready(self):
        assert health_report([MUSIC21, HealthCheck("FluidSynth", "ok")])["status"] == "ready"

    def test_a_warning_is_degraded(self):
        assert health_report([MUSIC21, PORTAUDIO])["status"] == "degraded"

    def test_a_failure_is_not_ready_even_with_warnings(self):
        assert health_report([PORTAUDIO, SOUNDFONT, MUSIC21])["status"] == "not_ready"

    def test_no_checks_is_ready(self):
        assert health_report([]) == {"status": "ready", "checks": []}

    def test_checks_keep_their_order_and_omit_unset_fields(self):
        report = health_report([SOUNDFONT, MUSIC21])

        assert report["checks"] == [SOUNDFONT.to_dict(), MUSIC21.to_dict()]

    def test_takes_any_iterable(self):
        report = health_report(check for check in (MUSIC21, PORTAUDIO))

        assert [c["name"] for c in report["checks"]] == ["music21", "Server microphone"]

    def test_duplicate_names_are_rejected(self):
        # The Setup Doctor keys its rows by name.
        with pytest.raises(ValueError, match="music21"):
            health_report([MUSIC21, HealthCheck("music21", "fail")])

    def test_only_health_checks_are_accepted(self):
        with pytest.raises(TypeError):
            health_report([{"name": "music21", "status": "ok"}])


class TestOutputSchema:
    def test_is_a_valid_json_schema(self):
        validator_for(HEALTH_OUTPUT_SCHEMA).check_schema(HEALTH_OUTPUT_SCHEMA)

    @pytest.mark.parametrize(
        "checks",
        [[], [MUSIC21], [SOUNDFONT, MUSIC21, PORTAUDIO]],
    )
    def test_every_report_matches_it(self, checks):
        jsonschema.validate(health_report(checks), HEALTH_OUTPUT_SCHEMA)

    @pytest.mark.parametrize(
        "report",
        [
            {"status": "ok", "checks": []},
            {"status": "ready"},
            {"status": "ready", "checks": [{"status": "ok"}]},
            {"status": "ready", "checks": [{"name": "x", "status": "missing"}]},
            {"status": "ready", "checks": [{"name": "x", "status": "ok", "path": "/x"}]},
            {"status": "ready", "checks": [{"name": "x", "status": "ok", "version": None}]},
        ],
    )
    def test_rejects_other_shapes(self, report):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(report, HEALTH_OUTPUT_SCHEMA)


def test_the_mcp_client_accepts_a_report_under_the_schema():
    # The client validates structuredContent against output_schema, so the schema must suit the SDK.
    report = health_report([SOUNDFONT, MUSIC21, PORTAUDIO])
    tool = Tool(name="health_check", input_schema={"type": "object"}, output_schema=HEALTH_OUTPUT_SCHEMA)

    async def on_list_tools(ctx, params):
        return ListToolsResult(tools=[tool])

    async def on_call_tool(ctx, params):
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(report))], structured_content=report)

    async def _go():
        async with Client(Server("test", on_list_tools=on_list_tools, on_call_tool=on_call_tool)) as client:
            await client.list_tools()
            return await client.call_tool("health_check", {})

    result = asyncio.run(_go())

    assert not result.is_error
    assert result.structured_content == report


class TestSetupDoctorResource:
    def test_points_at_the_shared_page(self):
        resource = setup_doctor_resource("synth")

        assert (resource.uri, resource.asset, resource.name) == (
            "ui://synth/setup-doctor",
            "setup-doctor.html",
            "Setup Doctor",
        )
        assert resource.description

    def test_asks_only_for_clipboard_write(self):
        # [Copy] next to each fix snippet (proposal §5.7); nothing else.
        assert setup_doctor_resource("pitch").resource_meta() == {"ui": {"permissions": {"clipboardWrite": {}}}}

    def test_is_the_same_resource_each_call(self):
        # UiRegistry.meta_for compares by value, so a server may call it again when linking tools.
        assert setup_doctor_resource("omr") == setup_doctor_resource("omr")

    @pytest.mark.parametrize("server", ["", "Synth", "synth-mcp/", "a/b", "ui://synth", "synth mcp", "-synth"])
    def test_server_must_be_a_short_lowercase_name(self, server):
        with pytest.raises(ValueError, match="server"):
            setup_doctor_resource(server)

    @pytest.mark.parametrize("server", ["render", "synth", "abc", "omr", "pitch", "comparer", "musicxml-abc"])
    def test_accepts_the_servers_uri_names(self, server):
        assert setup_doctor_resource(server).uri == f"ui://{server}/setup-doctor"
