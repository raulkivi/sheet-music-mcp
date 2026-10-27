"""Score references (UX Wave 2): scores passed as file paths, abc_to_musicxml returning a path for
large scores, and the shared describe_score tool (docs/conventions.md, Score References)."""

import asyncio
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from mcp import Client

from musicxml_abc_mcp.server import app, call_tool, list_tools

from .test_server import MINIMAL_ABC, MINIMAL_MUSICXML

SENTINEL = "sentinel-secret-line-do-not-leak"

# 30 bars of eighth notes: music21 writes about 60 KB of MusicXML, well over the 8 KB inline limit.
LONG_ABC = "X:1\nT:Long Tune\nM:4/4\nL:1/8\nK:C\n" + "CDEF GABc|" * 30 + "]"


@pytest.fixture
def root(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(out))
    for name in ("SHEET_MUSIC_INPUT_ROOTS", "SHEET_MUSIC_INLINE_MAX_BYTES", "SHEET_MUSIC_MAX_SCORE_BYTES"):
        monkeypatch.delenv(name, raising=False)
    return out.resolve()


def _payload(content):
    return json.loads(content[0].text)


def _tool(name):
    return next(t for t in asyncio.run(list_tools()) if t.name == name)


def _with_client(call):
    async def _go():
        async with Client(app) as client:
            return await call(client)

    return asyncio.run(_go())


def _mxl(path: Path, text: str, *, container: bool = True) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        if container:
            archive.writestr(
                "META-INF/container.xml",
                '<?xml version="1.0" encoding="UTF-8"?><container><rootfiles>'
                '<rootfile full-path="score/tune.musicxml"/></rootfiles></container>',
            )
            archive.writestr("score/tune.musicxml", text)
        else:
            archive.writestr("tune.xml", text)
    return path


# --- Schemas -----------------------------------------------------------------------------------


class TestSchemas:
    def test_musicxml_to_abc_takes_text_or_path(self):
        schema = _tool("musicxml_to_abc").input_schema

        assert {"musicxml", "musicxml_path", "part", "part_id"} <= set(schema["properties"])
        assert schema["oneOf"] == [{"required": ["musicxml"]}, {"required": ["musicxml_path"]}]
        assert "musicxml" not in schema.get("required", [])
        assert "musicxml_path" in schema["properties"]["musicxml"]["description"]

    def test_abc_to_musicxml_has_return_mode(self):
        tool = _tool("abc_to_musicxml")
        schema = tool.input_schema

        assert schema["properties"]["return"]["enum"] == ["auto", "path", "inline"]
        assert schema["properties"]["return"]["default"] == "auto"
        assert schema["required"] == ["abc"]
        assert "return" in tool.description


# --- musicxml_to_abc with a path ---------------------------------------------------------------


class TestPathInput:
    async def test_path_gives_the_same_result_as_inline(self, root):
        (root / "tune.musicxml").write_text(MINIMAL_MUSICXML, encoding="utf-8")

        inline = await call_tool("musicxml_to_abc", {"musicxml": MINIMAL_MUSICXML})
        by_path = await call_tool("musicxml_to_abc", {"musicxml_path": str(root / "tune.musicxml")})

        assert "abc" in _payload(inline)
        assert by_path[0].text == inline[0].text

    async def test_relative_path_is_read_from_the_output_root(self, root):
        (root / "tune.xml").write_text(MINIMAL_MUSICXML, encoding="utf-8")

        inline = await call_tool("musicxml_to_abc", {"musicxml": MINIMAL_MUSICXML})
        by_path = await call_tool("musicxml_to_abc", {"musicxml_path": "tune.xml"})

        assert by_path[0].text == inline[0].text

    @pytest.mark.parametrize("container", [True, False])
    async def test_mxl_path_works(self, root, container):
        path = _mxl(root / "tune.mxl", MINIMAL_MUSICXML, container=container)

        inline = await call_tool("musicxml_to_abc", {"musicxml": MINIMAL_MUSICXML})
        by_path = await call_tool("musicxml_to_abc", {"musicxml_path": str(path)})

        assert by_path[0].text == inline[0].text

    async def test_part_selection_works_with_a_path(self, root):
        (root / "tune.musicxml").write_text(MINIMAL_MUSICXML, encoding="utf-8")

        result = await call_tool(
            "musicxml_to_abc", {"musicxml_path": str(root / "tune.musicxml"), "part": "Soprano"}
        )

        assert _payload(result)["parts_included"] == ["P1"]

    async def test_missing_file_is_file_not_found(self, root):
        result = await call_tool("musicxml_to_abc", {"musicxml_path": str(root / "missing.musicxml")})

        assert _payload(result)["error_code"] == "FILE_NOT_FOUND"

    async def test_non_musicxml_file_is_invalid_input(self, root):
        (root / "notes.xml").write_text("<foo>" + SENTINEL + "</foo>", encoding="utf-8")

        result = await call_tool("musicxml_to_abc", {"musicxml_path": str(root / "notes.xml")})

        assert _payload(result)["error_code"] == "INVALID_INPUT"
        assert SENTINEL not in result[0].text


