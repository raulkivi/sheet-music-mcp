"""``warnings[]`` on recognize_sheet, recognize_sheets and recognize_sheet_to_file
(docs/conventions.md, Warnings): PARTS_FEWER_THAN_STAVES and EMPTY_MEASURE."""

import asyncio
import json

import jsonschema
import pytest

import omr_mcp.server as srv
from omr_mcp.recognition_warnings import build_warnings
from omr_mcp.server import call_tool_result, list_tools

from .test_recognition_review import _ctx, _page_image

@pytest.fixture(autouse=True)
def output_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path / "out"))
    return tmp_path / "out"


NOTE = "<note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration></note>"
REST = "<note><rest/><duration>4</duration></note>"


def _xml(*parts):
    """parts: one list of measure bodies per part, P1, P2, ..."""
    body = ""
    for p, measures in enumerate(parts, 1):
        inner = "".join(f'<measure number="{n}">{m}</measure>' for n, m in enumerate(measures, 1))
        body += f'<part id="P{p}">{inner}</part>'
    return f"<score-partwise>{body}</score-partwise>"


def _result(xml, staves=1, **metadata):
    return {"musicxml": xml, "metadata": {"source": "x.png", "staves_detected": staves, "measures": 2,
                                          "processing_time_ms": 1, "engine": "oemer", **metadata}}


class TestBuildWarnings:
    def test_clean_score_gives_an_empty_list(self):
        assert build_warnings(_xml([NOTE, REST]), parts=1, staves_on_page=1) == []

    def test_parts_fewer_than_staves(self):
        assert build_warnings(_xml([NOTE]), parts=1, staves_on_page=4) == [
            {"code": "PARTS_FEWER_THAN_STAVES", "severity": "warning",
             "message": "1 part recognised but 4 staves found on the page; voices may be merged"}
        ]

    @pytest.mark.parametrize("staves", [None, 0, 1])
    def test_no_warning_when_the_page_count_is_unknown_or_not_larger(self, staves):
        assert build_warnings(_xml([NOTE]), parts=1, staves_on_page=staves) == []

    def test_empty_measure_names_the_bar_and_the_part(self):
        assert build_warnings(_xml([NOTE, NOTE], [NOTE, ""]), parts=2, staves_on_page=None) == [
            {"code": "EMPTY_MEASURE", "severity": "warning",
             "message": "Measure 2 has no notes or rests", "measure": 2, "part": "P2"}
        ]

    def test_a_rest_is_not_empty(self):
        assert build_warnings(_xml([REST]), parts=1, staves_on_page=None) == []

    def test_unparseable_score_adds_no_empty_measure_warnings(self):
        assert build_warnings("not xml", parts=1, staves_on_page=None) == []

    def test_a_non_numeric_measure_number_omits_the_measure_field(self):
        xml = '<score-partwise><part id="P1"><measure number="X1"/></part></score-partwise>'
        (item,) = build_warnings(xml, parts=1, staves_on_page=None)
        assert item["code"] == "EMPTY_MEASURE" and "measure" not in item and item["part"] == "P1"

    def test_engine_strings_become_items_and_are_not_dropped(self):
        items = build_warnings(_xml([NOTE]), parts=1, staves_on_page=None, engine_notes=["Page 2: low resolution"])
        assert items == [{"code": "LOW_RESOLUTION", "severity": "warning", "message": "Page 2: low resolution"}]


