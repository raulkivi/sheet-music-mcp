"""MCP protocol and tool schema tests for comparer-mcp."""

import json
from pathlib import Path

import pytest
from music21 import converter, meter, note, stream
from music21.musicxml.m21ToXml import GeneralObjectExporter

from comparer_mcp.server import call_tool, list_tools

_SATB_MXL_DIR = Path(__file__).parents[2] / "omr-mcp" / "test_samples" / "pdmx_satb_samples" / "mxl"


def _mxl_to_musicxml(mxl_path) -> str:
    """Load a compressed .mxl fixture and re-export it as a MusicXML string
    (the new report/annotation tools take xml strings, not file paths)."""
    return GeneralObjectExporter(converter.parse(str(mxl_path))).parse().decode("utf-8")

_TOOL_NAMES = {
    "compare_musicxml",
    "compare_musicxml_files",
    "quick_similarity",
    "list_changes",
    "generate_comparison_report",
    "export_annotated_musicxml",
    "list_capabilities",
    "health_check",
}


def _score_xml(parts: dict) -> str:
    """Build a MusicXML string from {part_name: [(pitch_or_None, quarterLength), ...]}."""
    score = stream.Score()
    for part_name, notes in parts.items():
        part = stream.Part(id=part_name)
        part.partName = part_name
        part.append(meter.TimeSignature("4/4"))
        for pitch_name, ql in notes:
            if pitch_name is None:
                part.append(note.Rest(quarterLength=ql))
            else:
                part.append(note.Note(pitch_name, quarterLength=ql))
        score.insert(0, part)
    score.makeMeasures(inPlace=True)
    return GeneralObjectExporter(score).parse().decode("utf-8")


SOPRANO_NOTES = [("C4", 1.0), ("D4", 1.0), ("E4", 1.0), ("F4", 1.0)]
REFERENCE_XML = _score_xml({"Soprano": SOPRANO_NOTES, "Alto": SOPRANO_NOTES})
TARGET_XML = _score_xml(
    {"Soprano": [("C4", 1.0), ("G4", 1.0), ("E4", 1.0), ("F4", 1.0)], "Alto": SOPRANO_NOTES}
)


class TestListTools:
    async def test_returns_eight_tools(self):
        tools = await list_tools()
        names = {t.name for t in tools}
        assert names == _TOOL_NAMES

    async def test_compare_musicxml_schema(self):
        tools = await list_tools()
        tool = next(t for t in tools if t.name == "compare_musicxml")
        schema = tool.input_schema
        assert set(schema["required"]) == {"reference_xml", "target_xml"}
        assert "options" in schema["properties"]
        assert "options" not in schema["required"]

    async def test_compare_musicxml_files_schema(self):
        tools = await list_tools()
        tool = next(t for t in tools if t.name == "compare_musicxml_files")
        schema = tool.input_schema
        assert set(schema["required"]) == {"reference_path", "target_path"}

    async def test_quick_similarity_schema(self):
        tools = await list_tools()
        tool = next(t for t in tools if t.name == "quick_similarity")
        schema = tool.input_schema
        assert set(schema["required"]) == {"reference_xml", "target_xml"}

    async def test_list_changes_schema(self):
        tools = await list_tools()
        tool = next(t for t in tools if t.name == "list_changes")
        schema = tool.input_schema
        assert set(schema["required"]) == {"reference_xml", "target_xml"}
        assert "part" in schema["properties"]
        assert "measure_range" in schema["properties"]
        assert "part" not in schema["required"]
        assert "measure_range" not in schema["required"]

    async def test_generate_comparison_report_schema(self):
        tools = await list_tools()
        tool = next(t for t in tools if t.name == "generate_comparison_report")
        schema = tool.input_schema
        assert set(schema["required"]) == {"reference_xml", "target_xml"}
        assert "options" in schema["properties"]

    async def test_export_annotated_musicxml_schema(self):
        tools = await list_tools()
        tool = next(t for t in tools if t.name == "export_annotated_musicxml")
        schema = tool.input_schema
        assert set(schema["required"]) == {"reference_xml", "target_xml"}
        assert "options" in schema["properties"]

    async def test_list_capabilities_schema(self):
        tools = await list_tools()
        tool = next(t for t in tools if t.name == "list_capabilities")
        assert tool.input_schema["required"] == []

    async def test_health_check_schema(self):
        tools = await list_tools()
        tool = next(t for t in tools if t.name == "health_check")
        assert tool.input_schema["required"] == []


