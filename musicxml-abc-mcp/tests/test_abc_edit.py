"""apply_abc_edit engine (C16): replace some bars of one part, keep everything else.

"Identical" for an untouched part means two things, both checked:
- byte-identical: the part's exact source text appears unchanged in the result, and the text
  before and after the edited part is unchanged (DOCTYPE and comments included);
- canonically identical: C14N 2.0 of the part, whitespace-only text stripped, is equal.
"""

import re
import subprocess
import sys

import pytest
from sheet_music_mcp_core.errors import ProcessingError
from sheet_music_mcp_core.scores import describe_score

from musicxml_abc_mcp.abc_edit import apply_abc_edit
from musicxml_abc_mcp.engine import musicxml_to_abc

from .edit_fixtures import (
    EIGHTHS_ABC,
    QUARTERS_ABC,
    SCORE,
    canonical_part,
    measure,
    notes,
    part_text,
)


def _codes(result) -> list[str]:
    return [warning["code"] for warning in result["warnings"]]


# --- Replacing ---------------------------------------------------------------------------------


class TestReplaces:
    def test_target_bars_hold_the_abc_notes(self):
        result = apply_abc_edit(SCORE, "P2", [2, 3], QUARTERS_ABC)

        bar2 = notes(measure(result["musicxml"], "P2", "2"))
        bar3 = notes(measure(result["musicxml"], "P2", "3"))
        assert bar2 == [
            ("C", "0", "5", "quarter", "1"),
            ("B", "0", "4", "quarter", "1"),
            ("A", "0", "4", "quarter", "1"),
            ("G", "0", "4", "quarter", "1"),
        ]
        assert bar3 == [("F", "0", "4", "whole", "4")]

    def test_reports_the_resolved_part_and_bars(self):
        result = apply_abc_edit(SCORE, "Alto", [2, 3], QUARTERS_ABC)

        assert result["part"] == "P2"
        assert result["measures"] == [2, 3]
        assert result["measures_replaced"] == 2

    def test_bars_follow_abc_bar_lines_not_the_meter(self):
        # A hymn bar longer than its time signature: music21 alone would split it in two.
        abc = "X:1\nM:2/2\nL:1/8\nK:C\nc2 B2 A2 G2 | F8 |]"

        result = apply_abc_edit(SCORE, "P2", [2, 3], abc)

        assert len(notes(measure(result["musicxml"], "P2", "2"))) == 4
        assert notes(measure(result["musicxml"], "P2", "3")) == [("F", "0", "4", "whole", "4")]

    def test_short_bars_are_not_merged(self):
        abc = "X:1\nM:4/4\nL:1/8\nK:C\nC2 D2 | E2 F2 G4 |]"

        result = apply_abc_edit(SCORE, "P2", [2, 3], abc)

        assert len(notes(measure(result["musicxml"], "P2", "2"))) == 2
        assert len(notes(measure(result["musicxml"], "P2", "3"))) == 3

    def test_tie_across_a_bar_line(self):
        abc = "X:1\nM:4/4\nL:1/8\nK:C\nc2 B2 A2 G2- | G8 |]"

        result = apply_abc_edit(SCORE, "P2", [2, 3], abc)["musicxml"]
        first = measure(result, "P2", "3").find("note")

        assert first.find("tie").get("type") == "stop"
        assert first.find("notations/tied").get("type") == "stop"

    def test_triplets_get_finer_divisions(self):
        abc = "X:1\nM:4/4\nL:1/8\nK:C\n(3ABc (3def g4 | G8 |]"

        result = apply_abc_edit(SCORE, "P2", [2, 3], abc)["musicxml"]

        assert measure(result, "P2", "2").findtext("attributes/divisions") == "3"
        assert measure(result, "P2", "3").findtext("attributes/divisions") == "1"
        assert apply_abc_edit(SCORE, "P2", [2, 3], abc)["warnings"][-1]["code"] != "MEASURE_DURATION_MISMATCH"

    def test_single_bar(self):
        abc = "X:1\nM:4/4\nL:1/8\nK:C\nG8 |]"
        result = apply_abc_edit(SCORE, "P2", [4, 4], abc)

        assert notes(measure(result["musicxml"], "P2", "4")) == [("G", "0", "4", "whole", "4")]