class TestTools:
    def _stub(self, monkeypatch, result):
        monkeypatch.setattr(srv, "recognize_image", lambda path, engine="oemer": json.loads(json.dumps(result)))

    def _call(self, tmp_path, staves_on_page=0, **args):
        image = str(_page_image(tmp_path, staves=staves_on_page))
        return asyncio.run(call_tool_result("recognize_sheet", {"image": image, **args}))

    def test_clean_fixture_has_an_empty_array_in_both_places(self, tmp_path, monkeypatch):
        self._stub(monkeypatch, _result(_xml([NOTE, NOTE])))
        result = self._call(tmp_path, staves_on_page=1)
        assert json.loads(result.content[0].text)["warnings"] == []
        assert result.structured_content["warnings"] == []

    def test_empty_array_also_without_an_app_client(self, tmp_path, monkeypatch):
        self._stub(monkeypatch, _result(_xml([NOTE])))
        image = str(_page_image(tmp_path))
        result = asyncio.run(call_tool_result("recognize_sheet", {"image": image}, _ctx(ui=False)))
        assert json.loads(result.content[0].text)["warnings"] == []
        assert result.structured_content["warnings"] == []

    @pytest.mark.parametrize("ui", [True, False])
    def test_parts_fewer_than_staves_reaches_text_and_structured(self, tmp_path, monkeypatch, ui):
        self._stub(monkeypatch, _result(_xml([NOTE]), staves=1))
        image = str(_page_image(tmp_path, staves=4))
        result = asyncio.run(call_tool_result("recognize_sheet", {"image": image}, _ctx(ui=ui)))
        codes = [w["code"] for w in json.loads(result.content[0].text)["warnings"]]
        assert codes == ["PARTS_FEWER_THAN_STAVES"]
        assert result.structured_content["warnings"] == json.loads(result.content[0].text)["warnings"]

    def test_the_path_mode_text_carries_warnings_too(self, tmp_path, monkeypatch):
        self._stub(monkeypatch, _result(_xml([NOTE], [NOTE, ""]), staves=2))
        result = self._call(tmp_path, staves_on_page=2, **{"return": "path"})
        payload = json.loads(result.content[0].text)
        assert [w["code"] for w in payload["warnings"]] == ["EMPTY_MEASURE"]
        assert "musicxml_path" in payload

    def test_structured_content_validates_against_the_output_schema(self, tmp_path, monkeypatch):
        self._stub(monkeypatch, _result(_xml([NOTE, ""]), staves=1))
        result = self._call(tmp_path, staves_on_page=3)
        tool = {t.name: t for t in asyncio.run(list_tools())}["recognize_sheet"]
        jsonschema.validate(result.structured_content, tool.output_schema)
        assert len(result.structured_content["warnings"]) == 2

    def test_recognize_sheets_reports_them(self, tmp_path, monkeypatch):
        monkeypatch.setattr(srv, "recognize_images", lambda paths, engine="oemer": {
            "musicxml": _xml([NOTE]), "metadata": {"page_count": 2, "staves_detected": 1, "measures": 1,
                                                   "processing_time_ms": 1, "engine": engine}})
        images = [str(_page_image(tmp_path, f"p{i}.png", staves=2)) for i in (1, 2)]
        result = asyncio.run(call_tool_result("recognize_sheets", {"images": images}))
        assert [w["code"] for w in result.structured_content["warnings"]] == ["PARTS_FEWER_THAN_STAVES"]

    def test_to_file_has_warnings_in_the_text(self, tmp_path, monkeypatch):
        out = tmp_path / "out.musicxml"
        src = _page_image(tmp_path, staves=3)

        def fake(input_path, output_path, engine="oemer"):
            out.write_text(_xml([NOTE, ""]), encoding="utf-8")
            return {"output_path": str(out), "metadata": {"staves_detected": 1, "measures": 2,
                                                          "processing_time_ms": 1, "engine": engine}}

        monkeypatch.setattr(srv, "recognize_image_to_file", fake)
        result = asyncio.run(call_tool_result("recognize_sheet_to_file", {"input_path": str(src)}))
        codes = [w["code"] for w in json.loads(result.content[0].text)["warnings"]]
        assert codes == ["PARTS_FEWER_THAN_STAVES", "EMPTY_MEASURE"]

    def test_errors_keep_the_envelope_without_warnings(self, tmp_path, monkeypatch):
        self._stub(monkeypatch, {"error": "File not found: x", "error_code": "FILE_NOT_FOUND"})
        result = self._call(tmp_path)
        assert result.is_error and "warnings" not in json.loads(result.content[0].text)
