"""synth_mcp.health: the probes, the text report (byte-identical to the old inline branch),
the standard Setup Doctor mapping, and the health_check wiring in server.py."""

import builtins
import importlib.metadata
import sys
import types

import jsonschema
import pytest

import synth_mcp.server as server
from sheet_music_mcp_core.health import HEALTH_OUTPUT_SCHEMA, HealthCheck, health_report
from synth_mcp.health import DOC, Probe, build_health_report, health_checks, health_text, probe
from synth_mcp.server import SETUP_DOCTOR, call_tool_result, list_tools

DOCTOR_URI = "ui://synth/setup-doctor"
SOUNDFONT_FIX = '"env": {"SYNTH_SOUNDFONT_PATH": "/path/to/TimGM6mb.sf2"}'


# --- the reference text, copied from the inline health_check branch it replaces ---


def reference_text(path, sf_ok, fluidsynth_error, music21_error):
    lines = ["synth-mcp health check\n" + "=" * 22]

    if not path:
        sf_status = "MISSING — SYNTH_SOUNDFONT_PATH is not set"
        sf_ok = False
    elif not sf_ok:
        sf_status = f"MISSING — file not found at {path!r}"
        sf_ok = False
    else:
        sf_status = f"OK — {path}"
        sf_ok = True
    lines.append(f"Soundfont:    {sf_status}")

    if not sf_ok:
        lines.append(
            "\n  To fix: download an SF2 soundfont, e.g. TimGM6mb.sf2 from\n"
            "  https://sourceforge.net/projects/timidity/files/\n"
            "  Then add to your LLM client config:\n"
            '    "env": {"SYNTH_SOUNDFONT_PATH": "/path/to/soundfont.sf2"}'
        )

    if fluidsynth_error:
        lines.append(f"FluidSynth:   MISSING — {fluidsynth_error}")
    else:
        lines.append("FluidSynth:   OK")

    if music21_error:
        lines.append(f"music21:      MISSING — {music21_error}")
    else:
        lines.append("music21:      OK")

    all_ok = sf_ok and fluidsynth_error is None and music21_error is None
    lines.append(f"\nOverall:      {'READY' if all_ok else 'NOT READY'}")
    if not all_ok:
        lines.append("Fix the issues above, then restart the server and run health_check again.")

    return "\n".join(lines)


def make_probe(sf_state, fluidsynth_error, music21_error):
    path, sf_ok = {"unset": ("", False), "missing": ("/nope/x.sf2", False), "ok": ("/x/y.sf2", True)}[
        sf_state
    ]
    return Probe(
        soundfont_path=path,
        soundfont_ok=sf_ok,
        fluidsynth_error=fluidsynth_error,
        music21_version=None if music21_error else "9.9",
        music21_error=music21_error,
    )


# --- the text report, unchanged ---


@pytest.mark.parametrize("sf_state", ["unset", "missing", "ok"])
@pytest.mark.parametrize("fluidsynth_error", [None, "no libfluidsynth"])
@pytest.mark.parametrize("music21_error", [None, "No module named 'music21'"])
def test_health_text_matches_the_old_report(sf_state, fluidsynth_error, music21_error):
    p = make_probe(sf_state, fluidsynth_error, music21_error)

    assert health_text(p) == reference_text(
        p.soundfont_path, p.soundfont_ok, fluidsynth_error, music21_error
    )


# --- probe() ---


