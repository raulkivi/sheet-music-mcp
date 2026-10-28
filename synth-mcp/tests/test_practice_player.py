"""Practice Player linking: the ``ui://synth/practice-player`` resource, tool ``_meta``,
``structuredContent`` and the app-only ``read_audio_chunk`` / ``get_score_xml``
(proposal 5.2, AC-S2 to AC-S4)."""

import asyncio
import base64
import json
import wave

import jsonschema
import pytest
from mcp import Client, MCPError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS
from sheet_music_mcp_core.artifacts import MAX_CHUNK_BYTES, FileArtifactStore, InMemoryArtifactStore
from sheet_music_mcp_core.ui import UI_MIME, is_app_only

import synth_mcp.server as server
from synth_mcp.engine import describe_mix, wav_format
from synth_mcp.presenter import (
    CHUNK_OUTPUT_SCHEMA,
    PARTS_OUTPUT_SCHEMA,
    SCORE_OUTPUT_SCHEMA,
    SYNTH_OUTPUT_SCHEMA,
)
from synth_mcp.server import app, call_tool_result, list_tools

from .conftest import PLAYER_HTML, use_store
from .midi_helpers import fixture
from .test_server import VALID_MUSICXML

PLAYER_URI = "ui://synth/practice-player"
SATB = fixture("satb_4bars.musicxml")
APP_ONLY = ("read_audio_chunk", "get_score_xml")
TRACK_FIELDS = {"audio_id", "duration_seconds", "sample_rate", "channels", "byte_length", "parts", "tempo_factor"}