# --- Keeping everything else -------------------------------------------------------------------


class TestKeepsOtherParts:
    @pytest.mark.parametrize("part_id", ["P1", "P3"])
    def test_untouched_parts_are_byte_identical(self, part_id):
        result = apply_abc_edit(SCORE, "P2", [2, 3], QUARTERS_ABC)

        assert part_text(SCORE, part_id) in result["musicxml"]

    @pytest.mark.parametrize("part_id", ["P1", "P3"])
    def test_untouched_parts_are_canonically_identical(self, part_id):
        result = apply_abc_edit(SCORE, "P2", [2, 3], QUARTERS_ABC)

        assert canonical_part(result["musicxml"], part_id) == canonical_part(SCORE, part_id)

    def test_text_outside_the_edited_part_is_unchanged(self):
        result = apply_abc_edit(SCORE, "P2", [2, 3], QUARTERS_ABC)["musicxml"]
        alto = part_text(SCORE, "P2")
        before, after = SCORE.split(alto)

        assert result.startswith(before)  # declaration, DOCTYPE, comment, part list, soprano
        assert result.endswith(after)  # bass and the closing tag

    def test_untouched_bars_of_the_edited_part_are_byte_identical(self):
        result = apply_abc_edit(SCORE, "P2", [2, 3], QUARTERS_ABC)["musicxml"]
        alto = part_text(SCORE, "P2")
        first = alto[alto.index('<measure number="1"') : alto.index('<measure number="2"')].rstrip()
        last = alto[alto.index('<measure number="4"') : alto.index("</part>")].rstrip()

        assert first in result
        assert last in result


class TestSourceFormatting:
    def test_score_without_line_breaks(self):
        compact = "".join(line.strip() for line in SCORE.splitlines())

        result = apply_abc_edit(compact, "P2", [2, 3], QUARTERS_ABC)["musicxml"]

        assert part_text(compact, "P1") in result
        assert part_text(compact, "P3") in result
        assert "\n" not in part_text(result, "P2")

    def test_empty_self_closing_bar(self):
        alto = part_text(SCORE, "P2")
        empty_last = re.sub(r'<measure number="4">.*?</measure>', '<measure number="4"/>', alto, flags=re.DOTALL)
        score = SCORE.replace(alto, empty_last)

        result = apply_abc_edit(score, "P2", [4, 4], "X:1\nM:4/4\nL:1/8\nK:C\nG8 |]")["musicxml"]

        assert notes(measure(result, "P2", "4")) == [("G", "0", "4", "whole", "4")]
        assert part_text(score, "P3") in result

    def test_declared_encoding_becomes_utf8(self):
        score = SCORE.replace('encoding="UTF-8"', 'encoding="ISO-8859-1"')

        result = apply_abc_edit(score, "P2", [4, 4], "X:1\nM:4/4\nL:1/8\nK:C\nG8 |]")["musicxml"]

        assert result.startswith('<?xml version="1.0" encoding="UTF-8"')


class TestKeepsLayout:
    def test_bar_attributes_and_system_break_survive(self):
        bar3 = measure(apply_abc_edit(SCORE, "P2", [2, 3], QUARTERS_ABC)["musicxml"], "P2", "3")

        assert bar3.get("width") == "250"
        assert bar3.find("print").get("new-system") == "yes"

    def test_no_key_time_clef_or_tempo_from_the_abc_header(self):
        result = apply_abc_edit(SCORE, "P2", [2, 3], QUARTERS_ABC)["musicxml"]

        for number in ("2", "3"):
            bar = measure(result, "P2", number)
            assert bar.find("attributes/key") is None
            assert bar.find("attributes/time") is None
            assert bar.find("attributes/clef") is None
            assert bar.find("direction/direction-type/metronome") is None

    def test_no_final_barline_mid_score(self):
        bar3 = measure(apply_abc_edit(SCORE, "P2", [2, 3], QUARTERS_ABC)["musicxml"], "P2", "3")

        assert bar3.find("barline") is None

    def test_original_final_barline_kept(self):
        abc = "X:1\nM:4/4\nL:1/8\nK:C\nG8"  # no |] in the edit
        bar4 = measure(apply_abc_edit(SCORE, "P2", [4, 4], abc)["musicxml"], "P2", "4")

        assert bar4.find("barline/bar-style").text == "light-heavy"


