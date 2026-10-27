"""Measure ranges (docs/conventions.md, Measure Ranges)."""

from types import MappingProxyType

import jsonschema
import pytest

from sheet_music_mcp_core.errors import ProcessingError
from sheet_music_mcp_core.measures import (
    MEASURES_PROPERTY,
    MeasureRangeError,
    parse_range,
    printed_numbers,
    select_measures,
)
from sheet_music_mcp_core.scores import describe_score, first_pitches, parse_score

from .musicxml_fixtures import (
    SIX_BAR_PARTS,
    SIX_BARS,
    attributes,
    metronome,
    note,
    partwise,
    rest,
    tempo,
    timewise,
)


def _numbers(root, part_index=0):
    """``number`` attributes of one part's measures in a partwise result."""
    return [measure.get("number") for measure in root.findall("part")[part_index].findall("measure")]


def _first_measure(text, part_index=0):
    return parse_score(text).findall("part")[part_index].find("measure")


def _score(*measures, numbers=None, implicit_first=False):
    return partwise([("P1", "Voice", None, list(measures))], numbers=numbers, implicit_first=implicit_first)


PICKUP = _score(
    attributes(time="4/4", clef=("G", 2)) + note("G", 4),
    note("C", 5, duration=8),
    note("D", 5, duration=8),
    numbers=["0", "1", "2"],
)


class TestMeasuresProperty:
    def test_is_read_only(self):
        assert isinstance(MEASURES_PROPERTY, MappingProxyType)

    def test_matches_the_plan(self):
        assert dict(MEASURES_PROPERTY) == {
            "measures": {
                "type": "array",
                "items": {"type": "integer", "minimum": 0, "maximum": 99999},
                "minItems": 2,
                "maxItems": 2,
                "description": (
                    "Inclusive [start, end] range of printed measure numbers, e.g. [17, 24]. A pickup bar is 0."
                ),
            }
        }

    @pytest.mark.parametrize(("value", "valid"), [([3, 4], True), ([3], False), ([1, 100000], False), ([-1, 2], False)])
    def test_validates_as_a_schema_property(self, value, valid):
        schema = {"type": "object", "properties": dict(MEASURES_PROPERTY)}
        validator = jsonschema.Draft202012Validator(schema)

        assert validator.is_valid({"measures": value}) is valid


class TestParseRange:
    @pytest.mark.parametrize("value", [[3, 4], (3, 4)])
    def test_accepts_a_pair(self, value):
        assert parse_range(value) == (3, 4)

    def test_accepts_a_single_measure_and_the_bounds(self):
        assert parse_range([0, 0]) == (0, 0)
        assert parse_range([99999, 99999]) == (99999, 99999)

    def test_none_is_none(self):
        assert parse_range(None) is None

    @pytest.mark.parametrize(
        "value",
        [[4, 3], [3], [3, 4, 5], [True, 4], [3, False], ["3", "4"], [3.0, 4], [-1, 2], [1, 100000], "3-4", {"start": 3}, 3],
    )
    def test_rejects_anything_else(self, value):
        with pytest.raises(MeasureRangeError) as caught:
            parse_range(value)

        assert caught.value.error_code == "INVALID_PARAMETER"
        assert "[start, end]" in caught.value.hint

    def test_names_the_parameter(self):
        with pytest.raises(MeasureRangeError, match="options.measures"):
            parse_range([4, 3], param="options.measures")

    def test_is_a_processing_error(self):
        assert issubclass(MeasureRangeError, ProcessingError)


