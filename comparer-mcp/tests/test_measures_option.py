"""options.measures, renamed from options.measure_range (docs/research/ux-wave3-plan.md §3.4).

comparer keeps its filter semantics: differences are filtered by printed measure number and the
scores are not cut. options.measure_range (and list_changes's measure_range) stay as deprecated
aliases for one minor release (docs/conventions.md, Deprecated Parameter Names).
"""

import json
import logging

import pytest
from sheet_music_mcp_core import params

from comparer_mcp.engine import ProcessingError, compare
from comparer_mcp.server import INSTRUCTIONS, call_tool, list_tools

OPTIONS_TOOLS = [
    "compare_musicxml",
    "compare_musicxml_files",
    "generate_comparison_report",
    "export_annotated_musicxml",
]


def _score(steps):
    """One Soprano part, one whole note per measure: steps = ["C", "D", ...] for measures 1, 2, ..."""
    measures = "".join(
        f'<measure number="{number}">'
        + (
            "<attributes><divisions>1</divisions>"
            "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
            if number == 1
            else ""
        )
        + f"<note><pitch><step>{step}</step><octave>4</octave></pitch><duration>4</duration>"
        "<type>whole</type></note></measure>"
        for number, step in enumerate(steps, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><score-partwise version="3.1">'
        '<part-list><score-part id="P1"><part-name>Soprano</part-name></score-part></part-list>'
        f'<part id="P1">{measures}</part></score-partwise>'
    )


REFERENCE = _score(["C", "D", "E"])
TARGET = _score(["C", "F", "E"])  # measure 2 changed


@pytest.fixture(autouse=True)
def _fresh_warnings():
    params._warned.clear()
    yield
    params._warned.clear()


def _measure_numbers(result) -> list[int]:
    return [md.measure_number for pd in result.part_diffs for md in pd.measure_diffs]


def _deprecation_warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "deprecated" in r.getMessage()]


class TestEngineOptionsMeasures:
    def test_measures_filters_differences_by_measure_number(self):
        result = compare(REFERENCE, TARGET, options={"measures": [1, 1]})

        assert _measure_numbers(result) == [1]
        assert result.similarity_score == pytest.approx(1.0)

    def test_measures_gives_the_same_result_as_measure_range(self):
        new = compare(REFERENCE, TARGET, options={"measures": [2, 3]})
        old = compare(REFERENCE, TARGET, options={"measure_range": [2, 3]})

        assert new.to_dict() == old.to_dict()
        assert _measure_numbers(new) == [2, 3]

    def test_both_with_different_values_is_invalid(self):
        with pytest.raises(ProcessingError) as excinfo:
            compare(REFERENCE, TARGET, options={"measures": [1, 1], "measure_range": [2, 3]})

        assert excinfo.value.error_code == "INVALID_PARAMETER"

    def test_both_with_equal_values_is_accepted(self):
        result = compare(REFERENCE, TARGET, options={"measures": [2, 2], "measure_range": [2, 2]})

        assert _measure_numbers(result) == [2]

    def test_measure_range_logs_one_deprecation_warning(self, caplog):
        caplog.set_level(logging.WARNING, logger="sheet_music_mcp_core.params")

        compare(REFERENCE, TARGET, options={"measure_range": [1, 1]})
        compare(REFERENCE, TARGET, options={"measure_range": [2, 2]})

        warnings = _deprecation_warnings(caplog)
        assert len(warnings) == 1
        assert "measure_range" in warnings[0] and "measures" in warnings[0]

    def test_measures_logs_no_deprecation_warning(self, caplog):
        caplog.set_level(logging.WARNING, logger="sheet_music_mcp_core.params")

        compare(REFERENCE, TARGET, options={"measures": [1, 1]})

        assert _deprecation_warnings(caplog) == []

    def test_scores_are_not_cut(self):
        # A range past the end of the score filters everything out instead of failing.
        result = compare(REFERENCE, TARGET, options={"measures": [10, 20]})

        assert _measure_numbers(result) == []

    @pytest.mark.parametrize(
        "value",
        [[3, 1], [1], [1, 2, 3], "1-3", [1.5, 2], [True, 2], [-1, 2], 7],
    )
    @pytest.mark.parametrize("key", ["measures", "measure_range"])
    def test_malformed_range_is_invalid_and_names_options_measures(self, key, value):
        with pytest.raises(ProcessingError) as excinfo:
            compare(REFERENCE, TARGET, options={key: value})

        assert excinfo.value.error_code == "INVALID_PARAMETER"
        assert "options.measures" in str(excinfo.value)
        assert excinfo.value.hint


