"""The note body: one record per suite (JSON Lines), the latest run of each suite wins."""

import json

from release_evidence.note import find_record, merge_note
from release_evidence.record import CheckResult, RecordError, to_dict

from .helpers import evidence, record_dict

import pytest


def _lines(note):
    return [json.loads(line) for line in note.splitlines()]


class TestMergeNote:
    def test_new_note_holds_one_line(self):
        note = merge_note(None, evidence())
        assert note.endswith("\n")
        assert _lines(note) == [to_dict(evidence())]

    def test_later_run_of_the_same_suite_replaces_it_pass_or_fail(self):
        first = merge_note(None, evidence())
        failed = evidence(tests=(CheckResult("PM1 x", "failed"),), ran_at="2026-11-12T00:00:00Z")
        assert _lines(merge_note(first, failed)) == [to_dict(failed)]

    def test_other_suites_are_kept(self):
        host = record_dict(suite="claude-desktop-host")
        note = json.dumps(host) + "\n"
        merged = merge_note(note, evidence())
        assert _lines(merged) == [host, to_dict(evidence())]

    def test_unreadable_lines_are_dropped(self):
        merged = merge_note("garbage\n\n[1]\n", evidence())
        assert _lines(merged) == [to_dict(evidence())]


class TestFindRecord:
    def test_finds_the_suite(self):
        assert find_record(merge_note(None, evidence()), "pitch-mic") == evidence()

    def test_absent_suite_is_none(self):
        assert find_record(merge_note(None, evidence()), "claude-desktop-host") is None

    def test_line_that_is_not_json_is_malformed(self):
        with pytest.raises(RecordError) as exc:
            find_record("{oops\n", "pitch-mic")
        assert exc.value.code == "malformed"

    def test_object_without_a_suite_is_malformed(self):
        with pytest.raises(RecordError) as exc:
            find_record('{"schema": 1}\n', "pitch-mic")
        assert exc.value.code == "malformed"

    def test_two_lines_for_one_suite_is_malformed(self):
        line = json.dumps(to_dict(evidence()))
        with pytest.raises(RecordError) as exc:
            find_record(f"{line}\n{line}\n", "pitch-mic")
        assert exc.value.code == "malformed"
