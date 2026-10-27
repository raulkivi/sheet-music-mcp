"""Score references (docs/conventions.md, Score References; UX Wave 2).

recognize_sheet and recognize_sheets take ``return: auto | path | inline``: large results come back
as a ``musicxml_path`` plus a ``score_summary`` instead of the MusicXML text. recognize_sheet_to_file
adds a ``score_summary`` next to its ``output_path``. The OMR engines are replaced by fakes.
"""

import ast
import asyncio
import json
from pathlib import Path

import pytest
from mcp import Client
from sheet_music_mcp_core import paths as core_paths

import omr_mcp.server as srv
from omr_mcp import utils

MUSICXML_MIME = "application/vnd.recordare.musicxml+xml"


@pytest.fixture(autouse=True)
def output_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
    monkeypatch.delenv("SHEET_MUSIC_INLINE_MAX_BYTES", raising=False)
    return tmp_path


def _score(measures: int) -> str:
    """A one-part MusicXML score; about 150 bytes per measure."""
    first = (
        '<measure number="1"><attributes><divisions>1</divisions><key><fifths>0</fifths></key>'
        "<time><beats>4</beats><beat-type>4</beat-type></time>"
        "<clef><sign>G</sign><line>2</line></clef></attributes>"
        "<note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration>"
        "<type>whole</type></note></measure>"
    )
    rest = "".join(
        f'<measure number="{number}"><note><pitch><step>G</step><octave>4</octave></pitch>'
        "<duration>4</duration><type>whole</type></note></measure>"
        for number in range(2, measures + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<score-partwise version="4.0">'
        '<part-list><score-part id="P1"><part-name>Soprano</part-name></score-part></part-list>'
        f'<part id="P1">{first}{rest}</part></score-partwise>'
    )


LARGE = _score(100)
SMALL = _score(2)


def test_fixture_sizes():
    assert len(LARGE.encode("utf-8")) > 8192
    assert len(SMALL.encode("utf-8")) < 8192


def _engine_result(musicxml: str, **metadata) -> dict:
    return {
        "musicxml": musicxml,
        "metadata": {"source": "page.png", "measures": 100, "engine": "oemer", **metadata},
        "warnings": ["low resolution; recognition may fail"],
    }


# Each producer: (tool name, engine function patched on the server, base arguments).
PRODUCERS = [
    ("recognize_sheet", "recognize_image", {"image": "page.png", "format": "path"}),
    ("recognize_sheets", "recognize_images", {"images": ["page1.png", "page2.png"]}),
]


@pytest.fixture(params=PRODUCERS, ids=[name for name, _, _ in PRODUCERS])
def producer(request, monkeypatch):
    """Patch the tool's engine call to return what ``producer.returns`` holds; yield a caller."""
    name, engine_function, base_arguments = request.param

    class Producer:
        returns = _engine_result(SMALL)

        def call(self, **extra):
            return asyncio.run(srv.call_tool(name, {**base_arguments, **extra}))

    current = Producer()
    monkeypatch.setattr(srv, engine_function, lambda *args, **kwargs: json.loads(json.dumps(current.returns)))
    return current


def _payload(result):
    return json.loads(result[0].text)


class TestProducerAuto:
    def test_large_result_becomes_a_path_and_summary(self, producer, output_root):
        producer.returns = _engine_result(LARGE)

        result = producer.call()

        assert "<score-partwise" not in result[0].text
        payload = _payload(result)
        assert "musicxml" not in payload
        written = Path(payload["musicxml_path"])
        assert written.parent == (output_root / "scores").resolve()
        assert written.name.startswith("recognized-")
        assert written.suffix == ".musicxml"
        assert written.read_text(encoding="utf-8") == LARGE
        summary = payload["score_summary"]
        assert summary["measures"] == 100
        assert summary["parts"] == [{"id": "P1", "name": "Soprano", "range": {"low": "C4", "high": "G4"}}]
        # The rest of the engine result is kept.
        assert payload["metadata"] == producer.returns["metadata"]
        assert payload["warnings"] == producer.returns["warnings"]

    def test_large_result_appends_a_resource_link(self, producer):
        producer.returns = _engine_result(LARGE)

        result = producer.call()

        assert [block.type for block in result] == ["text", "resource_link"]
        link = result[1]
        assert link.mime_type == MUSICXML_MIME
        assert link.uri == Path(_payload(result)["musicxml_path"]).resolve().as_uri()

    def test_small_result_stays_inline_and_unchanged(self, producer, output_root):
        producer.returns = _engine_result(SMALL)

        result = producer.call()

        assert len(result) == 1
        assert result[0].text == json.dumps(producer.returns, indent=2)
        assert not (output_root / "scores").exists()

    def test_explicit_auto_equals_omitted(self, producer):
        producer.returns = _engine_result(SMALL)

        assert producer.call(**{"return": "auto"})[0].text == producer.call()[0].text

    def test_limit_follows_the_environment(self, producer, monkeypatch):
        monkeypatch.setenv("SHEET_MUSIC_INLINE_MAX_BYTES", "100")
        producer.returns = _engine_result(SMALL)

        assert "musicxml_path" in _payload(producer.call())


class TestProducerModes:
    def test_path_always_writes(self, producer):
        producer.returns = _engine_result(SMALL)

        result = producer.call(**{"return": "path"})

        payload = _payload(result)
        assert "musicxml" not in payload
        assert Path(payload["musicxml_path"]).read_text(encoding="utf-8") == SMALL
        assert payload["score_summary"]["measures"] == 2
        assert [block.type for block in result] == ["text", "resource_link"]

    def test_inline_keeps_a_large_result_inline(self, producer, output_root):
        producer.returns = _engine_result(LARGE)

        result = producer.call(**{"return": "inline"})

        assert len(result) == 1
        assert result[0].text == json.dumps(producer.returns, indent=2)
        assert not (output_root / "scores").exists()

    def test_engine_error_dict_is_unchanged_in_path_mode(self, producer, output_root):
        producer.returns = {"error": "File not found: page.png", "error_code": "FILE_NOT_FOUND"}

        result = producer.call(**{"return": "path"})

        assert len(result) == 1
        assert result[0].text == json.dumps(producer.returns, indent=2)
        assert not (output_root / "scores").exists()

    def test_unknown_mode_is_an_invalid_parameter(self, producer):
        producer.returns = _engine_result(SMALL)

        payload = _payload(producer.call(**{"return": "zip"}))

        assert payload["error_code"] == "INVALID_PARAMETER"
        assert payload["choices"] == ["auto", "path", "inline"]


class TestProducerSchema:
    @pytest.mark.parametrize("name", ["recognize_sheet", "recognize_sheets"])
    def test_return_property(self, name):
        tool = next(t for t in asyncio.run(srv.list_tools()) if t.name == name)

        prop = tool.input_schema["properties"]["return"]
        assert prop["enum"] == ["auto", "path", "inline"]
        assert prop["default"] == "auto"
        assert "return" not in tool.input_schema["required"]
        assert "musicxml_path" in tool.description

    def test_to_file_takes_no_return(self):
        tool = next(t for t in asyncio.run(srv.list_tools()) if t.name == "recognize_sheet_to_file")

        assert "return" not in tool.input_schema["properties"]

    def test_protocol_rejects_an_unknown_mode(self):
        async def _go():
            async with Client(srv.app) as client:
                return await client.call_tool("recognize_sheet", {"image": "page.png", "return": "zip"})

        result = asyncio.run(_go())

        assert result.is_error
        assert json.loads(result.content[0].text)["error_code"] == "INVALID_PARAMETER"

    def test_protocol_returns_a_path_for_a_large_result(self, monkeypatch):
        monkeypatch.setattr(srv, "recognize_image", lambda *args, **kwargs: _engine_result(LARGE))

        async def _go():
            async with Client(srv.app) as client:
                return await client.call_tool("recognize_sheet", {"image": "page.png", "format": "path"})

        result = asyncio.run(_go())

        assert not result.is_error
        assert "musicxml_path" in json.loads(result.content[0].text)
        assert result.content[1].type == "resource_link"


class TestRecognizeSheetToFileSummary:
    def _fake(self, out: Path, text: str | None):
        def fake(input_path, output_path, engine="oemer"):
            if text is not None:
                out.write_text(text, encoding="utf-8")
            return {"output_path": str(out), "metadata": {"source": input_path, "engine": engine}}

        return fake

    def _call(self, output_root):
        return asyncio.run(srv.call_tool("recognize_sheet_to_file", {"input_path": str(output_root / "page.png")}))

    def test_adds_score_summary_and_keeps_the_link(self, monkeypatch, output_root):
        out = output_root / "score.musicxml"
        monkeypatch.setattr(srv, "recognize_image_to_file", self._fake(out, LARGE))

        result = self._call(output_root)

        payload = _payload(result)
        assert payload["output_path"] == str(out)
        assert payload["score_summary"]["measures"] == 100
        assert payload["score_summary"]["parts"][0]["id"] == "P1"
        assert "<score-partwise" not in result[0].text
        assert [block.type for block in result] == ["text", "resource_link"]
        assert result[1].uri == out.resolve().as_uri()

    def test_unparsable_output_gives_a_null_summary(self, monkeypatch, output_root):
        out = output_root / "score.musicxml"
        monkeypatch.setattr(srv, "recognize_image_to_file", self._fake(out, "<not-closed>"))

        payload = _payload(self._call(output_root))

        assert payload["score_summary"] is None

    def test_missing_output_gives_a_null_summary(self, monkeypatch, output_root):
        out = output_root / "never_written.musicxml"
        monkeypatch.setattr(srv, "recognize_image_to_file", self._fake(out, None))

        result = self._call(output_root)

        assert _payload(result)["score_summary"] is None
        assert len(result) == 1

    def test_error_dict_gets_no_summary(self, monkeypatch, output_root):
        def fake(input_path, output_path, engine="oemer"):
            return {"error": "File not found: page.png", "error_code": "FILE_NOT_FOUND"}

        monkeypatch.setattr(srv, "recognize_image_to_file", fake)

        payload = _payload(self._call(output_root))

        assert "score_summary" not in payload


def test_confine_output_path_is_the_core_one():
    assert utils.confine_output_path is core_paths.confine_output_path


def test_engine_imports_no_mcp_modules_of_the_core():
    source = (Path(srv.__file__).parent / "omr_engine.py").read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)

    forbidden = {"mcp", *(f"sheet_music_mcp_core.{name}" for name in ("references", "content", "wiring"))}
    assert not {name for name in imported if name.split(".")[0] == "mcp" or name in forbidden}
