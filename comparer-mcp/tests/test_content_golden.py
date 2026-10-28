"""Golden test: the tools' ``content`` stays byte-identical (MCP Apps Diff Viewer).

Linking the Diff Viewer and adding ``structuredContent`` must not change what text-only clients
see. The golden file was recorded before the presenter existed; regenerate it only for an intended
change with ``COMPARER_GOLDEN_UPDATE=1 pytest tests/test_content_golden.py``.
"""

import json
import os
import re
from pathlib import Path

import pytest

from comparer_mcp.server import call_tool

from .test_server import REFERENCE_XML, TARGET_XML

GOLDEN = Path(__file__).parent / "golden" / "comparer_content.json"
TMP: list = []
# music21 stamps the export with the current date.
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# music21 gives every part a fresh random id per process.
PART_ID = re.compile(r"P[0-9a-f]{32}")
# Output file names carry a timestamp.
STAMP = re.compile(r"\d{8}-\d{6}-\d{6}")


def _text(result) -> list[dict]:
    blocks = result.content if hasattr(result, "content") else result
    dumped = json.dumps([b.model_dump(mode="json", by_alias=True, exclude_none=True) for b in blocks])
    return json.loads(PART_ID.sub("<PART>", STAMP.sub("<STAMP>", DATE.sub("<DATE>", dumped))).replace(str(TMP[0].resolve()), "<TMP>").replace(str(TMP[0]), "<TMP>"))


async def _all_contents(tmp_path, monkeypatch) -> dict:
    TMP[:] = [tmp_path]
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
    reference = tmp_path / "reference.musicxml"
    target = tmp_path / "target.musicxml"
    reference.write_text(REFERENCE_XML, encoding="utf-8")
    target.write_text(TARGET_XML, encoding="utf-8")
    pair = {"reference_xml": REFERENCE_XML, "target_xml": TARGET_XML}
    paths = {"reference_path": str(reference), "target_path": str(target)}

    contents = {}

    async def record(name, tool, arguments):
        contents[name] = _text(await call_tool(tool, arguments))

    await record("compare", "compare_musicxml", pair)
    await record("compare_options", "compare_musicxml", {**pair, "options": {"measures": [1, 1], "parts": ["Soprano"]}})
    await record("compare_identical", "compare_musicxml", {**pair, "target_xml": REFERENCE_XML})
    await record("compare_from_paths", "compare_musicxml", paths)
    await record("compare_files", "compare_musicxml_files", paths)
    await record("similarity", "quick_similarity", pair)
    await record("changes", "list_changes", pair)
    await record("changes_part", "list_changes", {**pair, "part": "Soprano", "measures": [1, 1]})
    await record("report", "generate_comparison_report", pair)
    await record("export_inline", "export_annotated_musicxml", {**pair, "return": "inline"})
    await record("export_path", "export_annotated_musicxml", {**pair, "return": "path"})
    await record("capabilities", "list_capabilities", {})
    await record("describe", "describe_score", {"musicxml": REFERENCE_XML})

    await record("compare_bad_xml", "compare_musicxml", {"reference_xml": "<nope/>", "target_xml": TARGET_XML})
    await record("compare_missing_target", "compare_musicxml", {"reference_xml": REFERENCE_XML})
    await record("files_missing_reference", "compare_musicxml_files", {"target_path": str(target)})
    await record("files_no_file", "compare_musicxml_files",
                 {"reference_path": str(tmp_path / "nope.musicxml"), "target_path": str(target)})
    await record("changes_bad_part", "list_changes", {**pair, "part": "Tuba"})
    await record("report_bad_xml", "generate_comparison_report", {"reference_xml": "<nope/>", "target_xml": TARGET_XML})
    await record("export_bad_xml", "export_annotated_musicxml", {"reference_xml": "<nope/>", "target_xml": TARGET_XML})
    return contents


async def test_content_matches_the_golden_file(tmp_path, monkeypatch):
    contents = await _all_contents(tmp_path, monkeypatch)

    if os.environ.get("COMPARER_GOLDEN_UPDATE") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(contents, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip("golden file rewritten")

    assert contents == json.loads(GOLDEN.read_text(encoding="utf-8"))
