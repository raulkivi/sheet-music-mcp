"""synthesize's practice parameters at the tool level (UX Wave 3 C8–C11, B2).

The engine runs for real up to MIDI; synthesize_midi is faked and keeps the MIDI it was given.
"""

import asyncio
import json
import wave

import pytest
from mcp import Client
from sheet_music_mcp_core.measures import MEASURES_PROPERTY

import synth_mcp.server as server
from synth_mcp.server import app, call_tool, list_tools

from .midi_helpers import cc7, click_events, fixture, melodic_tracks, read_midi

SATB = fixture("satb_4bars.musicxml")

NEW_PROPERTIES = (
    "measures", "repeat", "count_in_bars", "metronome", "timbre", "part_gains", "preset", "focus_part",
)


@pytest.fixture(autouse=True)
def output_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def rendered(monkeypatch):
    midi = []

    def fake(midi_bytes, output_path):
        midi.append(midi_bytes)
        with wave.open(output_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\0\0" * 800)
        return 0.1

    monkeypatch.setattr(server, "synthesize_midi", fake)
    return midi


def _json(result):
    return json.loads(result[0].text)


async def _schema():
    return next(t for t in await list_tools() if t.name == "synthesize").input_schema


class TestSchema:
    async def test_every_new_property_is_listed(self):
        assert set(NEW_PROPERTIES) <= set((await _schema())["properties"])

    async def test_measures_is_the_shared_property(self):
        assert (await _schema())["properties"]["measures"] == dict(MEASURES_PROPERTY["measures"])

    async def test_bounds(self):
        props = (await _schema())["properties"]
        assert (props["repeat"]["minimum"], props["repeat"]["maximum"]) == (1, 20)
        assert (props["count_in_bars"]["minimum"], props["count_in_bars"]["maximum"]) == (0, 4)
        assert props["metronome"]["type"] == "boolean"
        assert props["timbre"]["enum"] == ["score", "piano", "choir", "organ"]
        assert props["preset"]["enum"] == ["learning", "karaoke", "equal"]
        gain = props["part_gains"]["additionalProperties"]
        assert (gain["type"], gain["minimum"], gain["maximum"]) == ("number", 0.0, 2.0)
        assert props["focus_part"]["type"] == "string"

    async def test_nothing_new_is_required(self):
        schema = await _schema()
        assert not set(NEW_PROPERTIES) & set(schema.get("required", []))


class TestSynthesize:
    async def test_default_call_passes_no_practice_options(self, monkeypatch):
        seen = []

        def fake_extract(musicxml, part_ids, tempo_factor, **practice):
            seen.append(practice)
            return b"MThd"

        monkeypatch.setattr(server, "extract_midi", fake_extract)
        monkeypatch.setattr(server, "synthesize_midi", lambda midi, path: 0.0)

        await call_tool("synthesize", {"musicxml": SATB})

        assert seen == [{}]

    async def test_practice_options_reach_the_midi(self, rendered):
        result = await call_tool(
            "synthesize",
            {"musicxml": SATB, "preset": "learning", "focus_part": "Alto", "count_in_bars": 1,
             "measures": [3, 4], "repeat": 2, "timbre": "choir"},
        )

        data = _json(result)
        assert "error" not in data
        _, tracks = read_midi(rendered[0])
        assert [cc7(t) for t in melodic_tracks(tracks)] == [[32], [95], [32], [32]]
        assert len(click_events(tracks)) == 4

    async def test_result_echoes_the_practice_options(self, rendered):
        result = await call_tool(
            "synthesize", {"musicxml": SATB, "measures": [3, 4], "repeat": 2, "part_gains": {"P2": 0}}
        )

        data = _json(result)
        assert data["measures"] == [3, 4]
        assert data["repeat"] == 2
        assert data["part_gains"] == {"P2": 0}

    async def test_measures_out_of_range(self, rendered):
        data = _json(await call_tool("synthesize", {"musicxml": SATB, "measures": [7, 9]}))

        assert data["error_code"] == "INVALID_PARAMETER"
        assert data["hint"] == "This score has measures 1–4."
        assert rendered == []

    async def test_learning_without_focus_part(self, rendered):
        data = _json(await call_tool("synthesize", {"musicxml": SATB, "preset": "learning"}))

        assert data["error_code"] == "INVALID_PARAMETER"
        assert data["choices"] == ["Soprano (P1)", "Alto (P2)", "Tenor (P3)", "Bass (P4)"]

    async def test_unknown_part_gains_key(self, rendered):
        data = _json(await call_tool("synthesize", {"musicxml": SATB, "part_gains": {"Viola": 1}}))

        assert data["error_code"] == "INVALID_PARAMETER"
        assert data["choices"]


def _call_over_protocol(arguments):
    async def _go():
        async with Client(app) as client:
            return await client.call_tool("synthesize", arguments)

    return asyncio.run(_go())


@pytest.mark.parametrize(
    "extra",
    [{"repeat": 21}, {"repeat": 0}, {"count_in_bars": 5}, {"timbre": "violin"},
     {"part_gains": {"P1": 2.5}}, {"part_gains": {"P1": -1}}, {"preset": "loud"},
     {"measures": [3]}, {"metronome": "yes"}],
)
def test_schema_rejects_out_of_range_values(extra):
    result = _call_over_protocol({"musicxml": SATB, **extra})

    assert result.is_error
    assert json.loads(result.content[0].text)["error_code"] == "INVALID_PARAMETER"


async def test_capabilities_list_the_new_tool_and_parameters():
    data = _json(await call_tool("list_capabilities", {}))

    assert "starting_pitches" in data["tools"]
    assert set(NEW_PROPERTIES) <= set(data["input_parameters"])