@pytest.fixture(autouse=True)
def output_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def rendered(monkeypatch):
    """A fake FluidSynth: a 0.1 s mono 8 kHz WAV (844 bytes), and the MIDI it was given."""
    midi = []

    def fake(midi_bytes, output_path):
        midi.append(midi_bytes)
        with wave.open(output_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(bytes(range(256)) * 3 + b"\0" * 32)
        return 0.1

    monkeypatch.setattr(server, "synthesize_midi", fake)
    return midi


def _with_client(call):
    async def _go():
        async with Client(app) as client:
            return await call(client)

    return asyncio.run(_go())


async def _tools():
    return {tool.name: tool for tool in await list_tools()}


async def _synthesize(**arguments):
    result = await call_tool_result("synthesize", {"musicxml": VALID_MUSICXML, **arguments})
    assert not result.is_error, result.content
    return result


def _error_code(result):
    return json.loads(result.content[0].text)["error_code"]


class TestToolLinking:
    async def test_synthesize_links_the_player_when_packaged(self, packaged_ui):
        assert (await _tools())["synthesize"].meta == {"ui": {"resourceUri": PLAYER_URI}}

    async def test_no_link_without_a_ui_build(self):
        assert (await _tools())["synthesize"].meta is None

    async def test_other_model_facing_tools_are_not_linked(self, packaged_ui):
        others = [t for n, t in (await _tools()).items() if n != "synthesize" and not is_app_only(t)]

        assert others
        assert all(t.meta is None or "resourceUri" not in t.meta.get("ui", {}) for t in others)

    @pytest.mark.parametrize("name", ("synthesize", "get_parts"))
    async def test_structured_tools_declare_an_output_schema(self, name):
        schema = (await _tools())[name].output_schema

        assert schema["type"] == "object"
        assert schema["required"]

    @pytest.mark.parametrize("name", APP_ONLY)
    async def test_app_only_tools_stay_app_only_without_a_build(self, name):
        tool = (await _tools())[name]

        assert is_app_only(tool)
        assert tool.meta == {"ui": {"visibility": ["app"]}}

    @pytest.mark.parametrize("name", APP_ONLY)
    async def test_app_only_tools_link_the_player_when_packaged(self, packaged_ui, name):
        assert (await _tools())[name].meta == {"ui": {"resourceUri": PLAYER_URI, "visibility": ["app"]}}

    async def test_app_only_tools_take_ids_never_paths(self):
        tools = await _tools()

        assert set(tools["read_audio_chunk"].input_schema["properties"]) == {"audio_id", "offset", "length"}
        assert set(tools["get_score_xml"].input_schema["properties"]) == {"audio_id"}
        for name in APP_ONLY:
            assert tools[name].input_schema["additionalProperties"] is False

    def test_app_only_tools_are_hidden_from_clients_without_ui(self):
        async def names(client):
            return {t.name for t in (await client.list_tools()).tools}

        listed = _with_client(names)

        assert not set(APP_ONLY) & listed
        assert {"synthesize", "get_parts"} <= listed


class TestResources:
    def test_lists_the_player_when_packaged(self, packaged_ui):
        result = _with_client(lambda c: c.list_resources())

        assert [(r.uri, r.name, r.mime_type) for r in result.resources] == [
            (PLAYER_URI, "Practice Player", UI_MIME)
        ]

    def test_lists_nothing_without_a_ui_build(self):
        assert _with_client(lambda c: c.list_resources()).resources == []

    def test_reads_the_player_html(self, packaged_ui):
        [contents] = _with_client(lambda c: c.read_resource(PLAYER_URI)).contents

        assert (contents.uri, contents.mime_type, contents.text) == (PLAYER_URI, UI_MIME, PLAYER_HTML)

    def test_missing_build_is_an_error_naming_the_fix(self):
        async def read(client):
            with pytest.raises(MCPError) as caught:
                await client.read_resource(PLAYER_URI)
            return caught.value

        error = _with_client(read)

        assert error.code == INTERNAL_ERROR
        assert error.data["error_code"] == "UI_ASSET_MISSING"

    def test_unknown_resource_is_invalid_params(self, packaged_ui):
        async def read(client):
            with pytest.raises(MCPError) as caught:
                await client.read_resource("ui://synth/nope")
            return caught.value

        assert _with_client(read).code == INVALID_PARAMS


class TestSynthesizeStructuredContent:
    async def test_describes_the_track(self, output_root):
        out = output_root / "take.wav"

        result = await _synthesize(output_path=str(out), tempo_factor=0.75)

        data = result.structured_content
        jsonschema.validate(data, SYNTH_OUTPUT_SCHEMA)
        assert set(data) == TRACK_FIELDS
        assert data["duration_seconds"] == 0.1
        assert (data["sample_rate"], data["channels"]) == (8000, 1)
        assert data["byte_length"] == out.stat().st_size == 844
        assert data["tempo_factor"] == 0.75
        assert data["parts"] == [
            {"id": "P1", "name": "Soprano", "included": True, "gain": 1.0},
            {"id": "P2", "name": "Alto", "included": True, "gain": 1.0},
        ]

    async def test_never_exposes_a_path(self, output_root):
        result = await _synthesize(output_path=str(output_root / "take.wav"))

        assert str(output_root) not in json.dumps(result.structured_content)

    async def test_audio_id_is_the_stored_wav(self, output_root, artifacts):
        result = await _synthesize(output_path=str(output_root / "take.wav"))

        info = artifacts.info(result.structured_content["audio_id"])
        assert (info.kind, info.byte_length) == ("audio/wav", 844)

    async def test_unselected_parts_are_listed_as_not_included(self):
        data = (await _synthesize(parts=["Alto"])).structured_content

        assert data["parts"] == [
            {"id": "P1", "name": "Soprano", "included": False, "gain": 0.0},
            {"id": "P2", "name": "Alto", "included": True, "gain": 1.0},
        ]

    async def test_gains_are_the_ones_the_engine_used(self):
        result = await call_tool_result(
            "synthesize",
            {"musicxml": SATB, "preset": "learning", "focus_part": "Alto", "part_gains": {"Bass": 0.0}},
        )

        gains = {p["id"]: p["gain"] for p in result.structured_content["parts"]}
        assert gains == {"P1": 0.5, "P2": 1.5, "P3": 0.5, "P4": 0.0}

    async def test_karaoke_mutes_the_focus_part(self):
        result = await call_tool_result(
            "synthesize", {"musicxml": SATB, "preset": "karaoke", "focus_part": "S", "parts": ["S", "A"]}
        )

        assert [(p["id"], p["included"], p["gain"]) for p in result.structured_content["parts"]] == [
            ("P1", True, 0.0), ("P2", True, 1.0), ("P3", False, 0.0), ("P4", False, 0.0),
        ]

    async def test_default_tempo_factor_is_one(self):
        assert (await _synthesize()).structured_content["tempo_factor"] == 1.0

    async def test_content_is_the_json_and_a_link_without_audio_bytes(self, output_root):
        result = await _synthesize(output_path=str(output_root / "take.wav"))

        assert [b.type for b in result.content] == ["text", "resource_link"]
        assert set(json.loads(result.content[0].text)) == {
            "audio_path", "format", "duration_seconds", "parts_included", "tempo_factor",
        }

    async def test_default_output_is_inside_the_output_root(self, output_root):
        # The artifact store only takes files inside the output root.
        result = await _synthesize()

        path = json.loads(result.content[0].text)["audio_path"]
        assert path.startswith(str(output_root.resolve()))

    async def test_works_with_the_file_backed_store(self, monkeypatch, output_root):
        use_store(monkeypatch, FileArtifactStore())

        result = await _synthesize(output_path=str(output_root / "take.wav"))

        chunk = await call_tool_result(
            "read_audio_chunk", {"audio_id": result.structured_content["audio_id"], "offset": 0, "length": 4}
        )
        assert base64.b64decode(chunk.structured_content["data_b64"]) == b"RIFF"


class TestReadAudioChunk:
    async def _chunks(self, audio_id, size):
        offset, pieces = 0, []
        while True:
            result = await call_tool_result("read_audio_chunk", {"audio_id": audio_id, "offset": offset, "length": size})
            assert not result.is_error
            jsonschema.validate(result.structured_content, CHUNK_OUTPUT_SCHEMA)
            pieces.append(base64.b64decode(result.structured_content["data_b64"]))
            if result.structured_content["eof"]:
                return b"".join(pieces), result
            offset += result.structured_content["length"]

    @pytest.mark.parametrize("size", (2, 500, 844, MAX_CHUNK_BYTES))
    async def test_chunks_reassemble_to_the_wav(self, output_root, size):
        out = output_root / "take.wav"
        result = await _synthesize(output_path=str(out))

        data, last = await self._chunks(result.structured_content["audio_id"], size)

        assert data == out.read_bytes()
        assert last.structured_content["byte_length"] == 844

    async def test_one_byte_chunks_cover_the_start(self, output_root):
        result = await _synthesize(output_path=str(output_root / "take.wav"))

        first = await call_tool_result("read_audio_chunk", {"audio_id": result.structured_content["audio_id"], "offset": 0, "length": 1})

        assert base64.b64decode(first.structured_content["data_b64"]) == b"R"
        assert first.structured_content["eof"] is False

    async def test_text_content_is_one_short_line_without_the_data(self, output_root):
        result = await _synthesize(output_path=str(output_root / "take.wav"))

        chunk = await call_tool_result("read_audio_chunk", {"audio_id": result.structured_content["audio_id"], "offset": 0, "length": 844})

        [block] = chunk.content
        assert "\n" not in block.text and len(block.text) < 120
        assert chunk.structured_content["data_b64"] not in block.text

    async def test_unknown_id_is_invalid_parameter(self):
        result = await call_tool_result("read_audio_chunk", {"audio_id": "nope", "offset": 0, "length": 10})

        assert result.is_error
        assert result.structured_content is None
        assert _error_code(result) == "INVALID_PARAMETER"

    async def test_expired_id_is_invalid_parameter(self, monkeypatch, output_root):
        now = [0.0]
        use_store(monkeypatch, InMemoryArtifactStore(ttl_seconds=5, clock=lambda: now[0]))
        result = await _synthesize()

        now[0] = 5
        expired = await call_tool_result("read_audio_chunk", {"audio_id": result.structured_content["audio_id"], "offset": 0, "length": 10})

        assert expired.is_error
        assert _error_code(expired) == "INVALID_PARAMETER"

    @pytest.mark.parametrize(
        "arguments",
        [
            {"offset": -1, "length": 10},
            {"offset": 0, "length": MAX_CHUNK_BYTES + 1},
            {"offset": 0, "length": 0},
            {"offset": "0", "length": 10},
            {"length": 10},
            {"offset": 0, "length": 10, "path": "/etc/passwd"},
        ],
    )
    def test_bad_arguments_are_invalid_parameter_over_the_protocol(self, arguments):
        result = _with_client(lambda c: c.call_tool("read_audio_chunk", {"audio_id": "x", **arguments}))

        assert result.is_error
        assert json.loads(result.content[0].text)["error_code"] == "INVALID_PARAMETER"

    def test_over_the_protocol_end_to_end(self, output_root):
        out = output_root / "take.wav"

        async def go(client):
            made = await client.call_tool(
                "synthesize", {"musicxml": VALID_MUSICXML, "output_path": str(out)}
            )
            audio_id = made.structured_content["audio_id"]
            got = b""
            while True:
                chunk = await client.call_tool(
                    "read_audio_chunk", {"audio_id": audio_id, "offset": len(got), "length": 700}
                )
                got += base64.b64decode(chunk.structured_content["data_b64"])
                if chunk.structured_content["eof"]:
                    return got

        # The app-only tool is hidden from a client without UI support, but still callable by id.
        assert _with_client(go) == out.read_bytes()


class TestGetScoreXml:
    async def test_returns_the_score_the_audio_was_made_from(self):
        audio_id = (await _synthesize()).structured_content["audio_id"]

        result = await call_tool_result("get_score_xml", {"audio_id": audio_id})

        assert not result.is_error
        jsonschema.validate(result.structured_content, SCORE_OUTPUT_SCHEMA)
        assert result.structured_content == {"audio_id": audio_id, "musicxml": VALID_MUSICXML}

    async def test_follows_the_measures_the_audio_was_cut_to(self):
        result = await call_tool_result("synthesize", {"musicxml": SATB, "measures": [2, 3]})
        audio_id = result.structured_content["audio_id"]

        xml = (await call_tool_result("get_score_xml", {"audio_id": audio_id})).structured_content["musicxml"]

        assert xml.count("<measure ") == 2 * 4  # SATB: two bars in each of four parts

    async def test_text_content_does_not_carry_the_score(self):
        audio_id = (await _synthesize()).structured_content["audio_id"]

        result = await call_tool_result("get_score_xml", {"audio_id": audio_id})

        [block] = result.content
        assert "<score-partwise" not in block.text and "\n" not in block.text

    async def test_unknown_id_is_invalid_parameter(self):
        result = await call_tool_result("get_score_xml", {"audio_id": "nope"})

        assert result.is_error
        assert result.structured_content is None
        assert _error_code(result) == "INVALID_PARAMETER"

    async def test_score_expires_with_its_audio(self, monkeypatch):
        now = [0.0]
        use_store(monkeypatch, InMemoryArtifactStore(ttl_seconds=5, clock=lambda: now[0]))
        audio_id = (await _synthesize()).structured_content["audio_id"]

        now[0] = 5
        result = await call_tool_result("get_score_xml", {"audio_id": audio_id})

        assert result.is_error
        assert _error_code(result) == "INVALID_PARAMETER"

    def test_paths_are_not_accepted(self):
        result = _with_client(lambda c: c.call_tool("get_score_xml", {"audio_id": "x", "musicxml_path": "/etc/passwd"}))

        assert result.is_error
        assert json.loads(result.content[0].text)["error_code"] == "INVALID_PARAMETER"


class TestGetParts:
    async def test_structured_content_equals_the_json_content(self):
        result = await call_tool_result("get_parts", {"musicxml": VALID_MUSICXML})

        jsonschema.validate(result.structured_content, PARTS_OUTPUT_SCHEMA)
        assert result.structured_content == json.loads(result.content[0].text)
        assert [p["id"] for p in result.structured_content["parts"]] == ["P1", "P2"]


class TestErrors:
    @pytest.mark.parametrize(
        "tool, arguments, code",
        [
            ("get_parts", {"musicxml": "<nope/>"}, "INVALID_INPUT"),
            ("synthesize", {"musicxml": "<nope/>"}, "INVALID_INPUT"),
            ("synthesize", {"musicxml": VALID_MUSICXML, "tempo_factor": 9}, "INVALID_PARAMETER"),
            ("synthesize", {"musicxml": VALID_MUSICXML, "parts": ["Tuba"]}, "INVALID_PARAMETER"),
            ("synthesize", {"musicxml": SATB, "measures": [9, 12]}, "INVALID_PARAMETER"),
            ("synthesize", {"musicxml": VALID_MUSICXML, "output_path": "/tmp/x.wav"}, "INVALID_PARAMETER"),
        ],
    )
    def test_keep_the_envelope_and_carry_no_structured_content(self, tool, arguments, code):
        result = _with_client(lambda c: c.call_tool(tool, arguments))

        assert result.is_error
        assert result.structured_content is None
        assert json.loads(result.content[0].text)["error_code"] == code

    async def test_a_failed_render_is_an_error_result(self, monkeypatch):
        from synth_mcp.engine import ProcessingError

        def boom(midi, path):
            raise ProcessingError("no soundfont", "PROCESSING_FAILED")

        monkeypatch.setattr(server, "synthesize_midi", boom)

        result = await call_tool_result("synthesize", {"musicxml": VALID_MUSICXML})

        assert result.is_error and result.structured_content is None
        assert _error_code(result) == "PROCESSING_FAILED"


class TestEngineHelpers:
    def test_wav_format_reads_rate_and_channels(self, tmp_path):
        path = tmp_path / "a.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(44100)
            w.writeframes(b"\0" * 8)

        assert wav_format(str(path)) == (44100, 2)

    def test_describe_mix_defaults_to_every_part_at_unity(self):
        assert describe_mix(SATB, None) == [
            {"id": "P1", "name": "Soprano", "included": True, "gain": 1.0},
            {"id": "P2", "name": "Alto", "included": True, "gain": 1.0},
            {"id": "P3", "name": "Tenor", "included": True, "gain": 1.0},
            {"id": "P4", "name": "Bass", "included": True, "gain": 1.0},
        ]

    def test_describe_mix_applies_selection_and_part_gains(self):
        mix = describe_mix(SATB, ["P2", "P3"], part_gains={"Tenor": 1.25})

        assert [(p["id"], p["included"], p["gain"]) for p in mix] == [
            ("P1", False, 0.0), ("P2", True, 1.0), ("P3", True, 1.25), ("P4", False, 0.0),
        ]
