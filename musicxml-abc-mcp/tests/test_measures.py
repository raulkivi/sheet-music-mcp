"""Measure ranges on musicxml_to_abc (docs/research/ux-wave3-plan.md B2; docs/conventions.md,
Measure Ranges).

The score is cut to the printed bars before music21 parses it, so the ABC holds only those bars and
its K:, M: and Q: headers are the ones in force at the first kept bar.
"""

import json
from unittest.mock import patch

import music21.converter
import pytest
from mcp import Client
from sheet_music_mcp_core.measures import MEASURES_PROPERTY, MeasureRangeError
from sheet_music_mcp_core.scores import describe_score

from musicxml_abc_mcp.engine import musicxml_to_abc
from musicxml_abc_mcp.server import INSTRUCTIONS, app, call_tool, list_tools

_STEPS = "CDEFGA"
_PARTS = [("P1", "Soprano", 5), ("P2", "Alto", 4), ("P3", "Tenor", 4), ("P4", "Bass", 3)]
# Bar 1: C major, 4/4, tempo 84. Bar 2 changes to D major and 3/4, which bars 3-4 inherit.
_BAR_ONE_ATTRIBUTES = (
    "<attributes><divisions>1</divisions><key><fifths>0</fifths></key>"
    "<time><beats>4</beats><beat-type>4</beat-type></time>"
    "<clef><sign>G</sign><line>2</line></clef></attributes>"
)
_TEMPO = (
    '<direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit>'
    '<per-minute>84</per-minute></metronome></direction-type><sound tempo="84"/></direction>'
)
_BAR_TWO_ATTRIBUTES = (
    "<attributes><key><fifths>2</fifths></key><time><beats>3</beats><beat-type>4</beat-type></time></attributes>"
)


def _note(step: str, octave: int, beats: int) -> str:
    kind = {1: "<type>quarter</type>", 3: "<type>half</type><dot/>", 4: "<type>whole</type>"}[beats]
    return f"<note><pitch><step>{step}</step><octave>{octave}</octave></pitch><duration>{beats}</duration>{kind}</note>"


def _six_bar_part(octave: int) -> str:
    """Bar n holds one note on the n-th step of CDEFGA, filling the bar."""
    bars = [f'<measure number="1">{_BAR_ONE_ATTRIBUTES}{_TEMPO}{_note("C", octave, 4)}</measure>']
    bars.append(f'<measure number="2">{_BAR_TWO_ATTRIBUTES}{_note("D", octave, 3)}</measure>')
    bars += [f'<measure number="{n}">{_note(_STEPS[n - 1], octave, 3)}</measure>' for n in range(3, 7)]
    return "".join(bars)


def _score(body_by_part) -> str:
    part_list = "".join(f'<score-part id="{pid}"><part-name>{name}</part-name></score-part>' for pid, name, _ in _PARTS)
    parts = "".join(f'<part id="{pid}">{body_by_part(octave)}</part>' for pid, _, octave in _PARTS)
    return (
        '<?xml version="1.0" encoding="UTF-8"?><score-partwise version="3.1">'
        f"<part-list>{part_list}</part-list>{parts}</score-partwise>"
    )


def _pickup_part(octave: int) -> str:
    """A one-beat pickup (G), then two full 4/4 bars (C, D)."""
    return (
        f'<measure number="0" implicit="yes">{_BAR_ONE_ATTRIBUTES}{_note("G", octave, 1)}</measure>'
        f'<measure number="1">{_note("C", octave, 4)}</measure>'
        f'<measure number="2">{_note("D", octave, 4)}</measure>'
    )


SATB_SIX_BARS = _score(_six_bar_part)
SATB_PICKUP = _score(_pickup_part)


def _tunes(abc: str) -> list[str]:
    return abc.split("\n\n")


def _header(tune: str, field: str) -> str:
    return next(line[2:] for line in tune.splitlines() if line.startswith(f"{field}:"))


def _bars(tune: str) -> list[str]:
    """The note tokens of each bar of one tune (the lines after its K: header)."""
    body = " ".join(tune.split("\nK:", 1)[1].splitlines()[1:])
    return [bar.strip() for bar in body.replace("|]", "|").split("|") if bar.strip()]