class TestDivisions:
    def test_durations_rescaled_to_the_part_divisions(self):
        bar2 = measure(apply_abc_edit(SCORE, "P2", [2, 3], QUARTERS_ABC)["musicxml"], "P2", "2")

        assert bar2.find("attributes/divisions") is None
        assert {note.findtext("duration") for note in bar2.iter("note")} == {"1"}

    def test_finer_divisions_set_and_restored(self):
        result = apply_abc_edit(SCORE, "P2", [2, 2], EIGHTHS_ABC)["musicxml"]
        bar2 = measure(result, "P2", "2")
        bar3 = measure(result, "P2", "3")

        assert bar2.findtext("attributes/divisions") == "2"
        assert [note.findtext("duration") for note in bar2.iter("note")] == ["1", "1", "1", "1", "2", "2"]
        # The bar after the edit is back to the part's own divisions.
        assert bar3.findtext("attributes/divisions") == "1"
        assert notes(bar3) == notes(measure(SCORE, "P2", "3"))


# --- Warnings ----------------------------------------------------------------------------------


class TestWarnings:
    def test_dropped_dynamics_lyrics_and_articulations(self):
        result = apply_abc_edit(SCORE, "P2", [2, 3], QUARTERS_ABC)

        by_code = {(w["code"], w["measure"]) for w in result["warnings"]}
        assert ("DYNAMICS_DROPPED", 2) in by_code
        assert ("LYRICS_DROPPED", 2) in by_code
        assert ("LYRICS_DROPPED", 3) in by_code
        assert ("ARTICULATION_DROPPED", 2) in by_code
        assert ("DYNAMICS_DROPPED", 3) not in by_code

    def test_warning_items_follow_the_contract(self):
        result = apply_abc_edit(SCORE, "P2", [2, 3], QUARTERS_ABC)

        for warning in result["warnings"]:
            assert set(warning) == {"code", "severity", "message", "measure", "part"}
            assert warning["severity"] == "warning"
            assert warning["part"] == "P2"
            assert "Alto" not in warning["message"]  # never echo score metadata

    def test_no_warnings_for_a_plain_bar(self):
        abc = "X:1\nM:4/4\nL:1/8\nK:C\nG8 |]"

        assert apply_abc_edit(SCORE, "P2", [4, 4], abc)["warnings"] == []

    def test_bar_length_mismatch(self):
        abc = "X:1\nM:4/4\nL:1/8\nK:C\nG6 |]"  # 3 quarters in a 4/4 bar

        result = apply_abc_edit(SCORE, "P2", [4, 4], abc)

        assert _codes(result) == ["MEASURE_DURATION_MISMATCH"]
        assert result["warnings"][0]["measure"] == 4


# --- Errors ------------------------------------------------------------------------------------