class TestPathConfinement:
    async def test_etc_passwd_is_refused(self, root):
        result = await call_tool("musicxml_to_abc", {"musicxml_path": "/etc/passwd"})

        assert _payload(result)["error_code"] == "INVALID_PARAMETER"
        assert "root:" not in result[0].text

    async def test_parent_directory_is_refused(self, root):
        (root.parent / "x.musicxml").write_text(SENTINEL, encoding="utf-8")

        result = await call_tool("musicxml_to_abc", {"musicxml_path": "../x.musicxml"})

        assert _payload(result)["error_code"] == "INVALID_PARAMETER"
        assert SENTINEL not in result[0].text

    async def test_symlink_pointing_outside_is_refused(self, root):
        outside = root.parent / "outside.musicxml"
        outside.write_text(MINIMAL_MUSICXML.replace("Test Score", SENTINEL), encoding="utf-8")
        (root / "link.musicxml").symlink_to(outside)

        result = await call_tool("musicxml_to_abc", {"musicxml_path": str(root / "link.musicxml")})

        assert _payload(result)["error_code"] == "INVALID_PARAMETER"
        assert SENTINEL not in result[0].text

    async def test_input_roots_extend_the_allowed_folders(self, root, monkeypatch, tmp_path):
        extra = tmp_path / "library"
        extra.mkdir()
        (extra / "tune.musicxml").write_text(MINIMAL_MUSICXML, encoding="utf-8")
        monkeypatch.setenv("SHEET_MUSIC_INPUT_ROOTS", str(extra))

        result = await call_tool("musicxml_to_abc", {"musicxml_path": str(extra / "tune.musicxml")})

        assert "abc" in _payload(result)


class TestProtocol:
    @pytest.mark.parametrize(
        "arguments",
        [{"musicxml": MINIMAL_MUSICXML, "musicxml_path": "tune.musicxml"}, {}],
        ids=["both", "neither"],
    )
    def test_both_or_neither_is_invalid_parameter(self, root, arguments):
        result = _with_client(lambda client: client.call_tool("musicxml_to_abc", arguments))

        assert result.is_error
        assert json.loads(result.content[0].text)["error_code"] == "INVALID_PARAMETER"
        assert "<score-partwise" not in result.content[0].text

    def test_path_call_through_the_protocol(self, root):
        (root / "tune.musicxml").write_text(MINIMAL_MUSICXML, encoding="utf-8")

        result = _with_client(
            lambda client: client.call_tool("musicxml_to_abc", {"musicxml_path": "tune.musicxml"})
        )

        assert not result.is_error
        assert "X:1" in json.loads(result.content[0].text)["abc"]

    def test_unknown_return_mode_is_invalid_parameter(self, root):
        result = _with_client(
            lambda client: client.call_tool("abc_to_musicxml", {"abc": MINIMAL_ABC, "return": "zip"})
        )

        assert result.is_error
        assert json.loads(result.content[0].text)["error_code"] == "INVALID_PARAMETER"


# --- abc_to_musicxml as a producer -------------------------------------------------------------