class TestProbe:
    def test_soundfont_unset(self, monkeypatch):
        monkeypatch.delenv("SYNTH_SOUNDFONT_PATH", raising=False)

        assert (probe().soundfont_path, probe().soundfont_ok) == ("", False)

    def test_soundfont_missing_file(self, monkeypatch):
        monkeypatch.setenv("SYNTH_SOUNDFONT_PATH", "/nope/x.sf2")

        assert probe().soundfont_ok is False

    def test_soundfont_ok(self, monkeypatch, tmp_path):
        sf2 = tmp_path / "test.sf2"
        sf2.write_bytes(b"dummy")
        monkeypatch.setenv("SYNTH_SOUNDFONT_PATH", str(sf2))

        assert probe().soundfont_ok is True

    def test_fluidsynth_import_error_is_captured(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "fluidsynth", None)

        assert probe().fluidsynth_error is not None

    def test_fluidsynth_os_error_is_captured(self, monkeypatch):
        real = builtins.__import__

        def fake(name, *args, **kwargs):
            if name.split(".")[0] == "fluidsynth":
                raise OSError("libfluidsynth not found")
            return real(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake)

        assert probe().fluidsynth_error == "libfluidsynth not found"

    def test_fluidsynth_ok(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "fluidsynth", types.ModuleType("fluidsynth"))

        assert probe().fluidsynth_error is None

    def test_music21_missing(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "music21", None)

        p = probe()

        assert p.music21_error is not None and p.music21_version is None

    def test_music21_ok_reports_version(self):
        import music21

        p = probe()

        assert p.music21_error is None and p.music21_version == music21.__version__

    def test_probe_reads_the_env_at_call_time(self, monkeypatch, tmp_path):
        sf2 = tmp_path / "test.sf2"
        sf2.write_bytes(b"dummy")
        monkeypatch.setenv("SYNTH_SOUNDFONT_PATH", str(sf2))
        p1 = probe()
        monkeypatch.delenv("SYNTH_SOUNDFONT_PATH")
        p2 = probe()

        assert p1.soundfont_ok is True and p2.soundfont_ok is False


# --- the Setup Doctor mapping ---


class TestHealthChecks:
    def test_soundfont_unset_fails_with_download_hint(self):
        [check] = [c for c in health_checks(make_probe("unset", None, None)) if c.name == "Soundfont"]

        assert check == HealthCheck(
            "Soundfont",
            "fail",
            hint=(
                "SYNTH_SOUNDFONT_PATH is not set; download an SF2 soundfont such as "
                "TimGM6mb.sf2 (https://sourceforge.net/projects/timidity/files/)."
            ),
            fix_snippet=SOUNDFONT_FIX,
            doc_url=DOC,
        )
        assert DOC == (
            "https://github.com/raulkivi/sheet-music-mcp/blob/main/synth-mcp/TROUBLESHOOTING.md"
        )

    def test_soundfont_missing_file_names_the_path(self):
        [check] = [c for c in health_checks(make_probe("missing", None, None)) if c.name == "Soundfont"]

        assert check.status == "fail"
        assert check.hint == "No soundfont file at '/nope/x.sf2'."
        assert check.fix_snippet == SOUNDFONT_FIX
        assert check.doc_url == DOC

    def test_soundfont_ok_carries_nothing_extra(self):
        [check] = [c for c in health_checks(make_probe("ok", None, None)) if c.name == "Soundfont"]

        assert check == HealthCheck("Soundfont", "ok")
        assert check.to_dict() == {"name": "Soundfont", "status": "ok"}

    def test_fluidsynth_fail_carries_error_hint_and_fix(self):
        checks = health_checks(make_probe("ok", "no libfluidsynth", None))
        [check] = [c for c in checks if c.name == "FluidSynth"]

        assert check == HealthCheck(
            "FluidSynth",
            "fail",
            hint="FluidSynth could not be loaded: no libfluidsynth",
            fix_snippet="sudo apt install libfluidsynth-dev",
            doc_url=DOC,
        )
        assert check.version is None

    def test_fluidsynth_ok_reports_the_package_version(self):
        checks = health_checks(make_probe("ok", None, None))
        [check] = [c for c in checks if c.name == "FluidSynth"]

        assert check.status == "ok"
        try:
            assert check.version == importlib.metadata.version("pyfluidsynth")
        except importlib.metadata.PackageNotFoundError:
            assert check.version is None

    def test_music21_fail_carries_error_hint_and_fix(self):
        checks = health_checks(make_probe("ok", None, "No module named 'music21'"))
        [check] = [c for c in checks if c.name == "music21"]

        assert check == HealthCheck(
            "music21",
            "fail",
            hint="music21 is not installed: No module named 'music21'",
            fix_snippet="uv sync",
            doc_url=DOC,
        )

    def test_music21_ok_reports_version(self):
        checks = health_checks(make_probe("ok", None, None))
        [check] = [c for c in checks if c.name == "music21"]

        assert check == HealthCheck("music21", "ok", version="9.9")

    def test_rows_are_in_order_soundfont_fluidsynth_music21(self):
        assert [c.name for c in health_checks(make_probe("unset", "boom", "gone"))] == [
            "Soundfont",
            "FluidSynth",
            "music21",
        ]


