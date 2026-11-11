"""Golden test: the tools' ``content`` stays byte-identical (MCP Apps Practice Coach).

Linking the Practice Coach and adding ``structuredContent`` must not change what text-only
clients see. The golden file was recorded before the presenter existed; regenerate it only for an
intended change with ``PITCH_GOLDEN_UPDATE=1 pytest tests/test_content_golden.py``.
"""

import json
import os
import re
from pathlib import Path

import pytest

import pitch_mcp.server as server
from pitch_mcp import engine
from pitch_mcp.server import call_tool

from .test_engine import MINIMAL_MUSICXML
from .test_practice import SIX_BARS, mic  # noqa: F401  (mic is a fixture)

GOLDEN = Path(__file__).parent / "golden" / "pitch_content.json"
TMP: list = []
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

ANALYSIS = {
    "part_id": "P1",
    "part_name": "Soprano",
    "measures_covered": 2,
    "avg_accuracy_cents": 12.5,
    "note_accuracy": [
        {"measure": 1, "beat": 1.0, "expected": "C4", "expected_hz": 261.63, "sung_hz": 258.0,
         "accuracy_cents": -24, "status": "on_pitch"},
        {"measure": 2, "beat": 1.0, "expected": "D4", "expected_hz": 293.66, "sung_hz": None,
         "accuracy_cents": None, "status": "no_signal"},
    ],
    "accuracy_histogram": {"on_pitch": 1, "sharp": 0, "flat": 0, "no_signal": 1},
    "highlights": [],
}


def _text(blocks) -> list[dict]:
    dumped = json.dumps([b.model_dump(mode="json", by_alias=True, exclude_none=True) for b in blocks])
    return json.loads(UUID.sub("<SESSION>", dumped).replace(str(TMP[0].resolve()), "<TMP>").replace(str(TMP[0]), "<TMP>"))


async def _all_contents(tmp_path, monkeypatch) -> dict:
    TMP[:] = [tmp_path]
    audio = tmp_path / "take.wav"
    audio.write_bytes(b"RIFF")
    score = tmp_path / "score.musicxml"
    score.write_text(MINIMAL_MUSICXML, encoding="utf-8")
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
    monkeypatch.setattr(server, "analyze_recording", lambda *a, **k: ANALYSIS)

    contents = {}

    async def record(name, tool, arguments):
        contents[name] = _text(await call_tool(tool, arguments))

    await record("load_score", "load_score", {"musicxml": MINIMAL_MUSICXML, "part": "P1"})
    await record("load_score_measures", "load_score", {"musicxml": SIX_BARS, "part": "Alto", "measures": [2, 3]})
    await record("start_practice", "start_practice", {"musicxml": SIX_BARS, "part": "P1", "tempo_bpm": 100})
    await record("analyze", "analyze_recording", {"audio_path": str(audio), "musicxml": MINIMAL_MUSICXML, "part": "P1"})
    await record("analyze_from_path", "analyze_recording",
                 {"audio_path": str(audio), "musicxml_path": str(score), "part": "P1"})
    await record("list_sessions", "list_sessions", {})

    first = engine.list_sessions()["sessions"][0]["session_id"]
    await record("position", "get_current_position", {"session_id": first})
    await record("stop", "stop_monitoring", {"session_id": first})

    await record("position_unknown", "get_current_position", {"session_id": "no-such-session"})
    await record("position_invalid_id", "get_current_position", {"session_id": ""})
    await record("load_no_part", "load_score", {"musicxml": MINIMAL_MUSICXML})
    await record("load_bad_xml", "load_score", {"musicxml": "<nope/>", "part": "P1"})
    await record("load_bad_part", "load_score", {"musicxml": MINIMAL_MUSICXML, "part": "Tuba"})
    await record("practice_bad_measures", "start_practice",
                 {"musicxml": SIX_BARS, "part": "P1", "measures": [9, 12]})
    await record("analyze_missing_audio", "analyze_recording",
                 {"audio_path": str(tmp_path / "nope.wav"), "musicxml": MINIMAL_MUSICXML, "part": "P1"})
    await record("analyze_no_part", "analyze_recording", {"audio_path": str(audio), "musicxml": MINIMAL_MUSICXML})
    return contents


async def test_content_matches_the_golden_file(tmp_path, monkeypatch, mic):  # noqa: F811
    contents = await _all_contents(tmp_path, monkeypatch)

    if os.environ.get("PITCH_GOLDEN_UPDATE") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(contents, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip("golden file rewritten")

    assert contents == json.loads(GOLDEN.read_text(encoding="utf-8"))