class TestCallToolListCapabilities:
    async def test_structure(self):
        result = await call_tool("list_capabilities", {})
        payload = json.loads(result[0].text)
        assert payload["server"] == "comparer-mcp"
        assert payload["input_formats"] == ["musicxml"]
        assert payload["output_formats"] == ["json"]
        assert set(payload["tools"]) == _TOOL_NAMES
        assert payload["backend"] == "music21"
        assert "backend_version" in payload


class TestCallToolHealthCheck:
    async def test_returns_ok_status(self):
        result = await call_tool("health_check", {})
        payload = json.loads(result[0].text)
        assert payload["status"] == "ok"
        assert payload["checks"]["music21"]["ok"] is True
        assert payload["checks"]["self_compare"]["ok"] is True
        assert "music21" in payload["summary"]


class TestCallToolCompareMusicxml:
    async def test_valid_returns_full_result(self):
        result = await call_tool(
            "compare_musicxml", {"reference_xml": REFERENCE_XML, "target_xml": TARGET_XML}
        )
        payload = json.loads(result[0].text)
        assert "similarity_score" in payload
        assert "summary" in payload
        assert "part_diffs" in payload
        assert payload["summary"]["notes_pitch_changed"] >= 1

    async def test_identical_scores_similarity_one(self):
        result = await call_tool(
            "compare_musicxml", {"reference_xml": REFERENCE_XML, "target_xml": REFERENCE_XML}
        )
        payload = json.loads(result[0].text)
        assert payload["similarity_score"] == 1.0

    async def test_empty_reference_returns_error(self):
        result = await call_tool(
            "compare_musicxml", {"reference_xml": "", "target_xml": TARGET_XML}
        )
        payload = json.loads(result[0].text)
        assert payload["error_code"] == "INVALID_INPUT"

    async def test_malformed_target_returns_error(self):
        result = await call_tool(
            "compare_musicxml", {"reference_xml": REFERENCE_XML, "target_xml": "<foo/>"}
        )
        payload = json.loads(result[0].text)
        assert payload["error_code"] == "INVALID_INPUT"


class TestCallToolCompareMusicxmlFiles:
    async def test_valid_files(self, tmp_path):
        ref_path = tmp_path / "reference.musicxml"
        tgt_path = tmp_path / "target.musicxml"
        ref_path.write_text(REFERENCE_XML)
        tgt_path.write_text(TARGET_XML)

        result = await call_tool(
            "compare_musicxml_files",
            {"reference_path": str(ref_path), "target_path": str(tgt_path)},
        )
        payload = json.loads(result[0].text)
        assert "similarity_score" in payload
        assert "part_diffs" in payload

    async def test_missing_file_returns_error(self, tmp_path):
        ref_path = tmp_path / "reference.musicxml"
        ref_path.write_text(REFERENCE_XML)

        result = await call_tool(
            "compare_musicxml_files",
            {"reference_path": str(ref_path), "target_path": str(tmp_path / "missing.musicxml")},
        )
        payload = json.loads(result[0].text)
        assert payload["error_code"] == "FILE_NOT_FOUND"

    async def test_unsupported_file_extension_returns_error(self, tmp_path):
        ref_path = tmp_path / "reference.musicxml"
        tgt_path = tmp_path / "target.pdf"
        ref_path.write_text(REFERENCE_XML)
        tgt_path.write_text("not a musicxml file")

        result = await call_tool(
            "compare_musicxml_files",
            {"reference_path": str(ref_path), "target_path": str(tgt_path)},
        )
        payload = json.loads(result[0].text)
        assert payload["error_code"] == "UNSUPPORTED_FORMAT"

    async def test_missing_path_argument_returns_error(self):
        result = await call_tool(
            "compare_musicxml_files", {"reference_path": "", "target_path": "somewhere.musicxml"}
        )
        payload = json.loads(result[0].text)
        assert payload["error_code"] == "INVALID_PARAMETER"