class TestEngine:
    def test_exports_exactly_the_selected_bars_in_every_part(self):
        result = musicxml_to_abc(SATB_SIX_BARS, measures=[3, 4])

        tunes = _tunes(result["abc"])
        assert result["parts_included"] == ["P1", "P2", "P3", "P4"]
        assert len(tunes) == 4
        for tune in tunes:
            assert len(_bars(tune)) == 2
        assert _bars(tunes[0]) == ["e6", "f6"]
        assert _bars(tunes[3]) == ["E,6", "F,6"]

    def test_key_meter_and_tempo_in_force_at_the_first_bar_are_carried(self):
        tune = _tunes(musicxml_to_abc(SATB_SIX_BARS, measures=[3, 4])["abc"])[0]

        assert _header(tune, "K") == "D"
        assert _header(tune, "M") == "3/4"
        assert _header(tune, "Q") == "1/4=84"

    def test_only_the_cut_score_reaches_music21(self):
        parse = music21.converter.parseData
        seen: list[str] = []

        def spy(data, *args, **kwargs):
            seen.append(data)
            return parse(data, *args, **kwargs)

        with patch("music21.converter.parseData", side_effect=spy):
            musicxml_to_abc(SATB_SIX_BARS, measures=[3, 4])

        assert describe_score(seen[0])["measures"] == 2

    def test_combines_with_part_selection(self):
        result = musicxml_to_abc(SATB_SIX_BARS, part_id="Alto", measures=[5, 6])

        assert result["parts_included"] == ["P2"]
        assert _bars(result["abc"]) == ["G6", "A6"]

    def test_pickup_bar_is_measure_zero(self):
        tunes = _tunes(musicxml_to_abc(SATB_PICKUP, measures=[0, 0])["abc"])

        assert [_bars(tune) for tune in tunes] == [["g2"], ["G2"], ["G2"], ["G,2"]]

    def test_range_after_a_pickup_starts_on_the_full_bar(self):
        tune = _tunes(musicxml_to_abc(SATB_PICKUP, measures=[1, 2])["abc"])[0]

        assert _bars(tune) == ["c8", "d8"]
        assert _header(tune, "M") == "4/4"

    @pytest.mark.parametrize("measures", [[5, 99], [4, 3], [7, 7]])
    def test_range_outside_the_score_or_reversed_names_the_score_range(self, measures):
        with pytest.raises(MeasureRangeError) as excinfo:
            musicxml_to_abc(SATB_SIX_BARS, measures=measures)

        assert excinfo.value.error_code == "INVALID_PARAMETER"
        assert excinfo.value.hint == "This score has measures 1–6."

    @pytest.mark.parametrize("measures", [[3], ["3", "4"], [True, 4]])
    def test_malformed_range_is_invalid_parameter(self, measures):
        with pytest.raises(MeasureRangeError) as excinfo:
            musicxml_to_abc(SATB_SIX_BARS, measures=measures)

        assert excinfo.value.error_code == "INVALID_PARAMETER"

    def test_no_range_gives_the_whole_score_as_before(self):
        assert musicxml_to_abc(SATB_SIX_BARS, measures=None) == musicxml_to_abc(SATB_SIX_BARS)
        assert len(_bars(_tunes(musicxml_to_abc(SATB_SIX_BARS)["abc"])[0])) == 6


class TestServer:
    async def test_schema_lists_measures(self):
        tool = next(t for t in await list_tools() if t.name == "musicxml_to_abc")

        assert tool.input_schema["properties"]["measures"] == dict(MEASURES_PROPERTY)["measures"]
        assert "measures" not in tool.input_schema.get("required", [])

    async def test_measures_cut_the_exported_abc(self):
        result = await call_tool("musicxml_to_abc", {"musicxml": SATB_SIX_BARS, "measures": [3, 4]})

        abc = json.loads(result[0].text)["abc"]
        assert [len(_bars(tune)) for tune in _tunes(abc)] == [2, 2, 2, 2]

    async def test_out_of_range_is_an_invalid_parameter_error_with_hint(self):
        result = await call_tool("musicxml_to_abc", {"musicxml": SATB_SIX_BARS, "measures": [5, 99]})

        payload = json.loads(result[0].text)
        assert payload["error_code"] == "INVALID_PARAMETER"
        assert payload["hint"] == "This score has measures 1–6."

    async def test_schema_rejects_a_malformed_range_through_the_protocol(self):
        async with Client(app) as client:
            result = await client.call_tool("musicxml_to_abc", {"musicxml": SATB_SIX_BARS, "measures": [3]})

        assert result.is_error
        assert "INVALID_PARAMETER" in result.content[0].text

    async def test_list_capabilities_lists_measures(self):
        result = await call_tool("list_capabilities", {})

        assert "measures" in json.loads(result[0].text)["input_parameters"]

    def test_instructions_mention_measures(self):
        assert "measures" in INSTRUCTIONS


class TestTempoHeader:
    """The cut score carries tempo as a bare ``<sound tempo>``, which music21 reads as a
    MetronomeMark with only ``numberSounding`` set: Q: must use it rather than fall back to 120."""

    def test_sound_only_tempo_sets_q(self):
        score = SATB_SIX_BARS.replace(_TEMPO, '<sound tempo="66"/>')

        assert _header(_tunes(musicxml_to_abc(score)["abc"])[0], "Q") == "1/4=66"

    def test_no_tempo_still_defaults_to_120(self):
        score = SATB_SIX_BARS.replace(_TEMPO, "")

        assert _header(_tunes(musicxml_to_abc(score)["abc"])[0], "Q") == "1/4=120"