class TestErrors:
    def _error(self, *args) -> ProcessingError:
        with pytest.raises(ProcessingError) as caught:
            apply_abc_edit(*args)
        return caught.value

    def test_reversed_bars(self):
        error = self._error(SCORE, "P2", [3, 2], QUARTERS_ABC)

        assert error.error_code == "INVALID_PARAMETER"
        assert "1–4" in error.hint

    def test_bars_outside_the_score(self):
        error = self._error(SCORE, "P2", [4, 5], QUARTERS_ABC)

        assert error.error_code == "INVALID_PARAMETER"
        assert "1–4" in error.hint

    def test_malformed_range(self):
        assert self._error(SCORE, "P2", [2], QUARTERS_ABC).error_code == "INVALID_PARAMETER"

    def test_unknown_part(self):
        error = self._error(SCORE, "Tenor", [2, 3], QUARTERS_ABC)

        assert error.error_code == "INVALID_PARAMETER"
        assert "Alto (P2)" in error.choices

    def test_unparseable_abc(self):
        error = self._error(SCORE, "P2", [2, 3], "X:1\nK:C\n|||[[[ ((( %%% ")

        assert error.error_code == "INVALID_INPUT"

    def test_empty_abc(self):
        assert self._error(SCORE, "P2", [2, 3], "  ").error_code == "INVALID_INPUT"

    def test_bar_count_mismatch(self):
        error = self._error(SCORE, "P2", [2, 3], "X:1\nM:4/4\nL:1/8\nK:C\nG8 |]")

        assert error.error_code == "INVALID_INPUT"
        assert "2" in error.hint and "1" in error.hint

    def test_several_tunes(self):
        abc = "X:1\nM:4/4\nL:1/8\nK:C\nG8|]\n\nX:2\nM:4/4\nL:1/8\nK:C\nC8|]"
        error = self._error(SCORE, "P2", [4, 4], abc)

        assert error.error_code == "INVALID_INPUT"

    def test_timewise_score(self):
        timewise = (
            '<?xml version="1.0"?><score-timewise><part-list><score-part id="P1">'
            "<part-name>S</part-name></score-part></part-list><measure number=\"1\">"
            '<part id="P1"><note><rest/><duration>4</duration></note></part></measure></score-timewise>'
        )
        error = self._error(timewise, "P1", [1, 1], "X:1\nL:1/8\nK:C\nz8|]")

        assert error.error_code == "INVALID_INPUT"
        assert error.hint

    def test_malformed_score(self):
        error = self._error("<score-partwise><part>", "P1", [1, 1], QUARTERS_ABC)

        assert error.error_code == "INVALID_INPUT"


# --- Round trip --------------------------------------------------------------------------------


class TestRoundTrip:
    def test_unchanged_export_of_bars_keeps_their_notes(self):
        abc = musicxml_to_abc(SCORE, "P2", [2, 3])["abc"]

        result = apply_abc_edit(SCORE, "P2", [2, 3], abc)["musicxml"]

        for number in ("2", "3"):
            assert notes(measure(result, "P2", number)) == notes(measure(SCORE, "P2", number))

    def test_output_is_readable_by_the_exporter(self):
        result = apply_abc_edit(SCORE, "P2", [2, 3], QUARTERS_ABC)["musicxml"]

        assert "c2 B2 A2 G2" in musicxml_to_abc(result, "P2", [2, 3])["abc"]


@pytest.mark.integration
class TestIntegrationSatb:
    """A real four-part score: re-applying an unchanged export of two bars of the second part."""

    def _edit(self):
        from .test_engine import _load_mxl_fixture

        score = _load_mxl_fixture()
        part_ids = [part["id"] for part in describe_score(score)["parts"]]
        abc = musicxml_to_abc(score, part_ids[1], [2, 3])["abc"]
        return score, part_ids, apply_abc_edit(score, part_ids[1], [2, 3], abc)["musicxml"]

    def test_other_parts_identical(self):
        score, part_ids, result = self._edit()

        for part_id in part_ids[:1] + part_ids[2:]:
            assert part_text(score, part_id) in result
            assert canonical_part(result, part_id) == canonical_part(score, part_id)

    def test_edited_bars_keep_their_pitches(self):
        score, part_ids, result = self._edit()

        for number in ("2", "3"):
            before = [found[:3] for found in notes(measure(score, part_ids[1], number))]
            after = [found[:3] for found in notes(measure(result, part_ids[1], number))]
            assert after == before


def test_module_does_not_import_mcp():
    code = "import sys, musicxml_abc_mcp.abc_edit; print(any(m == 'mcp' or m.startswith('mcp.') for m in sys.modules))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)

    assert out.stdout.strip() == "False"