class TestPrintedNumbers:
    def test_plain_numbers(self):
        assert printed_numbers(parse_score(SIX_BARS)) == [1, 2, 3, 4, 5, 6]

    def test_pickup_numbered_zero(self):
        assert printed_numbers(parse_score(PICKUP)) == [0, 1, 2]

    def test_implicit_first_measure_is_zero(self):
        score = _score(note("G", 4), note("C", 5), note("D", 5), numbers=["1", "2", "3"], implicit_first=True)

        assert printed_numbers(parse_score(score)) == [0, 2, 3]

    def test_suffix_belongs_to_its_integer(self):
        score = _score(note("C", 4), note("D", 4), note("E", 4), numbers=["11", "12a", "12b"])

        assert printed_numbers(parse_score(score)) == [11, 12, 12]

    @pytest.mark.parametrize(("number", "expected"), [("X1", 7), ("", 7), ("1234567", 7), ("-3", 7)])
    def test_number_without_a_leading_integer_takes_the_previous(self, number, expected):
        score = _score(note("C", 4), note("D", 4), numbers=["7", number])

        assert printed_numbers(parse_score(score)) == [7, expected]

    def test_number_is_a_token_so_surrounding_whitespace_is_ignored(self):
        score = _score(note("C", 4), note("D", 4), numbers=["7", " 8 "])

        assert printed_numbers(parse_score(score)) == [7, 8]

    def test_first_number_without_an_integer_is_zero(self):
        score = _score(note("C", 4), note("D", 4), numbers=["X1", "1"])

        assert printed_numbers(parse_score(score)) == [0, 1]

    def test_reads_the_first_part_only(self):
        score = partwise(
            [("P1", "S", None, [note("C", 4), note("D", 4)]), ("P2", "A", None, [note("C", 4), note("D", 4)])],
            numbers=["5", "6"],
        )

        assert printed_numbers(parse_score(score)) == [5, 6]

    def test_timewise(self):
        assert printed_numbers(parse_score(timewise(SIX_BAR_PARTS, numbers=["0", "1", "2", "3", "4", "5"]))) == [
            0, 1, 2, 3, 4, 5,
        ]


