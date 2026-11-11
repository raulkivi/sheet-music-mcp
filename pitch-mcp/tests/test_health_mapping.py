"""The standard health report behind ``health_check``: mapping the engine's raw dict to
Setup Doctor checks (pitch-mcp/src/pitch_mcp/health.py, MCP-free) and the server wiring
(structuredContent, output_schema, the link to the Setup Doctor app)."""

import json

import jsonschema
import pytest
from sheet_music_mcp_core.health import (
    HEALTH_OUTPUT_SCHEMA,
    HealthCheck,
    health_report,
    setup_doctor_resource,
)

import pitch_mcp.server as server
from pitch_mcp.health import build_health_report, health_checks
from pitch_mcp.server import SETUP_DOCTOR, call_tool_result, list_tools

DOC = "https://github.com/raulkivi/sheet-music-mcp/blob/main/pitch-mcp/TROUBLESHOOTING.md"
LIBROSA = "librosa (offline analysis)"
PORTAUDIO = "Server microphone (PortAudio)"
MIC = "Microphone"


def raw(
    *,
    librosa=True,
    librosa_version="0.11.0",
    sounddevice=True,
    sounddevice_version="0.5.1",
    portaudio=True,
    mic=True,
):
    """A raw ``engine.health_check()`` dict with every knob set."""
    return {
        "status": "ok",
        "summary": "All systems operational.",
        "offline_analysis": {
            "available": librosa,
            "backend": "librosa/pYIN",
            "librosa_version": librosa_version,
        },
        "realtime_monitoring": {
            "available": sounddevice and portaudio,
            "sounddevice_available": sounddevice,
            "sounddevice_version": sounddevice_version,
            "portaudio_available": portaudio,
            "microphone_detected": mic,
        },
    }


def by_name(checks, name):
    return next(c for c in checks if c.name == name)


class TestChecks:
    def test_all_ok(self):
        checks = health_checks(raw())

        assert checks == [
            HealthCheck(LIBROSA, "ok", version="0.11.0"),
            HealthCheck(PORTAUDIO, "ok", version="0.5.1"),
            HealthCheck(MIC, "ok"),
        ]

    def test_librosa_missing(self):
        check = by_name(health_checks(raw(librosa=False, librosa_version="unavailable")), LIBROSA)

        assert check == HealthCheck(
            LIBROSA,
            "fail",
            hint="librosa is not installed; analyze_recording fails.",
            fix_snippet="uv sync",
            doc_url=DOC,
        )

    def test_sounddevice_missing(self):
        check = by_name(
            health_checks(raw(sounddevice=False, sounddevice_version="unavailable")), PORTAUDIO
        )

        assert check == HealthCheck(
            PORTAUDIO,
            "warn",
            hint=(
                "sounddevice is not installed; start_monitoring with the server microphone "
                "fails. The Practice Coach can still use the browser microphone."
            ),
            fix_snippet="uv sync",
            doc_url=DOC,
        )

    def test_portaudio_missing(self):
        check = by_name(health_checks(raw(portaudio=False)), PORTAUDIO)

        assert check == HealthCheck(
            PORTAUDIO,
            "warn",
            hint=(
                "libportaudio2 is missing; start_monitoring with the server microphone fails. "
                "The Practice Coach can still use the browser microphone."
            ),
            fix_snippet="sudo apt install libportaudio2",
            doc_url=DOC,
        )

    def test_microphone_absent(self):
        check = by_name(health_checks(raw(mic=False)), MIC)

        assert check == HealthCheck(
            MIC,
            "warn",
            hint="No input device found on the server; use the browser microphone instead.",
            doc_url=DOC,
        )

    def test_microphone_row_only_when_realtime_works(self):
        for kwargs in (
            {"sounddevice": False, "sounddevice_version": "unavailable"},
            {"portaudio": False},
        ):
            names = [c.name for c in health_checks(raw(**kwargs))]

            assert names == [LIBROSA, PORTAUDIO]

    @pytest.mark.parametrize("librosa_version", ("unavailable", "unknown"))
    @pytest.mark.parametrize("sounddevice_version", ("unavailable", "unknown"))
    def test_sentinel_versions_are_unset(self, librosa_version, sounddevice_version):
        # An "available" backend whose version reads as a sentinel: the row stays ok,
        # the version is left to the Setup Doctor rather than shown as a literal.
        checks = health_checks(
            raw(librosa_version=librosa_version, sounddevice_version=sounddevice_version)
        )

        assert by_name(checks, LIBROSA).version is None
        assert by_name(checks, PORTAUDIO).version is None


class TestReport:
    def test_builds_the_standard_report(self):
        data = raw()

        assert build_health_report(data) == health_report(health_checks(data))

    @pytest.mark.parametrize(
        "kwargs, status",
        [
            ({}, "ready"),
            ({"librosa": False, "librosa_version": "unavailable"}, "not_ready"),
            ({"portaudio": False}, "degraded"),
            ({"mic": False}, "degraded"),
        ],
    )
    def test_overall_status_is_derived(self, kwargs, status):
        report = build_health_report(raw(**kwargs))

        assert report["status"] == status
        jsonschema.validate(report, HEALTH_OUTPUT_SCHEMA)


class TestServerWiring:
    async def test_text_is_unchanged_and_structured_is_the_report(self, monkeypatch):
        data = raw(portaudio=False)
        monkeypatch.setattr(server, "health_check", lambda: data)

        result = await call_tool_result("health_check", {})

        assert not result.is_error
        assert result.content[0].type == "text"
        assert result.content[0].text == json.dumps(data, indent=2)
        assert result.structured_content == build_health_report(data)

    async def test_output_schema_is_the_standard_one(self):
        tools = {t.name: t for t in await list_tools()}

        assert tools["health_check"].output_schema == HEALTH_OUTPUT_SCHEMA

    async def test_links_the_setup_doctor_when_packaged(self, packaged_ui):
        tools = {t.name: t for t in await list_tools()}

        assert tools["health_check"].meta == {"ui": {"resourceUri": SETUP_DOCTOR.uri}}

    async def test_no_link_without_a_ui_build(self):
        tools = {t.name: t for t in await list_tools()}

        assert tools["health_check"].meta is None


def test_setup_doctor_is_the_standard_app():
    assert SETUP_DOCTOR == setup_doctor_resource("pitch")
    assert SETUP_DOCTOR.asset == "setup-doctor.html"