class TestCallToolQuickSimilarity:
    async def test_valid_returns_score_and_summary_only(self):
        result = await call_tool(
            "quick_similarity", {"reference_xml": REFERENCE_XML, "target_xml": TARGET_XML}
        )
        payload = json.loads(result[0].text)
        assert set(payload.keys()) == {"similarity_score", "summary"}
        assert 0.0 <= payload["similarity_score"] <= 1.0

    async def test_invalid_input_returns_error(self):
        result = await call_tool(
            "quick_similarity", {"reference_xml": "not xml", "target_xml": TARGET_XML}
        )
        payload = json.loads(result[0].text)
        assert payload["error_code"] == "INVALID_INPUT"


class TestCallToolListChanges:
    async def test_returns_only_non_match_operations(self):
        result = await call_tool(
            "list_changes", {"reference_xml": REFERENCE_XML, "target_xml": TARGET_XML}
        )
        payload = json.loads(result[0].text)
        assert payload["count"] == len(payload["changes"])
        assert payload["count"] >= 1
        assert all(c["operation"] != "MATCH" for c in payload["changes"])
        assert all("part_name" in c for c in payload["changes"])

    async def test_identical_scores_have_no_changes(self):
        result = await call_tool(
            "list_changes", {"reference_xml": REFERENCE_XML, "target_xml": REFERENCE_XML}
        )
        payload = json.loads(result[0].text)
        assert payload["changes"] == []
        assert payload["count"] == 0

    async def test_part_filter(self):
        result = await call_tool(
            "list_changes",
            {"reference_xml": REFERENCE_XML, "target_xml": TARGET_XML, "part": "Soprano"},
        )
        payload = json.loads(result[0].text)
        assert payload["count"] >= 1
        assert all(c["part_name"] == "Soprano" for c in payload["changes"])

        result = await call_tool(
            "list_changes",
            {"reference_xml": REFERENCE_XML, "target_xml": TARGET_XML, "part": "Alto"},
        )
        payload = json.loads(result[0].text)
        assert payload["changes"] == []

    async def test_measure_range_filter(self):
        result = await call_tool(
            "list_changes",
            {
                "reference_xml": REFERENCE_XML,
                "target_xml": TARGET_XML,
                "measure_range": [2, 5],
            },
        )
        payload = json.loads(result[0].text)
        assert payload["changes"] == []

    async def test_invalid_measure_range_returns_error(self):
        result = await call_tool(
            "list_changes",
            {
                "reference_xml": REFERENCE_XML,
                "target_xml": TARGET_XML,
                "measure_range": [5, 1],
            },
        )
        payload = json.loads(result[0].text)
        assert payload["error_code"] == "INVALID_PARAMETER"

    async def test_malformed_musicxml_returns_error(self):
        result = await call_tool(
            "list_changes", {"reference_xml": "", "target_xml": TARGET_XML}
        )
        payload = json.loads(result[0].text)
        assert payload["error_code"] == "INVALID_INPUT"


class TestCallToolGenerateComparisonReport:
    async def test_valid_returns_report_text(self):
        result = await call_tool(
            "generate_comparison_report",
            {"reference_xml": REFERENCE_XML, "target_xml": TARGET_XML},
        )
        payload = json.loads(result[0].text)
        assert "report" in payload
        assert "%" in payload["report"]
        assert "similarity_score" in payload

    async def test_options_are_applied(self):
        result = await call_tool(
            "generate_comparison_report",
            {
                "reference_xml": REFERENCE_XML,
                "target_xml": TARGET_XML,
                "options": {"part_filter": ["Alto"]},
            },
        )
        payload = json.loads(result[0].text)
        assert payload["similarity_score"] == pytest.approx(1.0)

    async def test_invalid_input_returns_error(self):
        result = await call_tool(
            "generate_comparison_report",
            {"reference_xml": "", "target_xml": TARGET_XML},
        )
        payload = json.loads(result[0].text)
        assert payload["error_code"] == "INVALID_INPUT"

    async def test_invalid_option_returns_error(self):
        result = await call_tool(
            "generate_comparison_report",
            {
                "reference_xml": REFERENCE_XML,
                "target_xml": TARGET_XML,
                "options": {"measure_range": [5, 1]},
            },
        )
        payload = json.loads(result[0].text)
        assert payload["error_code"] == "INVALID_PARAMETER"