class TestSelectMeasures:
    def test_none_returns_the_text_unchanged(self):
        assert select_measures(SIX_BARS, None) is SIX_BARS

    def test_keeps_exactly_the_range_in_every_part(self):
        root = parse_score(select_measures(SIX_BARS, [3, 4]))

        assert [_numbers(root, index) for index in range(4)] == [["3", "4"]] * 4

    def test_result_is_musicxml_text_with_a_declaration(self):
        result = select_measures(SIX_BARS, [3, 4])

        assert isinstance(result, str)
        assert result.startswith('<?xml version="1.0" encoding="UTF-8"?>')
        assert parse_score(result).tag == "score-partwise"

    def test_header_is_kept(self):
        description = describe_score(select_measures(SIX_BARS, [3, 4]))

        assert description["title"] == "Six Bars"
        assert [part["name"] for part in description["parts"]] == ["Soprano", "Alto", "Tenor", "Bass"]

    def test_described_cut_has_the_state_in_force_at_start(self):
        description = describe_score(select_measures(SIX_BARS, [3, 4]))

        assert description["measures"] == 2
        assert description["key"] == "F major"
        assert description["time"] == "3/4"
        assert description["tempo_bpm"] == 80
        # Divisions 2 are carried from bar 1: two bars of 3/4 last six quarters, not twelve.
        assert description["duration_quarters"] == 6.0
        assert [part["clef"] for part in description["parts"]] == ["treble", "treble", "bass", "bass"]

    def test_carried_attributes_are_in_musicxml_order(self):
        attributes_ = _first_measure(select_measures(SIX_BARS, [3, 4]), 2).find("attributes")

        assert [child.tag for child in attributes_] == ["divisions", "key", "time", "clef"]
        assert attributes_.findtext("divisions") == "2"
        assert attributes_.findtext("key/fifths") == "-1"
        assert attributes_.findtext("time/beats") == "3"
        assert attributes_.findtext("clef/sign") == "F"

    def test_attributes_come_before_the_first_note(self):
        measure = _first_measure(select_measures(SIX_BARS, [3, 4]))

        tags = [child.tag for child in measure]
        assert tags.index("attributes") < tags.index("note")

    def test_tempo_is_carried_as_sound_tempo(self):
        measure = _first_measure(select_measures(SIX_BARS, [3, 4]))

        assert [sound.get("tempo") for sound in measure.iter("sound")] == ["80"]

    def test_no_tempo_is_added_to_parts_that_never_had_one(self):
        alto = _first_measure(select_measures(SIX_BARS, [3, 4]), 1)

        assert alto.find(".//sound") is None

    def test_tempo_at_the_start_of_the_first_kept_measure_is_not_doubled(self):
        score = _score(
            attributes(time="2/4") + tempo(80) + note("C", 4, duration=4),
            tempo(100) + note("D", 4, duration=4),
        )

        measure = _first_measure(select_measures(score, [2, 2]))

        assert [sound.get("tempo") for sound in measure.iter("sound")] == ["100"]

    def test_latest_tempo_wins(self):
        score = _score(
            attributes(time="2/4") + tempo(80) + note("C", 4, duration=4),
            tempo(100) + note("D", 4, duration=4),
            note("E", 4, duration=4),
        )

        assert describe_score(select_measures(score, [3, 3]))["tempo_bpm"] == 100

    def test_tempo_later_in_the_first_kept_measure_does_not_hide_the_carried_one(self):
        score = _score(
            attributes(time="2/4") + tempo(80) + note("C", 4, duration=4),
            note("D", 4) + tempo(100) + note("D", 4),
        )

        measure = _first_measure(select_measures(score, [2, 2]))

        assert [sound.get("tempo") for sound in measure.iter("sound")] == ["80", "100"]

    def test_metronome_mark_is_carried_as_quarter_note_tempo(self):
        score = _score(
            attributes(time="2/4") + metronome("half", 40) + note("C", 4, duration=4),
            note("D", 4, duration=4),
        )

        assert describe_score(select_measures(score, [2, 2]))["tempo_bpm"] == 80

    def test_print_in_the_first_kept_measure_is_dropped(self):
        measure = _first_measure(select_measures(SIX_BARS, [3, 4]))

        assert measure.find("print") is None

    def test_print_after_the_first_kept_measure_is_kept(self):
        root = parse_score(select_measures(SIX_BARS, [2, 4]))

        assert root.find("part/measure[@number='3']/print") is not None

    def test_print_is_kept_when_the_range_starts_at_the_first_measure(self):
        score = _score('<print new-page="yes"/>' + attributes() + note("C", 4), note("D", 4))

        assert _first_measure(select_measures(score, [1, 1])).find("print") is not None

    def test_whole_range_describes_like_the_original(self):
        assert describe_score(select_measures(SIX_BARS, [1, 6])) == describe_score(SIX_BARS)

    def test_attributes_the_first_kept_measure_sets_itself_win(self):
        score = _score(
            attributes(fifths=2, time="4/4", clef=("G", 2)) + note("C", 4, duration=8),
            "<attributes><time><beats>2</beats><beat-type>4</beat-type></time></attributes>" + note("D", 4, duration=4),
        )

        attributes_ = _first_measure(select_measures(score, [2, 2])).find("attributes")

        assert [child.tag for child in attributes_] == ["divisions", "key", "time", "clef"]
        assert attributes_.findtext("time/beats") == "2"

    def test_attributes_after_the_first_note_get_a_new_block_at_the_start(self):
        score = _score(
            attributes(fifths=2, time="4/4", clef=("G", 2)) + note("C", 4, duration=8),
            note("D", 4) + attributes(divisions=None, clef=("F", 4)) + note("D", 3),
        )

        measure = _first_measure(select_measures(score, [2, 2]))

        assert [child.tag for child in measure][:2] == ["attributes", "note"]
        assert [clef.findtext("sign") for clef in measure.iter("clef")] == ["G", "F"]

    def test_clefs_are_carried_per_staff(self):
        piano = (
            "<attributes><divisions>1</divisions><staves>2</staves>"
            '<clef number="1"><sign>G</sign><line>2</line></clef>'
            '<clef number="2"><sign>F</sign><line>4</line></clef></attributes>'
        )
        score = _score(
            piano + note("C", 4, duration=4),
            '<attributes><clef number="2"><sign>G</sign><line>2</line></clef></attributes>' + note("D", 4, duration=4),
            '<attributes><clef number="1"><sign>C</sign><line>3</line></clef></attributes>' + note("E", 4, duration=4),
        )

        attributes_ = _first_measure(select_measures(score, [3, 3])).find("attributes")

        assert [child.tag for child in attributes_] == ["divisions", "staves", "clef", "clef"]
        clefs = {clef.get("number"): clef.findtext("sign") for clef in attributes_.findall("clef")}
        assert clefs == {"1": "C", "2": "G"}

    def test_transposition_is_carried(self):
        # A B-flat clarinet: written D5 sounds C5.
        score = _score(attributes(transpose=(-1, -2)) + note("C", 5), note("D", 5))

        cut = select_measures(score, [2, 2])

        assert describe_score(cut)["parts"][0]["range"] == {"low": "C5", "high": "C5"}
        assert first_pitches(cut)[0]["pitch"] == "C5"

    def test_pickup_alone(self):
        root = parse_score(select_measures(PICKUP, [0, 0]))

        assert _numbers(root) == ["0"]

    def test_suffixed_measures_belong_to_their_number(self):
        score = _score(
            attributes() + note("C", 4), note("D", 4), note("E", 4), note("F", 4), numbers=["11", "12", "12a", "13"]
        )

        assert _numbers(parse_score(select_measures(score, [12, 12]))) == ["12", "12a"]

    def test_parts_follow_the_first_parts_positions(self):
        score = partwise(
            [
                ("P1", "S", None, [attributes() + note("C", 5), note("D", 5), note("E", 5)]),
                ("P2", "A", None, [attributes() + note("C", 4), note("D", 4), note("E", 4)]),
            ],
            numbers=["1", "2", "3"],
        ).replace('<part id="P2"><measure number="1">', '<part id="P2"><measure number="99">')

        root = parse_score(select_measures(score, [1, 1]))

        assert _numbers(root, 1) == ["99"]

    def test_timewise(self):
        cut = select_measures(timewise(SIX_BAR_PARTS, title="Six Bars"), [3, 4])
        root = parse_score(cut)

        assert root.tag == "score-timewise"
        assert [measure.get("number") for measure in root.findall("measure")] == ["3", "4"]
        assert describe_score(cut) == describe_score(select_measures(SIX_BARS, [3, 4]))

    def test_accepts_bytes(self):
        assert describe_score(select_measures(SIX_BARS.encode("utf-8"), (3, 4)))["measures"] == 2

    def test_does_not_carry_rests_or_notes(self):
        score = _score(attributes(time="2/4") + rest(4), note("D", 4, duration=4))

        assert first_pitches(select_measures(score, [2, 2]))[0]["pitch"] == "D4"

    def test_carries_state_into_each_kept_run(self):
        # Two movements numbered from 1: [2, 2] keeps bar 2 of each, after bars in other keys.
        score = _score(
            attributes(fifths=0, time="4/4") + note("C", 4, duration=8),
            note("C", 4, duration=8),
            attributes(divisions=None, fifths=3) + note("A", 4, duration=8),
            note("A", 4, duration=8),
            numbers=["1", "2", "1", "2"],
        )

        root = parse_score(select_measures(score, [2, 2]))

        measures = root.find("part").findall("measure")
        assert [measure.findtext("attributes/key/fifths") for measure in measures] == ["0", "3"]


