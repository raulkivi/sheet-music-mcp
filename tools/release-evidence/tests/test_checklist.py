"""The Claude Desktop host checklist: its data file and the walk through it."""

import json

import pytest

from release_evidence.checklist import ChecklistRow, load_rows, walk
from release_evidence.record import CheckResult, id_of


class TestRows:
    def test_rows_have_unique_stable_ids_in_order(self):
        ids = [row.id for row in load_rows()]
        assert ids == ["M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7"]

    def test_every_row_says_what_to_check(self):
        assert all(len(row.text) > 10 for row in load_rows())

    def test_titles_carry_the_id(self):
        assert all(id_of(row.title) == row.id for row in load_rows())

    def test_load_from_a_file(self, tmp_path):
        path = tmp_path / "rows.json"
        path.write_text(json.dumps({"rows": [{"id": "X1", "text": "Check it", "required": False}]}))
        assert load_rows(path) == [ChecklistRow("X1", "Check it", False)]

    @pytest.mark.parametrize("rows", [
        [{"id": "X1", "text": "a"}, {"id": "X1", "text": "b"}],
        [{"id": "x1", "text": "a"}],
        [{"id": "X1", "text": ""}],
        [{"id": "X1", "text": "a", "extra": 1}],
    ])
    def test_bad_data_is_refused(self, tmp_path, rows):
        path = tmp_path / "rows.json"
        path.write_text(json.dumps({"rows": rows}))
        with pytest.raises(ValueError):
            load_rows(path)


ROWS = [ChecklistRow("M1", "Viewer shows inline", True), ChecklistRow("M2", "Zoom works", True)]


def _walk(answers, rows=ROWS):
    replies = iter(answers)
    said = []
    tests, notes = walk(rows, ask=lambda prompt: next(replies), say=said.append)
    return tests, notes, said


class TestWalk:
    def test_all_pass(self):
        tests, notes, said = _walk(["p", "", "pass", "", ""])
        assert tests == [CheckResult("M1 Viewer shows inline", "passed"), CheckResult("M2 Zoom works", "passed")]
        assert notes == ""
        assert any("M1" in line for line in said)

    def test_fail_records_what_went_wrong_in_the_notes(self):
        tests, notes, _ = _walk(["f", "dark theme ignored", "p", "", ""])
        assert tests[0].state == "failed"
        assert "M1 failed: dark theme ignored" in notes

    def test_skip_asks_for_a_reason(self):
        tests, _, _ = _walk(["s", "no fullscreen on this host", "p", "", ""])
        assert tests[0] == CheckResult("M1 Viewer shows inline", "skipped", "no fullscreen on this host")

    def test_skip_without_reason_keeps_none(self):
        tests, _, _ = _walk(["skip", "", "p", "", ""])
        assert tests[0].skip_reason is None

    def test_unknown_answer_asks_again(self):
        tests, _, said = _walk(["maybe", "P", "", "p", "", ""])
        assert [t.state for t in tests] == ["passed", "passed"]
        assert any("pass, fail or skip" in line for line in said)

    def test_row_note_and_final_notes(self):
        _, notes, _ = _walk(["p", "took 2.1 s", "p", "", "all on macOS 15"])
        assert notes == "M1: took 2.1 s\nall on macOS 15"
