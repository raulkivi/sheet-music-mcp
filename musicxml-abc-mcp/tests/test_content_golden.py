"""Golden test: the tools' ``content`` stays byte-identical (MCP Apps ABC Workbench).

Linking the workbench and adding ``structuredContent`` must not change what text-only clients
see. The golden file was recorded before the presenter existed; regenerate it only for an
intended change with ``ABC_GOLDEN_UPDATE=1 pytest tests/test_content_golden.py``.
list_capabilities is not recorded: it carries package versions, and its tool list grows with the
app-only getter on purpose.
"""

import json
import os
import re
from pathlib import Path

import pytest

from musicxml_abc_mcp.server import call_tool

from .test_measures import SATB_PICKUP, SATB_SIX_BARS
from .test_server import MINIMAL_ABC, MINIMAL_MUSICXML

GOLDEN = Path(__file__).parent / "golden" / "abc_content.json"
TIMESTAMP = re.compile(r"\d{8}-\d{6}-\d{6}(-\d+)?")
# music21 gives parsed ABC parts random ids; they are not part of the contract.
RANDOM_PART_ID = re.compile(r"P[0-9a-f]{32}")
BIG_ABC = "X:1\nT:Big\nM:4/4\nL:1/8\nK:C\n" + "CDEFGABc|" * 600 + "]"


def _normalise(blocks, tmp_path: Path) -> list[dict]:
    dumped = json.dumps([b.model_dump(mode="json", by_alias=True, exclude_none=True) for b in blocks])
    dumped = dumped.replace(str(tmp_path.resolve()), "<TMP>").replace(str(tmp_path), "<TMP>")
    return json.loads(RANDOM_PART_ID.sub("<PID>", TIMESTAMP.sub("<STAMP>", dumped)))


async def _all_contents(tmp_path, monkeypatch) -> dict:
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
    score = tmp_path / "in.musicxml"
    score.write_text(MINIMAL_MUSICXML, encoding="utf-8")
    contents = {}

    async def record(name, tool, arguments):
        contents[name] = _normalise(await call_tool(tool, arguments), tmp_path)

    await record("to_abc", "musicxml_to_abc", {"musicxml": MINIMAL_MUSICXML})
    await record("to_abc_path", "musicxml_to_abc", {"musicxml_path": str(score)})
    await record("to_abc_satb", "musicxml_to_abc", {"musicxml": SATB_SIX_BARS})
    await record("to_abc_part", "musicxml_to_abc", {"musicxml": SATB_SIX_BARS, "part": "Alto"})
    await record("to_abc_measures", "musicxml_to_abc", {"musicxml": SATB_SIX_BARS, "measures": [3, 4]})
    await record("to_abc_pickup", "musicxml_to_abc", {"musicxml": SATB_PICKUP, "part": "P1"})
    await record("from_abc", "abc_to_musicxml", {"abc": MINIMAL_ABC})
    await record("from_abc_path", "abc_to_musicxml", {"abc": MINIMAL_ABC, "return": "path"})
    await record("from_abc_big_auto", "abc_to_musicxml", {"abc": BIG_ABC})
    await record("validate_ok", "validate_abc", {"abc": MINIMAL_ABC})
    await record("validate_no_headers", "validate_abc", {"abc": "CDEF|"})
    await record("validate_empty", "validate_abc", {"abc": ""})
    await record("describe", "describe_score", {"musicxml": MINIMAL_MUSICXML})

    await record("to_abc_bad_xml", "musicxml_to_abc", {"musicxml": "<nope/>"})
    await record("to_abc_bad_part", "musicxml_to_abc", {"musicxml": SATB_SIX_BARS, "part": "Tuba"})
    await record("to_abc_bad_measures", "musicxml_to_abc", {"musicxml": SATB_SIX_BARS, "measures": [9, 12]})
    await record("to_abc_missing_file", "musicxml_to_abc", {"musicxml_path": str(tmp_path / "no.musicxml")})
    await record("from_abc_empty", "abc_to_musicxml", {"abc": ""})
    await record("from_abc_bad_mode", "abc_to_musicxml", {"abc": MINIMAL_ABC, "return": "carrier-pigeon"})
    return contents


async def test_content_matches_the_golden_file(tmp_path, monkeypatch):
    contents = await _all_contents(tmp_path, monkeypatch)

    if os.environ.get("ABC_GOLDEN_UPDATE") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(contents, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip("golden file rewritten")

    assert contents == json.loads(GOLDEN.read_text(encoding="utf-8"))