class TestServerOptionsMeasures:
    @pytest.mark.parametrize("tool_name", OPTIONS_TOOLS)
    async def test_options_schema_lists_measures_and_deprecated_measure_range(self, tool_name):
        tool = next(t for t in await list_tools() if t.name == tool_name)
        props = tool.input_schema["properties"]["options"]["properties"]

        assert props["measures"]["type"] == "array"
        assert props["measures"]["minItems"] == 2 and props["measures"]["maxItems"] == 2
        assert props["measure_range"]["description"].startswith("(Deprecated: use `measures`)")

    async def test_compare_musicxml_measures_matches_measure_range(self):
        base = {"reference_xml": REFERENCE, "target_xml": TARGET}
        new = await call_tool("compare_musicxml", {**base, "options": {"measures": [2, 2]}})
        old = await call_tool("compare_musicxml", {**base, "options": {"measure_range": [2, 2]}})

        assert new[0].text == old[0].text

    async def test_reversed_options_measures_returns_invalid_parameter_with_hint(self):
        result = await call_tool(
            "generate_comparison_report",
            {"reference_xml": REFERENCE, "target_xml": TARGET, "options": {"measures": [3, 1]}},
        )
        payload = json.loads(result[0].text)

        assert payload["error_code"] == "INVALID_PARAMETER"
        assert "options.measures" in payload["error"]
        assert payload["hint"]

    async def test_conflicting_options_return_invalid_parameter(self):
        result = await call_tool(
            "export_annotated_musicxml",
            {
                "reference_xml": REFERENCE,
                "target_xml": TARGET,
                "options": {"measures": [1, 1], "measure_range": [1, 2]},
            },
        )

        assert json.loads(result[0].text)["error_code"] == "INVALID_PARAMETER"

    async def test_instructions_name_measures(self):
        assert "measures" in INSTRUCTIONS
        assert "measure_range" not in INSTRUCTIONS


class TestListChangesMeasures:
    async def test_schema_lists_measures_and_deprecated_measure_range(self):
        tool = next(t for t in await list_tools() if t.name == "list_changes")
        props = tool.input_schema["properties"]

        assert props["measures"]["minItems"] == 2 and props["measures"]["maxItems"] == 2
        assert props["measure_range"]["description"].startswith("(Deprecated: use `measures`)")

    async def test_measures_gives_the_same_changes_as_measure_range(self):
        base = {"reference_xml": REFERENCE, "target_xml": TARGET}
        new = await call_tool("list_changes", {**base, "measures": [2, 2]})
        old = await call_tool("list_changes", {**base, "measure_range": [2, 2]})

        assert json.loads(new[0].text)["count"] == 1
        assert new[0].text == old[0].text

    async def test_measures_excludes_unchanged_measures(self):
        result = await call_tool(
            "list_changes", {"reference_xml": REFERENCE, "target_xml": TARGET, "measures": [3, 3]}
        )

        assert json.loads(result[0].text)["count"] == 0

    async def test_conflicting_values_return_invalid_parameter(self):
        result = await call_tool(
            "list_changes",
            {"reference_xml": REFERENCE, "target_xml": TARGET, "measures": [1, 1], "measure_range": [2, 2]},
        )

        assert json.loads(result[0].text)["error_code"] == "INVALID_PARAMETER"

    async def test_measure_range_logs_one_deprecation_warning(self, caplog):
        caplog.set_level(logging.WARNING, logger="sheet_music_mcp_core.params")
        base = {"reference_xml": REFERENCE, "target_xml": TARGET}

        await call_tool("list_changes", {**base, "measure_range": [1, 1]})
        await call_tool("list_changes", {**base, "measure_range": [2, 2]})

        assert len(_deprecation_warnings(caplog)) == 1

    @pytest.mark.parametrize("value", [[3, 1], [1], "1-3", [True, 2]])
    async def test_malformed_measures_returns_invalid_parameter_naming_measures(self, value):
        result = await call_tool(
            "list_changes", {"reference_xml": REFERENCE, "target_xml": TARGET, "measures": value}
        )
        payload = json.loads(result[0].text)

        assert payload["error_code"] == "INVALID_PARAMETER"
        assert "measures" in payload["error"]
        assert payload["hint"]