class TestSelectMeasuresErrors:
    @pytest.mark.parametrize("measures", [[5, 99], [0, 2], [7, 8]])
    def test_out_of_range_names_the_scores_first_and_last_numbers(self, measures):
        with pytest.raises(MeasureRangeError) as caught:
            select_measures(SIX_BARS, measures)

        assert caught.value.error_code == "INVALID_PARAMETER"
        assert caught.value.hint == "This score has measures 1–6."

    def test_reversed_names_the_scores_numbers(self):
        with pytest.raises(MeasureRangeError) as caught:
            select_measures(SIX_BARS, [4, 3])

        assert caught.value.hint == "This score has measures 1–6."

    def test_pickup_score_hint_starts_at_zero(self):
        with pytest.raises(MeasureRangeError) as caught:
            select_measures(PICKUP, [3, 4])

        assert caught.value.hint == "This score has measures 0–2."

    def test_range_holding_no_measure(self):
        score = _score(attributes() + note("C", 4), note("D", 4), note("E", 4), numbers=["1", "2", "5"])

        with pytest.raises(MeasureRangeError) as caught:
            select_measures(score, [3, 4])

        assert caught.value.hint == "This score has measures 1–5."

    def test_score_without_measures(self):
        score = partwise([("P1", "Voice", None, [])])

        with pytest.raises(MeasureRangeError) as caught:
            select_measures(score, [1, 1])

        assert caught.value.hint == "This score has no measures."

    @pytest.mark.parametrize("measures", [[3], ["3", "4"], [True, 4]])
    def test_bad_shape(self, measures):
        with pytest.raises(MeasureRangeError):
            select_measures(SIX_BARS, measures)

    def test_never_echoes_score_text(self):
        score = _score(note("C", 4), note("D", 4), numbers=["Xsecret", "Ysecret"])

        with pytest.raises(MeasureRangeError) as caught:
            select_measures(score, [1, 1])

        assert "secret" not in str(caught.value)
        assert "secret" not in caught.value.hint

    def test_invalid_score_is_invalid_input(self):
        with pytest.raises(ProcessingError) as caught:
            select_measures("<score-partwise>", [1, 1])

        assert caught.value.error_code == "INVALID_INPUT"

