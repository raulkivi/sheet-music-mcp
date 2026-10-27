"""Score references (UX Wave 2): scores given as a file path instead of inline text
(docs/conventions.md, Score References; docs/research/ux-wave2-plan.md §3.2, §4).

`analyze_recording` and `load_score` take `musicxml` or `musicxml_path` (exactly one), next to the
Wave 1 `part` / `part_id` requirement. `describe_score` is the shared core tool. `audio_path` is
not confined in this wave (plan decision W2-3).
"""

import json
import os
import zipfile
from pathlib import Path

import numpy as np
import pytest
from mcp import Client
from scipy.io.wavfile import write as wav_write
from sheet_music_mcp_core.references import exactly_one

from pitch_mcp import engine, server
from pitch_mcp.server import app, call_tool, list_tools

SENTINEL = "TOP-SECRET-SENTINEL-4711"


def _score(parts, *, title="Practice"):
    """MusicXML at 96 BPM with two measures per part: parts = [(xml_id, name, step), ...]."""
    part_list = "".join(
        f'<score-part id="{pid}"><part-name>{name}</part-name></score-part>' for pid, name, _ in parts
    )
    body = "".join(
        f'<part id="{pid}"><measure number="1"><attributes><divisions>1</divisions>'
        f"<key><fifths>0</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time>"
        f"<clef><sign>G</sign><line>2</line></clef></attributes>"
        f'<direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit>'
        f'<per-minute>96</per-minute></metronome></direction-type><sound tempo="96"/></direction>'
        f"<note><pitch><step>{step}</step><octave>4</octave></pitch><duration>2</duration>"
        f"<type>half</type></note>"
        f"<note><pitch><step>{step}</step><octave>4</octave></pitch><duration>2</duration>"
        f'<type>half</type></note></measure><measure number="2">'
        f"<note><pitch><step>{step}</step><octave>4</octave></pitch><duration>4</duration>"
        f"<type>whole</type></note></measure></part>"
        for pid, _, step in parts
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><score-partwise version="3.1">'
        f"<work><work-title>{title}</work-title></work>"
        f"<part-list>{part_list}</part-list>{body}</score-partwise>"
    )


SATB = _score([("P1", "Soprano", "G"), ("P2", "Alto", "E"), ("P3", "Tenor", "C"), ("P4", "Bass", "A")])


@pytest.fixture
def root(tmp_path, monkeypatch):
    """The output root (the default read root) holding the score fixtures."""
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(root))
    monkeypatch.delenv("SHEET_MUSIC_INPUT_ROOTS", raising=False)
    (root / "satb.musicxml").write_text(SATB, encoding="utf-8")
    return root


