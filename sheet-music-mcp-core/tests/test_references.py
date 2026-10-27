"""Score references: schema helpers, client roots, load_score, deliver_score and the shared
describe_score tool (docs/conventions.md, Score References)."""

import asyncio
import copy
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest
from mcp import Client
from mcp.server import Server
from mcp.types import ListRootsResult, Root, TextContent

from sheet_music_mcp_core import references
from sheet_music_mcp_core.errors import ProcessingError
from sheet_music_mcp_core.references import (
    DESCRIBE_SCORE_TOOL,
    RETURN_PROPERTY,
    SCORE_MIME_TYPE,
    client_roots,
    deliver_score,
    describe_score_tool,
    exactly_one,
    load_score,
    score_input_properties,
)
from sheet_music_mcp_core.scores import describe_score, score_summary
from sheet_music_mcp_core.wiring import make_handlers

from .musicxml_fixtures import SATB, UNNAMED

SECRET = "root:x:0:0:secret-line"


@pytest.fixture
def root(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(out))
    for name in ("SHEET_MUSIC_INPUT_ROOTS", "SHEET_MUSIC_INLINE_MAX_BYTES", "SHEET_MUSIC_MAX_SCORE_BYTES"):
        monkeypatch.delenv(name, raising=False)
    return out.resolve()


def _ctx(roots=None, *, declared=True, error=None, delay=0.0):
    """A fake request context whose client answers roots/list with ``roots``."""
    calls = []

    async def list_roots():
        calls.append(1)
        if delay:
            await asyncio.sleep(delay)
        if error is not None:
            raise error
        # Plain objects, so a test can send schemes that mcp's Root model would refuse.
        return SimpleNamespace(roots=[SimpleNamespace(uri=uri) for uri in roots or []])

    capabilities = SimpleNamespace(roots=SimpleNamespace(list_changed=True) if declared else None)
    session = SimpleNamespace(client_capabilities=capabilities, list_roots=list_roots)
    return SimpleNamespace(session=session, calls=calls)


class TestSchemaHelpers:
    def test_score_input_properties(self):
        properties = score_input_properties("musicxml", "musicxml_path", what="the score")

        assert list(properties) == ["musicxml", "musicxml_path"]
        assert properties["musicxml"]["type"] == "string"
        assert properties["musicxml_path"]["type"] == "string"
        assert ".mxl" in properties["musicxml_path"]["description"]
        assert "the score" in properties["musicxml"]["description"]

    def test_score_input_properties_defaults(self):
        assert list(score_input_properties()) == ["musicxml", "musicxml_path"]

    def test_other_names(self):
        properties = score_input_properties("reference_xml", "reference_path", what="the reference score")

        assert list(properties) == ["reference_xml", "reference_path"]
        assert "the reference score" in properties["reference_path"]["description"]

    def test_exactly_one(self):
        assert exactly_one("musicxml", "musicxml_path") == {
            "oneOf": [{"required": ["musicxml"]}, {"required": ["musicxml_path"]}]
        }

    def test_exactly_one_validates_as_intended(self):
        schema = {"type": "object", "properties": score_input_properties(), **exactly_one()}

        jsonschema.validate({"musicxml": "<x/>"}, schema)
        jsonschema.validate({"musicxml_path": "a.musicxml"}, schema)
        for bad in ({}, {"musicxml": "<x/>", "musicxml_path": "a.musicxml"}):
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(bad, schema)

    def test_return_property(self):
        prop = RETURN_PROPERTY["return"]

        assert prop["type"] == "string"
        assert prop["enum"] == ["auto", "path", "inline"]
        assert prop["default"] == "auto"
        assert prop["description"]

    def test_return_property_merges_into_properties(self):
        properties = {**score_input_properties(), **RETURN_PROPERTY}

        assert list(properties) == ["musicxml", "musicxml_path", "return"]


