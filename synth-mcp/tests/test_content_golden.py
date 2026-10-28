"""Golden test: the tools' ``content`` stays byte-identical (MCP Apps Practice Player, AC-S4).

Linking the Practice Player and adding ``structuredContent`` must not change what text-only
clients see. The golden file was recorded before the presenter existed; regenerate it only for an
intended change with ``SYNTH_GOLDEN_UPDATE=1 pytest tests/test_content_golden.py``.
"""

import json
import os
import wave
from pathlib import Path

import pytest

import synth_mcp.server as server
from synth_mcp.server import call_tool

from .midi_helpers import fixture
from .test_server import VALID_MUSICXML

GOLDEN = Path(__file__).parent / "golden" / "synth_content.json"
SATB = fixture("satb_4bars.musicxml")


def _fake_synthesize(midi_bytes, output_path):
    with wave.open(output_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0" * 800)
    return 4.004


def _normalised(blocks, tmp_path: Path) -> list[dict]:
    dumped = json.dumps([b.model_dump(mode="json", by_alias=True, exclude_none=True) for b in blocks])
    return json.loads(dumped.replace(str(tmp_path.resolve()), "<TMP>").replace(str(tmp_path), "<TMP>"))


async def _all_contents(tmp_path, monkeypatch) -> dict:
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
    monkeypatch.setattr(server, "synthesize_midi", _fake_synthesize)
    score = tmp_path / "score.musicxml"
    score.write_text(VALID_MUSICXML, encoding="utf-8")
    contents = {}

    async def record(name, tool, arguments):
        contents[name] = _normalised(await call_tool(tool, arguments), tmp_path)

    def out(name):
        return str(tmp_path / name)

    await record("get_parts", "get_parts", {"musicxml": VALID_MUSICXML})
    await record("get_parts_from_path", "get_parts", {"musicxml_path": str(score)})
    await record("synthesize", "synthesize", {"musicxml": VALID_MUSICXML, "output_path": out("a.wav")})
    await record("synthesize_parts_tempo", "synthesize",
                 {"musicxml": VALID_MUSICXML, "parts": ["Alto"], "tempo_factor": 0.75, "output_path": out("b.wav")})
    await record("synthesize_from_path", "synthesize", {"musicxml_path": str(score), "output_path": out("c.wav")})
    await record("synthesize_practice", "synthesize",
                 {"musicxml": SATB, "preset": "learning", "focus_part": "Alto", "count_in_bars": 1,
                  "measures": [2, 3], "repeat": 2, "timbre": "choir", "part_gains": {"P4": 0.5},
                  "output_path": out("d.wav")})
    await record("get_parts_bad_xml", "get_parts", {"musicxml": "<nope/>"})
    await record("synthesize_bad_xml", "synthesize", {"musicxml": "<nope/>"})
    await record("synthesize_bad_tempo", "synthesize", {"musicxml": VALID_MUSICXML, "tempo_factor": 9})
    await record("synthesize_bad_part", "synthesize", {"musicxml": VALID_MUSICXML, "parts": ["Tuba"]})
    await record("synthesize_bad_measures", "synthesize", {"musicxml": SATB, "measures": [9, 12]})
    await record("synthesize_outside_root", "synthesize", {"musicxml": VALID_MUSICXML, "output_path": "/tmp/x.wav"})
    await record("synthesize_bad_gain_part", "synthesize", {"musicxml": SATB, "part_gains": {"Viola": 1}})
    return contents


async def test_content_matches_the_golden_file(tmp_path, monkeypatch):
    contents = await _all_contents(tmp_path, monkeypatch)

    if os.environ.get("SYNTH_GOLDEN_UPDATE") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(contents, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip("golden file rewritten")

    assert contents == json.loads(GOLDEN.read_text(encoding="utf-8"))