@pytest.fixture
def wav(tmp_path):
    sr = 22050
    t = np.linspace(0, 1.0, sr)
    audio = (0.5 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
    path = tmp_path / "take.wav"
    wav_write(path, sr, (audio * 32767).astype(np.int16))
    return str(path)


@pytest.fixture
def fake_analysis(monkeypatch):
    """Replace the heavy pYIN + DTW analysis; record the score text it was given."""
    calls = []

    def _analyze(audio_path, musicxml, part_id):
        calls.append(musicxml)
        return {"part": part_id, "score_chars": len(musicxml), "note_accuracy": []}

    monkeypatch.setattr(server, "analyze_recording", _analyze)
    return calls


def _payload(result):
    return json.loads(result[0].text)


def _stop(payload):
    if "session_id" in payload:
        engine.stop_monitoring(payload["session_id"])


async def _protocol_call(name, arguments):
    async with Client(app) as client:
        return await client.call_tool(name, arguments)


# --- Schemas ---------------------------------------------------------------------------------


class TestSchemas:
    @pytest.mark.parametrize("tool_name", ["analyze_recording", "load_score"])
    async def test_musicxml_or_path_next_to_part_requirement(self, tool_name):
        schema = next(t for t in await list_tools() if t.name == tool_name).input_schema

        assert schema["properties"]["musicxml"]["type"] == "string"
        assert schema["properties"]["musicxml_path"]["type"] == "string"
        assert ".mxl" in schema["properties"]["musicxml_path"]["description"]
        assert "musicxml_path" in schema["properties"]["musicxml"]["description"]
        assert schema["oneOf"] == exactly_one("musicxml", "musicxml_path")["oneOf"]
        assert schema["anyOf"] == [{"required": ["part"]}, {"required": ["part_id"]}]
        assert "musicxml" not in schema.get("required", [])
        assert "musicxml_path" not in schema.get("required", [])

    async def test_analyze_recording_still_requires_audio_path(self):
        schema = next(t for t in await list_tools() if t.name == "analyze_recording").input_schema

        assert schema["required"] == ["audio_path"]
        assert schema["properties"]["audio_path"]["description"] == "Absolute path to a 16-bit PCM WAV file"


# --- load_score ------------------------------------------------------------------------------


class TestLoadScoreByPath:
    async def test_path_creates_the_same_session_as_inline(self, root):
        inline = _payload(await call_tool("load_score", {"musicxml": SATB, "part": "Alto"}))
        by_path = _payload(
            await call_tool("load_score", {"musicxml_path": str(root / "satb.musicxml"), "part": "Alto"})
        )
        try:
            inline_session = engine._registry.get(inline["session_id"])
            path_session = engine._registry.get(by_path["session_id"])

            assert by_path["session_id"] != inline["session_id"]
            assert {k: v for k, v in by_path.items() if k != "session_id"} == {
                k: v for k, v in inline.items() if k != "session_id"
            }
            assert (path_session.part_id, path_session.part_name) == ("P2", "Alto")
            assert len(path_session.note_sequence) == len(inline_session.note_sequence) == 3
            assert path_session.note_sequence == inline_session.note_sequence
            assert path_session._nominal_bpm == inline_session._nominal_bpm == 96
        finally:
            _stop(inline)
            _stop(by_path)

    async def test_relative_path_resolves_against_the_output_root(self, root):
        payload = _payload(await call_tool("load_score", {"musicxml_path": "satb.musicxml", "part": "Bass"}))
        try:
            assert payload["part_id"] == "P4"
        finally:
            _stop(payload)

    @pytest.mark.parametrize("with_container", [True, False])
    async def test_mxl_path(self, root, with_container):
        mxl = root / "satb.mxl"
        with zipfile.ZipFile(mxl, "w", zipfile.ZIP_DEFLATED) as archive:
            if with_container:
                archive.writestr(
                    "META-INF/container.xml",
                    '<?xml version="1.0"?><container><rootfiles>'
                    '<rootfile full-path="score/satb.musicxml"/></rootfiles></container>',
                )
                archive.writestr("score/satb.musicxml", SATB)
            else:
                archive.writestr("satb.xml", SATB)

        payload = _payload(await call_tool("load_score", {"musicxml_path": str(mxl), "part": "Tenor"}))
        try:
            assert (payload["part_id"], payload["part_name"], payload["measure_count"]) == ("P3", "Tenor", 2)
        finally:
            _stop(payload)

    async def test_missing_file_inside_the_root(self, root):
        result = await call_tool("load_score", {"musicxml_path": str(root / "nope.musicxml"), "part": "S"})

        assert _payload(result)["error_code"] == "FILE_NOT_FOUND"

    async def test_inline_validation_message_is_unchanged(self):
        result = await call_tool("load_score", {"musicxml": "", "part": "S"})

        assert result[0].text == json.dumps({"error": "MusicXML string is empty.", "error_code": "INVALID_INPUT"})

    async def test_path_to_a_file_that_is_not_musicxml(self, root):
        (root / "page.xml").write_text("<html><body>hello</body></html>", encoding="utf-8")

        result = await call_tool("load_score", {"musicxml_path": str(root / "page.xml"), "part": "S"})

        assert _payload(result)["error_code"] == "INVALID_INPUT"
        assert "hello" not in result[0].text

    async def test_inline_and_path_together_are_rejected_without_a_session(self, root):
        before = len(engine.list_sessions()["sessions"])
        result = await call_tool(
            "load_score", {"musicxml": SATB, "musicxml_path": str(root / "satb.musicxml"), "part": "S"}
        )

        assert _payload(result)["error_code"] == "INVALID_PARAMETER"
        assert len(engine.list_sessions()["sessions"]) == before

    async def test_missing_part_keeps_the_existing_direct_call_message(self, root):
        result = await call_tool("load_score", {"musicxml_path": str(root / "satb.musicxml")})
        payload = _payload(result)

        assert payload == {"error": "part is required.", "error_code": "INVALID_INPUT"}


# --- analyze_recording -----------------------------------------------------------------------


class TestAnalyzeRecordingByPath:
    async def test_path_gives_the_same_content_as_inline(self, root, wav, fake_analysis):
        inline = await call_tool("analyze_recording", {"audio_path": wav, "musicxml": SATB, "part": "S"})
        by_path = await call_tool(
            "analyze_recording",
            {"audio_path": wav, "musicxml_path": str(root / "satb.musicxml"), "part": "S"},
        )

        assert by_path[0].text == inline[0].text
        assert fake_analysis == [SATB, SATB]

    async def test_mxl_path(self, root, wav, fake_analysis):
        with zipfile.ZipFile(root / "satb.mxl", "w") as archive:
            archive.writestr("satb.musicxml", SATB)

        result = await call_tool(
            "analyze_recording",
            {"audio_path": wav, "musicxml_path": str(root / "satb.mxl"), "part": "S"},
        )

        assert _payload(result)["part"] == "S"
        assert fake_analysis == [SATB]

    async def test_audio_path_is_checked_first_and_not_confined(self, root, fake_analysis):
        result = await call_tool(
            "analyze_recording",
            {"audio_path": "/nonexistent.wav", "musicxml_path": "/etc/passwd", "part": "S"},
        )

        assert _payload(result)["error_code"] == "FILE_NOT_FOUND"
        assert fake_analysis == []


# --- Paths outside the read roots ------------------------------------------------------------


@pytest.fixture
def outside(tmp_path):
    """A valid score outside the read roots whose content must never be echoed."""
    folder = tmp_path / "outside"
    folder.mkdir()
    secret = folder / "secret.musicxml"
    secret.write_text(_score([("P1", SENTINEL, "C")], title=SENTINEL), encoding="utf-8")
    return secret


def _outside_paths(root, outside):
    link = root / "link.musicxml"
    link.symlink_to(outside)
    return {
        "absolute": str(outside),
        "etc_passwd": "/etc/passwd",
        "dot_dot": "../outside/secret.musicxml",
        "symlink": str(link),
    }


class TestReadConfinement:
    @pytest.mark.parametrize("kind", ["absolute", "etc_passwd", "dot_dot", "symlink"])
    async def test_load_score_rejects_paths_outside_the_roots(self, root, outside, kind):
        path = _outside_paths(root, outside)[kind]
        before = len(engine.list_sessions()["sessions"])

        result = await call_tool("load_score", {"musicxml_path": path, "part": "P1"})

        assert _payload(result)["error_code"] == "INVALID_PARAMETER"
        assert SENTINEL not in result[0].text
        assert "root:" not in result[0].text  # nothing from /etc/passwd
        assert len(engine.list_sessions()["sessions"]) == before

    @pytest.mark.parametrize("kind", ["absolute", "etc_passwd", "dot_dot", "symlink"])
    async def test_analyze_recording_rejects_paths_outside_the_roots(
        self, root, outside, wav, fake_analysis, kind
    ):
        path = _outside_paths(root, outside)[kind]

        result = await call_tool("analyze_recording", {"audio_path": wav, "musicxml_path": path, "part": "P1"})

        assert _payload(result)["error_code"] == "INVALID_PARAMETER"
        assert SENTINEL not in result[0].text
        assert fake_analysis == []

    async def test_input_roots_extend_the_allowed_set(self, root, outside, monkeypatch):
        monkeypatch.setenv("SHEET_MUSIC_INPUT_ROOTS", str(outside.parent))

        payload = _payload(await call_tool("load_score", {"musicxml_path": str(outside), "part": "P1"}))
        try:
            assert payload["part_id"] == "P1"
        finally:
            _stop(payload)


# --- Through the protocol (schema validation in make_handlers) -------------------------------


class TestProtocol:
    @pytest.mark.parametrize("tool_name", ["analyze_recording", "load_score"])
    async def test_both_score_parameters_give_only_one_of(self, root, wav, tool_name):
        arguments = {"musicxml": SATB, "musicxml_path": str(root / "satb.musicxml"), "part": "S"}
        if tool_name == "analyze_recording":
            arguments["audio_path"] = wav

        result = await _protocol_call(tool_name, arguments)
        payload = json.loads(result.content[0].text)

        assert result.is_error
        assert payload["error_code"] == "INVALID_PARAMETER"
        assert "give only one of these parameters: 'musicxml', 'musicxml_path'" in payload["error"]
        assert "<score-partwise" not in payload["error"]

    @pytest.mark.parametrize("tool_name", ["analyze_recording", "load_score"])
    async def test_neither_score_parameter_is_required_error(self, wav, tool_name):
        arguments = {"part": "S"}
        if tool_name == "analyze_recording":
            arguments["audio_path"] = wav

        result = await _protocol_call(tool_name, arguments)
        payload = json.loads(result.content[0].text)

        assert result.is_error
        assert payload["error_code"] == "INVALID_PARAMETER"
        assert "one of these parameters is required: 'musicxml', 'musicxml_path'" in payload["error"]

    @pytest.mark.parametrize("score", ["musicxml", "musicxml_path"])
    async def test_missing_part_keeps_the_existing_message(self, root, score):
        value = SATB if score == "musicxml" else str(root / "satb.musicxml")

        result = await _protocol_call("load_score", {score: value})
        payload = json.loads(result.content[0].text)

        assert result.is_error
        assert payload == {
            "error": "Input validation error: one of these parameters is required: 'part', 'part_id'",
            "error_code": "INVALID_PARAMETER",
        }

    async def test_load_score_by_path_through_the_protocol(self, root):
        result = await _protocol_call(
            "load_score", {"musicxml_path": str(root / "satb.musicxml"), "part": "Soprano"}
        )
        payload = json.loads(result.content[0].text)
        try:
            assert not result.is_error
            assert payload["part_id"] == "P1"
        finally:
            _stop(payload)

    async def test_path_outside_the_roots_through_the_protocol(self, root, outside):
        result = await _protocol_call("load_score", {"musicxml_path": str(outside), "part": "P1"})

        assert json.loads(result.content[0].text)["error_code"] == "INVALID_PARAMETER"
        assert SENTINEL not in result.content[0].text


# --- describe_score --------------------------------------------------------------------------


class TestDescribeScore:
    async def test_listed(self):
        assert "describe_score" in {t.name for t in await list_tools()}

    async def test_inline(self):
        payload = _payload(await call_tool("describe_score", {"musicxml": SATB}))

        assert [p["id"] for p in payload["parts"]] == ["P1", "P2", "P3", "P4"]
        assert [p["name"] for p in payload["parts"]] == ["Soprano", "Alto", "Tenor", "Bass"]
        assert payload["tempo_bpm"] == 96
        assert payload["measures"] == 2

    async def test_path(self, root):
        payload = _payload(await call_tool("describe_score", {"musicxml_path": str(root / "satb.musicxml")}))

        assert [p["id"] for p in payload["parts"]] == ["P1", "P2", "P3", "P4"]

    async def test_path_outside_the_roots(self, root, outside):
        result = await call_tool("describe_score", {"musicxml_path": str(outside)})

        assert _payload(result)["error_code"] == "INVALID_PARAMETER"
        assert SENTINEL not in result[0].text

    async def test_through_the_protocol(self, root):
        result = await _protocol_call("describe_score", {"musicxml_path": str(root / "satb.musicxml")})

        assert not result.is_error
        assert [p["id"] for p in json.loads(result.content[0].text)["parts"]] == ["P1", "P2", "P3", "P4"]

    async def test_in_capabilities(self):
        payload = _payload(await call_tool("list_capabilities", {}))

        assert "describe_score" in payload["tools"]
        assert "mxl" in payload["input_formats"]
        assert payload["input_parameters"] == ["musicxml", "musicxml_path", "measures"]


# --- Server wiring ---------------------------------------------------------------------------


def test_call_tool_takes_an_optional_context():
    import inspect

    assert inspect.signature(call_tool).parameters["ctx"].default is None


def test_engine_stays_free_of_mcp_reference_modules():
    import ast

    tree = ast.parse(Path(engine.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = {"references", "content", "wiring"}
    assert not {m for m in imported if m == "mcp" or m.startswith("mcp.")}
    assert not {m for m in imported if m.split(".")[-1] in forbidden}


def test_audio_path_is_not_confined(tmp_path, monkeypatch, wav, fake_analysis):
    """W2-3: audio inputs keep the Wave 1 behaviour; a WAV outside the read roots is still read."""
    root = tmp_path / "elsewhere"
    root.mkdir()
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(root))
    assert not Path(wav).resolve().is_relative_to(root)

    import asyncio

    result = asyncio.run(call_tool("analyze_recording", {"audio_path": wav, "musicxml": SATB, "part": "S"}))

    assert _payload(result)["part"] == "S"
    assert os.path.exists(wav)