class TestClientRoots:
    async def test_no_context(self):
        assert await client_roots(None) == []

    async def test_declared_roots_become_paths(self, tmp_path):
        ctx = _ctx([(tmp_path / "a b").as_uri(), "file://localhost/srv/scores", "https://example.com/x"])

        assert await client_roots(ctx) == [tmp_path / "a b", Path("/srv/scores")]

    async def test_undeclared_capability_is_not_asked(self):
        ctx = _ctx(["file:///srv"], declared=False)

        assert await client_roots(ctx) == []
        assert ctx.calls == []

    async def test_no_capabilities_at_all(self):
        ctx = SimpleNamespace(session=SimpleNamespace(client_capabilities=None))

        assert await client_roots(ctx) == []

    async def test_failed_request_gives_no_roots(self):
        assert await client_roots(_ctx(error=RuntimeError("boom"))) == []

    async def test_slow_client_times_out(self, monkeypatch):
        monkeypatch.setattr(references, "ROOTS_TIMEOUT_SECONDS", 0.05)

        assert await client_roots(_ctx(["file:///srv"], delay=1.0)) == []

    def test_default_timeout_is_two_seconds(self):
        assert references.ROOTS_TIMEOUT_SECONDS == 2.0

    def test_round_trip_through_a_legacy_client(self, tmp_path):
        """Clients on the initialize handshake (protocol <= 2025-11-25) answer roots/list."""
        assert _roots_seen_by_server(tmp_path, mode="legacy") == [tmp_path]

    def test_modern_connection_has_no_roots(self, tmp_path):
        """mcp 2.x on protocol 2026-07-28 has no back-channel, so roots/list cannot be sent."""
        assert _roots_seen_by_server(tmp_path, mode="auto") == []


def _roots_seen_by_server(tmp_path, *, mode):
    seen = {}

    async def list_tools():
        return [DESCRIBE_SCORE_TOOL]

    async def call_tool(name, arguments, ctx):
        seen["roots"] = await client_roots(ctx)
        return [TextContent(type="text", text="ok")]

    async def answer_roots(context):
        return ListRootsResult(roots=[Root(uri=tmp_path.as_uri())])

    on_list_tools, on_call_tool = make_handlers(list_tools, call_tool, pass_context=True)
    server = Server("test", on_list_tools=on_list_tools, on_call_tool=on_call_tool)

    async def go():
        async with Client(server, mode=mode, list_roots_callback=answer_roots) as client:
            await client.call_tool("describe_score", {"musicxml": "x"})

    asyncio.run(go())
    return seen["roots"]