class TestAbcToMusicxmlReturn:
    async def test_large_score_auto_returns_a_path(self, root):
        result = await call_tool("abc_to_musicxml", {"abc": LONG_ABC})
        payload = _payload(result)

        assert "<score-partwise" not in result[0].text
        assert "musicxml" not in payload
        path = Path(payload["musicxml_path"])
        assert path.is_file()
        assert path.parent == root / "scores"
        assert path.name.startswith("from-abc-")
        assert "<score-partwise" in path.read_text(encoding="utf-8")
        assert payload["warnings"] == []
        summary = payload["score_summary"]
        assert summary["title"] == "Long Tune"
        assert summary["measures"] >= 30
        assert [part["id"] for part in summary["parts"]]
        assert result[1].type == "resource_link"
        assert result[1].uri == path.as_uri()

    async def test_small_score_stays_inline(self, root):
        result = await call_tool("abc_to_musicxml", {"abc": MINIMAL_ABC})
        payload = _payload(result)

        assert len(result) == 1
        assert "<score-partwise" in payload["musicxml"]
        assert "musicxml_path" not in payload
        assert not (root / "scores").exists()

    async def test_inline_output_is_byte_identical_to_the_engine_result(self, root):
        engine_result = {"musicxml": MINIMAL_MUSICXML, "warnings": ["w"]}
        with patch("musicxml_abc_mcp.server.abc_to_musicxml", return_value=engine_result):
            auto = await call_tool("abc_to_musicxml", {"abc": MINIMAL_ABC})
            inline = await call_tool("abc_to_musicxml", {"abc": MINIMAL_ABC, "return": "inline"})

        expected = json.dumps(engine_result, indent=2)
        assert auto[0].text == expected
        assert inline[0].text == expected

    async def test_inline_mode_keeps_a_large_score_inline(self, root):
        result = await call_tool("abc_to_musicxml", {"abc": LONG_ABC, "return": "inline"})

        assert len(result) == 1
        assert "<score-partwise" in _payload(result)["musicxml"]
        assert not (root / "scores").exists()

    async def test_path_mode_always_writes(self, root):
        result = await call_tool("abc_to_musicxml", {"abc": MINIMAL_ABC, "return": "path"})
        payload = _payload(result)

        assert "<score-partwise" not in result[0].text
        assert Path(payload["musicxml_path"]).is_file()
        assert payload["score_summary"]["parts"]

    async def test_inline_limit_comes_from_the_environment(self, root, monkeypatch):
        monkeypatch.setenv("SHEET_MUSIC_INLINE_MAX_BYTES", "100")

        result = await call_tool("abc_to_musicxml", {"abc": MINIMAL_ABC})

        assert "musicxml_path" in _payload(result)

    async def test_written_file_round_trips_through_musicxml_to_abc(self, root):
        written = _payload(await call_tool("abc_to_musicxml", {"abc": LONG_ABC}))

        result = await call_tool("musicxml_to_abc", {"musicxml_path": written["musicxml_path"]})
        payload = _payload(result)

        assert "error" not in payload
        assert "X:1" in payload["abc"]
        assert payload["abc"].count("C D E F G A B c") == 30

    async def test_error_results_stay_inline(self, root):
        result = await call_tool("abc_to_musicxml", {"abc": "", "return": "path"})

        assert _payload(result)["error_code"] == "INVALID_INPUT"
        assert not (root / "scores").exists()

    async def test_unknown_return_mode_in_a_direct_call(self, root):
        result = await call_tool("abc_to_musicxml", {"abc": MINIMAL_ABC, "return": "zip"})

        assert _payload(result)["error_code"] == "INVALID_PARAMETER"


# --- describe_score ----------------------------------------------------------------------------


class TestDescribeScore:
    def test_is_listed(self):
        assert _tool("describe_score").title == "Describe score"

    def test_is_listed_through_the_protocol(self):
        result = _with_client(lambda client: client.list_tools())

        assert "describe_score" in {tool.name for tool in result.tools}

    async def test_inline_score(self, root):
        payload = _payload(await call_tool("describe_score", {"musicxml": MINIMAL_MUSICXML}))

        assert payload["title"] == "Test Score"
        assert [part["id"] for part in payload["parts"]] == ["P1"]
        assert payload["parts"][0]["name"] == "Soprano"

    async def test_path(self, root):
        (root / "tune.musicxml").write_text(MINIMAL_MUSICXML, encoding="utf-8")

        payload = _payload(await call_tool("describe_score", {"musicxml_path": "tune.musicxml"}))

        assert [part["id"] for part in payload["parts"]] == ["P1"]

    async def test_outside_path_is_invalid_parameter(self, root):
        result = await call_tool("describe_score", {"musicxml_path": "/etc/passwd"})

        assert _payload(result)["error_code"] == "INVALID_PARAMETER"
        assert "root:" not in result[0].text

    def test_through_the_protocol(self, root):
        (root / "tune.musicxml").write_text(MINIMAL_MUSICXML, encoding="utf-8")

        result = _with_client(
            lambda client: client.call_tool("describe_score", {"musicxml_path": "tune.musicxml"})
        )

        assert not result.is_error
        assert json.loads(result.content[0].text)["parts"][0]["id"] == "P1"


class TestCapabilities:
    async def test_lists_describe_score_and_path_input(self):
        payload = _payload(await call_tool("list_capabilities", {}))

        assert "describe_score" in payload["tools"]
        assert "mxl" in payload["input_formats"]
        assert payload["input_parameters"] == ["musicxml", "musicxml_path"]