class TestCallToolExportAnnotatedMusicxml:
    async def test_valid_returns_both_documents(self):
        result = await call_tool(
            "export_annotated_musicxml",
            {"reference_xml": REFERENCE_XML, "target_xml": TARGET_XML},
        )
        payload = json.loads(result[0].text)
        assert "reference_annotated_musicxml" in payload
        assert "target_annotated_musicxml" in payload
        assert "<score-partwise" in payload["reference_annotated_musicxml"]
        assert "legend" in payload

    async def test_invalid_input_returns_error(self):
        result = await call_tool(
            "export_annotated_musicxml",
            {"reference_xml": "not xml", "target_xml": TARGET_XML},
        )
        payload = json.loads(result[0].text)
        assert payload["error_code"] == "INVALID_INPUT"


class TestUnknownTool:
    async def test_unknown_tool_raises(self):
        with pytest.raises(ValueError, match="Unknown tool"):
            await call_tool("nonexistent_tool", {})


@pytest.mark.integration
class TestIntegrationRealSATBFiles:
    """End-to-end tool calls against real compressed .mxl SATB scores shared with omr-mcp."""

    async def test_compare_musicxml_files_identical(self):
        mxl_files = sorted(_SATB_MXL_DIR.glob("*.mxl"))
        assert mxl_files, f"No .mxl fixtures found under {_SATB_MXL_DIR}"

        result = await call_tool(
            "compare_musicxml_files",
            {"reference_path": str(mxl_files[0]), "target_path": str(mxl_files[0])},
        )
        payload = json.loads(result[0].text)
        assert payload["similarity_score"] == 1.0

    async def test_quick_similarity_two_different_scores(self):
        mxl_files = sorted(_SATB_MXL_DIR.glob("*.mxl"))
        assert len(mxl_files) >= 2, f"Need at least 2 .mxl fixtures under {_SATB_MXL_DIR}"

        result = await call_tool(
            "compare_musicxml_files",
            {"reference_path": str(mxl_files[0]), "target_path": str(mxl_files[1])},
        )
        payload = json.loads(result[0].text)
        assert 0.0 <= payload["similarity_score"] <= 1.0

    async def test_generate_comparison_report_real_scores(self):
        mxl_files = sorted(_SATB_MXL_DIR.glob("*.mxl"))
        assert len(mxl_files) >= 2, f"Need at least 2 .mxl fixtures under {_SATB_MXL_DIR}"
        ref_xml = _mxl_to_musicxml(mxl_files[0])
        tgt_xml = _mxl_to_musicxml(mxl_files[1])

        result = await call_tool(
            "generate_comparison_report", {"reference_xml": ref_xml, "target_xml": tgt_xml}
        )
        payload = json.loads(result[0].text)
        assert "report" in payload
        assert "%" in payload["report"]

    async def test_export_annotated_musicxml_real_scores(self):
        mxl_files = sorted(_SATB_MXL_DIR.glob("*.mxl"))
        assert len(mxl_files) >= 2, f"Need at least 2 .mxl fixtures under {_SATB_MXL_DIR}"
        ref_xml = _mxl_to_musicxml(mxl_files[0])
        tgt_xml = _mxl_to_musicxml(mxl_files[1])

        result = await call_tool(
            "export_annotated_musicxml", {"reference_xml": ref_xml, "target_xml": tgt_xml}
        )
        payload = json.loads(result[0].text)
        assert "reference_annotated_musicxml" in payload
        assert "target_annotated_musicxml" in payload