class TestBuildHealthReport:
    def test_derives_not_ready_from_any_fail(self):
        assert build_health_report(make_probe("unset", None, None))["status"] == "not_ready"
        assert build_health_report(make_probe("ok", "boom", None))["status"] == "not_ready"
        assert build_health_report(make_probe("ok", None, "gone"))["status"] == "not_ready"

    def test_all_ok_is_ready(self):
        assert build_health_report(make_probe("ok", None, None))["status"] == "ready"

    def test_is_the_core_report_over_the_checks(self):
        p = make_probe("missing", "boom", None)

        assert build_health_report(p) == health_report(health_checks(p))

    def test_report_validates_against_the_output_schema(self):
        jsonschema.validate(
            build_health_report(make_probe("unset", "boom", "gone")), HEALTH_OUTPUT_SCHEMA
        )


# --- the server wiring ---


class TestServerWiring:
    async def test_result_is_the_text_and_the_standard_report(self):
        p = probe()

        result = await call_tool_result("health_check", {})

        assert not result.is_error
        assert result.content[0].type == "text"
        assert result.content[0].text == health_text(p)
        assert result.structured_content == build_health_report(p)

    def test_setup_doctor_is_registered_next_to_the_player(self):
        assert [r.uri for r in server.DEFAULT_UI_REGISTRY.list_resources()] == []
        assert SETUP_DOCTOR.uri == DOCTOR_URI
        assert SETUP_DOCTOR.asset == "setup-doctor.html"

    async def test_health_check_declares_the_output_schema(self):
        tool = next(t for t in await list_tools() if t.name == "health_check")

        assert tool.output_schema == HEALTH_OUTPUT_SCHEMA

    async def test_health_check_has_no_link_without_a_ui_build(self):
        tool = next(t for t in await list_tools() if t.name == "health_check")

        assert tool.meta is None

    async def test_health_check_links_the_setup_doctor_when_packaged(self, packaged_ui):
        tool = next(t for t in await list_tools() if t.name == "health_check")

        assert tool.meta == {"ui": {"resourceUri": DOCTOR_URI}}

    def test_setup_doctor_is_listed_when_packaged(self, packaged_ui):
        resources = server.ui_registry.list_resources()
        uris = [r.uri for r in resources]

        assert uris == ["ui://synth/practice-player", DOCTOR_URI]
        doctor = next(r for r in resources if r.uri == DOCTOR_URI)
        # The [Copy] button asks for the clipboard, and the registry sends it in _meta.ui.
        assert doctor.meta["ui"]["permissions"]["clipboardWrite"] == {}

    def test_setup_doctor_reads_when_packaged(self, packaged_ui):
        from .conftest import SETUP_DOCTOR_HTML

        result = server.ui_registry.read(DOCTOR_URI)

        [contents] = result.contents
        assert (contents.uri, contents.text) == (DOCTOR_URI, SETUP_DOCTOR_HTML)

    def test_setup_doctor_read_fails_without_a_build(self):
        from sheet_music_mcp_core.errors import ProcessingError

        with pytest.raises(ProcessingError) as caught:
            server.ui_registry.read(DOCTOR_URI)

        assert caught.value.error_code == "UI_ASSET_MISSING"
