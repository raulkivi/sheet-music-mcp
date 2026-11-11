"""The apply_abc_edit tool: schema, score references, delivery and error envelopes."""

import asyncio
import json

import pytest
from mcp import Client

from musicxml_abc_mcp.server import app, call_tool, call_tool_result, list_tools

from .edit_fixtures import QUARTERS_ABC, SCORE, part_text


@pytest.fixture
def root(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(out))
    for name in ("SHEET_MUSIC_INPUT_ROOTS", "SHEET_MUSIC_INLINE_MAX_BYTES", "SHEET_MUSIC_MAX_SCORE_BYTES"):
        monkeypatch.delenv(name, raising=False)
    return out.resolve()


def _tool():
    return next(t for t in asyncio.run(list_tools()) if t.name == "apply_abc_edit")


def _with_client(call):
    async def _go():
        async with Client(app) as client:
            return await call(client)

    return asyncio.run(_go())


def _args(**overrides) -> dict:
    return {"musicxml": SCORE, "part": "Alto", "measures": [2, 3], "abc": QUARTERS_ABC, **overrides}


def _written(root) -> list:
    folder = root / "scores"
    return sorted(folder.iterdir()) if folder.exists() else []


class TestSchema:
    def test_inputs(self):
        schema = _tool().input_schema

        assert {"musicxml", "musicxml_path", "part", "measures", "abc", "return"} <= set(schema["properties"])
        assert schema["oneOf"] == [{"required": ["musicxml"]}, {"required": ["musicxml_path"]}]
        assert set(schema["required"]) == {"part", "measures", "abc"}
        assert schema["properties"]["return"]["enum"] == ["auto", "path", "inline"]
        assert schema["properties"]["measures"]["minItems"] == 2

    def test_listed_in_capabilities(self):
        payload = json.loads(asyncio.run(call_tool("list_capabilities", {}))[0].text)

        assert "apply_abc_edit" in payload["tools"]


class TestResult:
    async def test_inline_result(self, root):
        result = await call_tool_result("apply_abc_edit", _args(**{"return": "inline"}))
        payload = json.loads(result.content[0].text)

        assert not result.is_error
        assert payload["part"] == "P2"
        assert payload["measures"] == [2, 3]
        assert payload["measures_replaced"] == 2
        assert part_text(SCORE, "P1") in payload["musicxml"]
        assert {w["code"] for w in payload["warnings"]} >= {"DYNAMICS_DROPPED", "LYRICS_DROPPED"}
        assert _written(root) == []

    async def test_path_result(self, root):
        result = await call_tool_result("apply_abc_edit", _args(**{"return": "path"}))
        payload = json.loads(result.content[0].text)

        assert "musicxml" not in payload
        [written] = _written(root)
        assert payload["musicxml_path"] == str(written)
        assert payload["score_summary"]["measures"] == 4
        assert part_text(SCORE, "P3") in written.read_text(encoding="utf-8")
        assert result.content[1].uri.startswith("file://")

    async def test_structured_content_has_no_score(self, root):
        result = await call_tool_result("apply_abc_edit", _args(**{"return": "inline"}))

        structured = result.structured_content
        assert structured["part"] == "P2"
        assert structured["measures"] == [2, 3]
        assert structured["measures_replaced"] == 2
        assert structured["delivery"] == "inline"
        assert structured["musicxml_bytes"] > 0
        assert "musicxml" not in structured
        assert structured["warnings"] == json.loads(result.content[0].text)["warnings"]

    def test_through_the_protocol(self, root):
        result = _with_client(lambda c: c.call_tool("apply_abc_edit", _args(**{"return": "inline"})))

        assert not result.is_error
        assert json.loads(result.content[0].text)["part"] == "P2"


class TestScoreReferences:
    async def test_reads_a_path_inside_the_root(self, root):
        source = root / "kyrie.musicxml"
        source.write_text(SCORE, encoding="utf-8")
        args = _args(**{"return": "inline"})
        del args["musicxml"]

        result = await call_tool_result("apply_abc_edit", {**args, "musicxml_path": str(source)})

        assert not result.is_error
        assert part_text(SCORE, "P1") in json.loads(result.content[0].text)["musicxml"]

    async def test_refuses_a_path_outside_the_roots(self, root, tmp_path):
        outside = tmp_path / "elsewhere.musicxml"
        outside.write_text(SCORE, encoding="utf-8")
        args = _args()
        del args["musicxml"]

        result = await call_tool_result("apply_abc_edit", {**args, "musicxml_path": str(outside)})

        assert result.is_error
        assert json.loads(result.content[0].text)["error_code"] == "INVALID_PARAMETER"


class TestErrors:
    async def _error(self, **overrides) -> dict:
        result = await call_tool_result("apply_abc_edit", _args(**overrides))
        assert result.is_error
        return json.loads(result.content[0].text)

    async def test_reversed_bars(self, root):
        payload = await self._error(measures=[3, 2])

        assert payload["error_code"] == "INVALID_PARAMETER"
        assert "1–4" in payload["hint"]

    async def test_bars_outside_the_score(self, root):
        payload = await self._error(measures=[3, 9])

        assert payload["error_code"] == "INVALID_PARAMETER"
        assert "hint" in payload

    async def test_unknown_part(self, root):
        payload = await self._error(part="Tenor")

        assert payload["error_code"] == "INVALID_PARAMETER"
        assert "choices" in payload

    async def test_bad_abc_writes_nothing(self, root):
        payload = await self._error(abc="X:1\nK:C\n|||[[[ ((( %%% ", **{"return": "path"})

        assert payload["error_code"] == "INVALID_INPUT"
        assert _written(root) == []

    async def test_not_musicxml(self, root):
        payload = await self._error(musicxml="hello")

        assert payload["error_code"] == "INVALID_INPUT"

    def test_missing_abc_is_a_validation_error(self, root):
        args = _args()
        del args["abc"]

        result = _with_client(lambda c: c.call_tool("apply_abc_edit", args))

        assert result.is_error