class TestLoadScore:
    async def test_inline_is_returned_unchanged(self, root):
        assert await load_score({"musicxml": "not even xml"}, None) == "not even xml"

    async def test_path(self, root):
        (root / "a.musicxml").write_text(SATB, encoding="utf-8")

        assert await load_score({"musicxml_path": "a.musicxml"}, None) == SATB

    async def test_mxl_path(self, root):
        with zipfile.ZipFile(root / "a.mxl", "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("a.musicxml", SATB)

        assert await load_score({"musicxml_path": str(root / "a.mxl")}, None) == SATB

    async def test_both(self, root):
        with pytest.raises(ProcessingError) as info:
            await load_score({"musicxml": SATB, "musicxml_path": "a.musicxml"}, None)

        assert info.value.error_code == "INVALID_PARAMETER"
        assert "<score-partwise" not in str(info.value)

    async def test_neither(self, root):
        with pytest.raises(ProcessingError) as info:
            await load_score({}, None)

        assert info.value.error_code == "INVALID_PARAMETER"
        assert "musicxml_path" in str(info.value)

    async def test_custom_parameter_names(self, root):
        (root / "ref.xml").write_text(SATB)

        text = await load_score({"reference_path": "ref.xml"}, None, inline="reference_xml", path="reference_path")

        assert text == SATB

    async def test_path_outside_the_roots(self, root, tmp_path):
        secret = tmp_path / "secret.musicxml"
        secret.write_text(SECRET)

        with pytest.raises(ProcessingError) as info:
            await load_score({"musicxml_path": str(secret)}, None)

        assert info.value.error_code == "INVALID_PARAMETER"
        assert SECRET not in str(info.value) + (info.value.hint or "")

    async def test_client_roots_are_used(self, root, tmp_path):
        shared = tmp_path / "shared"
        shared.mkdir()
        (shared / "s.musicxml").write_text(SATB)
        ctx = _ctx([shared.as_uri()])

        assert await load_score({"musicxml_path": str(shared / "s.musicxml")}, ctx) == SATB
        assert ctx.calls == [1]

    async def test_roots_are_not_asked_for_inline_scores(self, root):
        ctx = _ctx(["file:///srv"])

        await load_score({"musicxml": SATB}, ctx)

        assert ctx.calls == []

    async def test_input_roots_are_used(self, root, tmp_path, monkeypatch):
        shared = tmp_path / "shared"
        shared.mkdir()
        (shared / "s.musicxml").write_text(SATB)
        monkeypatch.setenv("SHEET_MUSIC_INPUT_ROOTS", str(shared))

        assert await load_score({"musicxml_path": str(shared / "s.musicxml")}, None) == SATB

    async def test_size_limit_from_environment(self, root, monkeypatch):
        (root / "a.musicxml").write_text(SATB)
        monkeypatch.setenv("SHEET_MUSIC_MAX_SCORE_BYTES", "100")

        with pytest.raises(ProcessingError) as info:
            await load_score({"musicxml_path": "a.musicxml"}, None)

        assert info.value.error_code == "FILE_TOO_LARGE"

    async def test_malformed_file_names_the_parameter_and_position_only(self, root):
        (root / "bad.musicxml").write_text("<score-partwise>\n<work>secret words</wrong>")

        with pytest.raises(ProcessingError) as info:
            await load_score({"musicxml_path": "bad.musicxml"}, None)

        assert info.value.error_code == "INVALID_INPUT"
        assert str(info.value).startswith("musicxml_path: ")
        assert "line 2" in str(info.value)
        assert "secret" not in str(info.value)

    async def test_file_that_is_not_musicxml(self, root):
        (root / "other.xml").write_text("<html><body>secret</body></html>")

        with pytest.raises(ProcessingError) as info:
            await load_score({"musicxml_path": "other.xml"}, None)

        assert info.value.error_code == "INVALID_INPUT"
        assert "secret" not in str(info.value) and "html" not in str(info.value)

    async def test_path_must_be_a_string(self, root):
        with pytest.raises(ProcessingError) as info:
            await load_score({"musicxml_path": 5}, None)

        assert info.value.error_code == "INVALID_PARAMETER"


class TestDeliverScore:
    def _payload(self, musicxml=SATB):
        return {"status": "ok", "musicxml": musicxml, "parts": 4}

    def test_inline_is_byte_identical_to_the_servers_output(self, root):
        payload = self._payload()

        content = deliver_score(payload, field="musicxml", musicxml=SATB, mode="inline", stem="x")

        assert len(content) == 1
        assert content[0].type == "text"
        assert content[0].text == json.dumps(payload, indent=2)

    def test_auto_at_the_limit_stays_inline(self, root, monkeypatch):
        monkeypatch.setenv("SHEET_MUSIC_INLINE_MAX_BYTES", str(len(SATB.encode("utf-8"))))
        payload = self._payload()

        content = deliver_score(payload, field="musicxml", musicxml=SATB, mode="auto", stem="x")

        assert content[0].text == json.dumps(payload, indent=2)
        assert len(content) == 1
        assert not (root / "scores").exists()

    def test_auto_above_the_limit_writes_a_file(self, root, monkeypatch):
        monkeypatch.setenv("SHEET_MUSIC_INLINE_MAX_BYTES", str(len(SATB.encode("utf-8")) - 1))

        content = deliver_score(self._payload(), field="musicxml", musicxml=SATB, mode="auto", stem="recognized")

        result = json.loads(content[0].text)
        assert "<score-partwise" not in content[0].text
        assert list(result) == ["status", "musicxml_path", "parts", "score_summary"]
        path = Path(result["musicxml_path"])
        assert path.parent == root / "scores"
        assert path.name.startswith("recognized-")
        assert path.read_text(encoding="utf-8") == SATB
        assert result["score_summary"] == score_summary(SATB)
        assert content[1].type == "resource_link"
        assert content[1].mime_type == SCORE_MIME_TYPE == "application/vnd.recordare.musicxml+xml"
        assert str(content[1].uri) == path.as_uri()

    def test_default_limit_is_8192_utf8_bytes(self, root):
        small = SATB + " " * (8192 - len(SATB.encode()))
        large = small + " "

        assert len(deliver_score({"musicxml": small}, field="musicxml", musicxml=small, mode="auto", stem="x")) == 1
        assert len(deliver_score({"musicxml": large}, field="musicxml", musicxml=large, mode="auto", stem="x")) == 2

    def test_limit_counts_utf8_bytes_not_characters(self, root, monkeypatch):
        text = SATB.replace("Test Chorale", "Ärä")
        monkeypatch.setenv("SHEET_MUSIC_INLINE_MAX_BYTES", str(len(text)))  # characters fit, bytes do not

        content = deliver_score({"musicxml": text}, field="musicxml", musicxml=text, mode="auto", stem="x")

        assert "musicxml_path" in json.loads(content[0].text)

    def test_path_mode_always_writes(self, root):
        content = deliver_score(self._payload(), field="musicxml", musicxml=SATB, mode="path", stem="x")

        assert "musicxml_path" in json.loads(content[0].text)
        assert len(content) == 2

    def test_inline_mode_never_writes(self, root, monkeypatch):
        monkeypatch.setenv("SHEET_MUSIC_INLINE_MAX_BYTES", "10")

        content = deliver_score(self._payload(), field="musicxml", musicxml=SATB, mode="inline", stem="x")

        assert json.loads(content[0].text)["musicxml"] == SATB
        assert not (root / "scores").exists()

    def test_payload_is_not_mutated(self, root):
        payload = self._payload()
        before = copy.deepcopy(payload)

        deliver_score(payload, field="musicxml", musicxml=SATB, mode="path", stem="x")

        assert payload == before

    def test_text_defaults_to_the_payload_field(self, root):
        content = deliver_score(self._payload(), field="musicxml", mode="path", stem="x")

        assert Path(json.loads(content[0].text)["musicxml_path"]).read_text() == SATB

    def test_payload_without_the_field_is_returned_inline(self, root):
        error = {"error": "Recognition failed", "error_code": "PROCESSING_FAILED"}

        content = deliver_score(error, field="musicxml", mode="path", stem="x")

        assert content[0].text == json.dumps(error, indent=2)
        assert len(content) == 1

    def test_unknown_mode(self, root):
        with pytest.raises(ProcessingError) as info:
            deliver_score(self._payload(), field="musicxml", musicxml=SATB, mode="file", stem="x")

        assert info.value.error_code == "INVALID_PARAMETER"
        assert info.value.choices == ["auto", "path", "inline"]

    def test_two_fields_are_written_together(self, root, monkeypatch):
        monkeypatch.setenv("SHEET_MUSIC_INLINE_MAX_BYTES", str(len(UNNAMED.encode()) + 10))
        payload = {"reference_annotated": UNNAMED, "target_annotated": SATB, "changes": 3}

        content = deliver_score(
            payload, field=("reference_annotated", "target_annotated"), mode="auto", stem="annotated"
        )

        result = json.loads(content[0].text)
        assert list(result) == ["reference_annotated_path", "target_annotated_path", "changes", "score_summary"]
        assert Path(result["reference_annotated_path"]).read_text() == UNNAMED
        assert Path(result["target_annotated_path"]).read_text() == SATB
        assert Path(result["reference_annotated_path"]).name.startswith("annotated-reference_annotated-")
        assert Path(result["target_annotated_path"]).name.startswith("annotated-target_annotated-")
        assert result["score_summary"] == {
            "reference_annotated": score_summary(UNNAMED),
            "target_annotated": score_summary(SATB),
        }
        assert [block.type for block in content] == ["text", "resource_link", "resource_link"]

    def test_two_fields_both_small_stay_inline(self, root):
        payload = {"reference_annotated": UNNAMED, "target_annotated": SATB}

        content = deliver_score(payload, field=("reference_annotated", "target_annotated"), mode="auto", stem="a")

        assert content[0].text == json.dumps(payload, indent=2)

    def test_two_fields_with_explicit_texts(self, root):
        payload = {"a": "short", "b": "short"}

        content = deliver_score(payload, field=("a", "b"), musicxml=(SATB, UNNAMED), mode="path", stem="s")

        result = json.loads(content[0].text)
        assert Path(result["a_path"]).read_text() == SATB
        assert Path(result["b_path"]).read_text() == UNNAMED

    def test_unparseable_score_is_still_written_without_summary(self, root):
        content = deliver_score({"musicxml": "<broken"}, field="musicxml", mode="path", stem="x")

        result = json.loads(content[0].text)
        assert Path(result["musicxml_path"]).read_text() == "<broken"
        assert result["score_summary"] is None


class TestDescribeScoreTool:
    def test_tool_definition(self):
        tool = DESCRIBE_SCORE_TOOL

        assert tool.name == "describe_score"
        assert tool.title == "Describe score"
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.open_world_hint is False
        assert "does not return the score" in tool.description
        schema = tool.input_schema
        assert set(schema["properties"]) == {"musicxml", "musicxml_path"}
        assert schema["oneOf"] == exactly_one()["oneOf"]

    async def test_describes_an_inline_score(self, root):
        [block] = await describe_score_tool({"musicxml": SATB}, None)

        assert block.text == json.dumps(describe_score(SATB), indent=2)

    async def test_describes_a_path(self, root):
        (root / "a.musicxml").write_text(SATB)

        [block] = await describe_score_tool({"musicxml_path": "a.musicxml"}, None)

        assert json.loads(block.text)["title"] == "Test Chorale"

    async def test_invalid_inline_score(self, root):
        with pytest.raises(ProcessingError) as info:
            await describe_score_tool({"musicxml": "<html/>"}, None)

        assert info.value.error_code == "INVALID_INPUT"

    def test_through_mcp_client(self, root):
        (root / "a.musicxml").write_text(SATB)

        async def list_tools():
            return [DESCRIBE_SCORE_TOOL]

        async def call_tool(name, arguments, ctx):
            return await describe_score_tool(arguments, ctx)

        on_list_tools, on_call_tool = make_handlers(list_tools, call_tool, pass_context=True)
        server = Server("test", on_list_tools=on_list_tools, on_call_tool=on_call_tool)

        async def go():
            async with Client(server) as client:
                listed = await client.list_tools()
                by_path = await client.call_tool("describe_score", {"musicxml_path": "a.musicxml"})
                inline = await client.call_tool("describe_score", {"musicxml": SATB})
                both = await client.call_tool("describe_score", {"musicxml": SATB, "musicxml_path": "a.musicxml"})
                bad = await client.call_tool("describe_score", {"musicxml": "<html/>"})
                return listed, by_path, inline, both, bad

        listed, by_path, inline, both, bad = asyncio.run(go())

        assert [t.name for t in listed.tools] == ["describe_score"]
        assert not by_path.is_error
        assert by_path.content[0].text == inline.content[0].text == json.dumps(describe_score(SATB), indent=2)
        assert both.is_error
        assert json.loads(both.content[0].text) == {
            "error": "Input validation error: give only one of these parameters: 'musicxml', 'musicxml_path'",
            "error_code": "INVALID_PARAMETER",
        }
        assert bad.is_error
        assert json.loads(bad.content[0].text)["error_code"] == "INVALID_INPUT"
