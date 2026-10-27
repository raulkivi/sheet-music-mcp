"""Score references: scores passed as file paths (docs/conventions.md, Score References).

``render_to_pdf`` and ``render_to_image`` take ``musicxml`` or ``musicxml_path`` (exactly one), and
the shared ``describe_score`` tool is exposed. The renderer is mocked as in test_result_content.py.
"""

import asyncio
import json
import zipfile
from pathlib import Path

import pytest
from mcp import Client

import render_mcp.server as server
from render_mcp.server import app, call_tool, list_tools

from .test_result_content import TINY_PNG, _fake_render_to_image, _fake_render_to_pdf
from .test_server import VALID_MUSICXML

SENTINEL = "SENTINEL-outside-file-must-not-leak"
RENDER_TOOLS = ("render_to_pdf", "render_to_image")

CONTAINER_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<container>
  <rootfiles>
    <rootfile full-path="score.musicxml" media-type="application/vnd.recordare.musicxml+xml"/>
  </rootfiles>
</container>"""


@pytest.fixture
def root(tmp_path, monkeypatch):
    """The output root (and so a read root), separate from files placed outside it."""
    path = tmp_path / "root"
    path.mkdir()
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(path))
    monkeypatch.delenv("SHEET_MUSIC_INPUT_ROOTS", raising=False)
    return path


@pytest.fixture
def score_file(root):
    path = root / "score.musicxml"
    path.write_text(VALID_MUSICXML, encoding="utf-8")
    return path


@pytest.fixture
def mxl_file(root):
    path = root / "score.mxl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/container.xml", CONTAINER_XML)
        archive.writestr("score.musicxml", VALID_MUSICXML)
    return path


@pytest.fixture
def outside_file(tmp_path):
    folder = tmp_path / "outside"
    folder.mkdir()
    path = folder / "secret.musicxml"
    path.write_text(f"<score-partwise><!-- {SENTINEL} --></score-partwise>", encoding="utf-8")
    return path


@pytest.fixture
def renders(monkeypatch):
    """Mock both renderers; record the MusicXML text each call received."""
    received = []
    fake_image = _fake_render_to_image(TINY_PNG)

    def image(musicxml, page, fmt, dpi, output_path):
        received.append(musicxml)
        return fake_image(musicxml, page, fmt, dpi, output_path)

    def pdf(musicxml, output_path):
        received.append(musicxml)
        return _fake_render_to_pdf(musicxml, output_path)

    monkeypatch.setattr(server, "render_to_image", image)
    monkeypatch.setattr(server, "render_to_pdf", pdf)
    monkeypatch.setattr(server, "detect_backend", lambda: "verovio")
    return received


def _output_args(tool, root):
    return {"output_path": str(root / ("out.pdf" if tool == "render_to_pdf" else "out.png"))}


async def _call_and_clear(tool, arguments):
    """Call ``tool``, then remove its output so the next call can write the same path."""
    result = await call_tool(tool, arguments)
    Path(arguments["output_path"]).unlink(missing_ok=True)
    return result


def _blocks(result):
    return [block.model_dump() for block in result]


def _error(result):
    assert len(result) == 1
    return json.loads(result[0].text)


def _with_client(call):
    async def _go():
        async with Client(app) as client:
            return await call(client)

    return asyncio.run(_go())


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TestSchemas:
    @pytest.mark.parametrize("tool", RENDER_TOOLS)
    async def test_render_tools_take_musicxml_or_musicxml_path(self, tool):
        schema = next(t for t in await list_tools() if t.name == tool).input_schema

        assert {"musicxml", "musicxml_path"} <= set(schema["properties"])
        assert schema["oneOf"] == [{"required": ["musicxml"]}, {"required": ["musicxml_path"]}]
        assert "musicxml" not in schema.get("required", [])

    async def test_describe_score_is_listed(self):
        names = [t.name for t in await list_tools()]

        assert "describe_score" in names

    async def test_capabilities_list_describe_score_and_mxl(self):
        data = json.loads((await call_tool("list_capabilities", {}))[0].text)

        assert "describe_score" in data["tools"]
        assert "mxl" in data["input_formats"]
        assert data["input_parameters"] == ["musicxml", "musicxml_path", "measures"]


# ---------------------------------------------------------------------------
# A path call gives the same result as the inline call
# ---------------------------------------------------------------------------


class TestPathEqualsInline:
    @pytest.mark.parametrize("tool", RENDER_TOOLS)
    async def test_same_content_as_inline(self, tool, root, score_file, renders):
        inline = await _call_and_clear(tool, {"musicxml": VALID_MUSICXML, **_output_args(tool, root)})
        by_path = await _call_and_clear(
            tool, {"musicxml_path": str(score_file), **_output_args(tool, root)}
        )

        assert by_path[0].text == inline[0].text
        assert _blocks(by_path) == _blocks(inline)
        assert [block.type for block in inline][1:] == (
            ["resource_link"] if tool == "render_to_pdf" else ["image", "resource_link"]
        )
        assert renders == [VALID_MUSICXML, VALID_MUSICXML]

    @pytest.mark.parametrize("tool", RENDER_TOOLS)
    async def test_relative_path_resolves_against_output_root(self, tool, root, score_file, renders):
        result = await call_tool(tool, {"musicxml_path": "score.musicxml", **_output_args(tool, root)})

        assert "error" not in json.loads(result[0].text)
        assert renders == [VALID_MUSICXML]

    @pytest.mark.parametrize("tool", RENDER_TOOLS)
    async def test_mxl_path(self, tool, root, mxl_file, renders):
        result = await call_tool(tool, {"musicxml_path": str(mxl_file), **_output_args(tool, root)})

        assert "error" not in json.loads(result[0].text)
        assert renders == [VALID_MUSICXML]

    async def test_mxl_without_container(self, root, renders):
        path = root / "plain.mxl"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("plain.xml", VALID_MUSICXML)

        result = await call_tool("render_to_pdf", {"musicxml_path": str(path), **_output_args("render_to_pdf", root)})

        assert "error" not in json.loads(result[0].text)
        assert renders == [VALID_MUSICXML]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class TestPathErrors:
    @pytest.mark.parametrize("tool", RENDER_TOOLS)
    async def test_absolute_path_outside_roots(self, tool, root, outside_file, renders):
        data = _error(await call_tool(tool, {"musicxml_path": str(outside_file)}))

        assert data["error_code"] == "INVALID_PARAMETER"
        assert SENTINEL not in json.dumps(data)
        assert renders == []

    @pytest.mark.parametrize("tool", RENDER_TOOLS)
    async def test_etc_passwd(self, tool, root, renders):
        data = _error(await call_tool(tool, {"musicxml_path": "/etc/passwd"}))

        assert data["error_code"] == "INVALID_PARAMETER"
        assert "root:" not in json.dumps(data)
        assert renders == []

    @pytest.mark.parametrize("tool", RENDER_TOOLS)
    async def test_parent_traversal(self, tool, root, outside_file, renders):
        # root and outside/ are siblings, so ../outside/secret.musicxml leaves the root.
        data = _error(await call_tool(tool, {"musicxml_path": "../outside/secret.musicxml"}))

        assert data["error_code"] == "INVALID_PARAMETER"
        assert SENTINEL not in json.dumps(data)
        assert renders == []

    @pytest.mark.parametrize("tool", RENDER_TOOLS)
    async def test_relative_parent_path(self, tool, root, renders):
        data = _error(await call_tool(tool, {"musicxml_path": "../x.musicxml"}))

        assert data["error_code"] == "INVALID_PARAMETER"
        assert renders == []

    @pytest.mark.parametrize("tool", RENDER_TOOLS)
    async def test_symlink_pointing_outside(self, tool, root, outside_file, renders):
        link = root / "link.musicxml"
        link.symlink_to(outside_file)

        data = _error(await call_tool(tool, {"musicxml_path": str(link)}))

        assert data["error_code"] == "INVALID_PARAMETER"
        assert SENTINEL not in json.dumps(data)
        assert renders == []

    async def test_missing_file_inside_root(self, root, renders):
        data = _error(await call_tool("render_to_pdf", {"musicxml_path": str(root / "missing.musicxml")}))

        assert data["error_code"] == "FILE_NOT_FOUND"
        assert renders == []

    async def test_wrong_suffix(self, root, renders):
        (root / "notes.txt").write_text(VALID_MUSICXML)

        data = _error(await call_tool("render_to_image", {"musicxml_path": str(root / "notes.txt")}))

        assert data["error_code"] == "INVALID_PARAMETER"
        assert renders == []

    async def test_malformed_file_gives_invalid_input_without_content(self, root, renders):
        (root / "bad.musicxml").write_text(f"<score-partwise>{SENTINEL}", encoding="utf-8")

        data = _error(await call_tool("render_to_pdf", {"musicxml_path": str(root / "bad.musicxml")}))

        assert data["error_code"] == "INVALID_INPUT"
        assert SENTINEL not in json.dumps(data)
        assert renders == []

    @pytest.mark.parametrize("tool", RENDER_TOOLS)
    async def test_direct_call_with_both_is_invalid_parameter(self, tool, root, score_file, renders):
        data = _error(await call_tool(tool, {"musicxml": VALID_MUSICXML, "musicxml_path": str(score_file)}))

        assert data["error_code"] == "INVALID_PARAMETER"
        assert renders == []


class TestThroughProtocol:
    @pytest.mark.parametrize("tool", [*RENDER_TOOLS, "describe_score"])
    def test_both_is_invalid_parameter(self, tool, root, score_file):
        arguments = {"musicxml": VALID_MUSICXML, "musicxml_path": str(score_file)}

        result = _with_client(lambda client: client.call_tool(tool, arguments))

        assert result.is_error
        data = json.loads(result.content[0].text)
        assert data["error_code"] == "INVALID_PARAMETER"
        assert "give only one" in data["error"]
        assert "<score-partwise" not in data["error"]

    @pytest.mark.parametrize("tool", [*RENDER_TOOLS, "describe_score"])
    def test_neither_is_invalid_parameter(self, tool, root):
        result = _with_client(lambda client: client.call_tool(tool, {}))

        assert result.is_error
        data = json.loads(result.content[0].text)
        assert data["error_code"] == "INVALID_PARAMETER"
        assert "musicxml_path" in data["error"]

    def test_path_call_through_the_protocol(self, root, score_file, renders):
        arguments = {"musicxml_path": str(score_file), **_output_args("render_to_pdf", root)}

        result = _with_client(lambda client: client.call_tool("render_to_pdf", arguments))

        assert not result.is_error
        assert renders == [VALID_MUSICXML]

    def test_outside_path_through_the_protocol(self, root, outside_file, renders):
        result = _with_client(
            lambda client: client.call_tool("render_to_image", {"musicxml_path": str(outside_file)})
        )

        data = json.loads(result.content[0].text)
        assert data["error_code"] == "INVALID_PARAMETER"
        assert SENTINEL not in result.content[0].text
        assert renders == []


# ---------------------------------------------------------------------------
# describe_score
# ---------------------------------------------------------------------------


class TestDescribeScore:
    async def test_inline(self, root):
        data = json.loads((await call_tool("describe_score", {"musicxml": VALID_MUSICXML}))[0].text)

        assert [part["id"] for part in data["parts"]] == ["P1"]
        assert data["parts"][0]["name"] == "Soprano"
        assert data["measures"] == 1

    async def test_path(self, root, score_file):
        data = json.loads((await call_tool("describe_score", {"musicxml_path": str(score_file)}))[0].text)

        assert [part["id"] for part in data["parts"]] == ["P1"]
        assert data["time"] == "4/4"

    async def test_mxl_path(self, root, mxl_file):
        data = json.loads((await call_tool("describe_score", {"musicxml_path": str(mxl_file)}))[0].text)

        assert [part["id"] for part in data["parts"]] == ["P1"]

    async def test_outside_path(self, root, outside_file):
        data = _error(await call_tool("describe_score", {"musicxml_path": str(outside_file)}))

        assert data["error_code"] == "INVALID_PARAMETER"
        assert SENTINEL not in json.dumps(data)

    async def test_invalid_inline_is_an_error_result(self, root):
        data = _error(await call_tool("describe_score", {"musicxml": "not xml"}))

        assert data["error_code"] == "INVALID_INPUT"

    def test_through_the_protocol(self, root, score_file):
        result = _with_client(
            lambda client: client.call_tool("describe_score", {"musicxml_path": str(score_file)})
        )

        assert not result.is_error
        assert json.loads(result.content[0].text)["parts"][0]["id"] == "P1"
