"""The release verdict: every blocking rule, each problem named."""

import json

from release_evidence.judge import evaluate, judge, render_verdict
from release_evidence.note import merge_note
from release_evidence.record import CheckResult, to_dict
from release_evidence.suites import Suite

from .helpers import OTHER_SHA, SHA, evidence, record_dict

PITCH = Suite("pitch-mic", required_tests=("PM1", "PM2"), run_hint="run the manual suite")


def _codes(problems):
    return [p.code for p in problems]


def _note(*records) -> str:
    return "\n".join(json.dumps(r) for r in records) + "\n"


class TestJudge:
    def test_clean_pass(self):
        assert judge(evidence(), SHA, PITCH) == []

    def test_wrong_commit(self):
        problems = judge(evidence(commit=OTHER_SHA), SHA, PITCH)
        assert _codes(problems) == ["wrong-commit"]
        assert OTHER_SHA in problems[0].message and SHA in problems[0].message

    def test_upper_case_release_commit_still_matches(self):
        assert judge(evidence(), SHA.upper(), PITCH) == []

    def test_dirty_tree(self):
        assert _codes(judge(evidence(dirty=True), SHA, PITCH)) == ["dirty-tree"]

    def test_required_test_missing(self):
        problems = judge(evidence(tests=(CheckResult("PM1 x", "passed"),)), SHA, PITCH)
        assert _codes(problems) == ["test-missing"]
        assert "PM2" in problems[0].message

    def test_required_test_failed(self):
        tests = (CheckResult("PM1 x", "failed"), CheckResult("PM2 y", "passed"))
        problems = judge(evidence(tests=tests), SHA, PITCH)
        assert _codes(problems) == ["test-failed"]
        assert "PM1" in problems[0].message

    def test_required_test_skipped_with_a_reason_blocks_and_quotes_it(self):
        tests = (CheckResult("PM1 x", "passed"), CheckResult("PM2 y", "skipped", "no microphone"))
        problems = judge(evidence(tests=tests), SHA, PITCH)
        assert _codes(problems) == ["test-skipped"]
        assert "PM2" in problems[0].message and "no microphone" in problems[0].message

    def test_required_test_skipped_without_a_reason_blocks(self):
        tests = (CheckResult("PM1 x", "passed"), CheckResult("PM2 y", "skipped"))
        problems = judge(evidence(tests=tests), SHA, PITCH)
        assert _codes(problems) == ["test-skipped"]
        assert "no reason recorded" in problems[0].message

    def test_any_failed_test_blocks_even_if_not_required(self):
        tests = evidence().tests + (CheckResult("extra check", "failed"),)
        problems = judge(evidence(tests=tests), SHA, PITCH)
        assert _codes(problems) == ["test-failed"]
        assert "extra check" in problems[0].message

    def test_a_test_that_is_not_required_may_skip(self):
        tests = evidence().tests + (CheckResult("PM9 optional", "skipped", "later"),)
        assert judge(evidence(tests=tests), SHA, PITCH) == []

    def test_every_problem_is_listed(self):
        tests = (CheckResult("PM1 x", "skipped"), CheckResult("other", "failed"))
        problems = judge(evidence(commit=OTHER_SHA, dirty=True, tests=tests), SHA, PITCH)
        assert _codes(problems) == ["wrong-commit", "dirty-tree", "test-skipped", "test-missing", "test-failed"]


class TestEvaluate:
    def test_no_note(self):
        verdict = evaluate(None, SHA, PITCH)
        assert _codes(verdict.problems) == ["missing-note"]
        assert "run the manual suite" in verdict.problems[0].message
        assert verdict.evidence is None

    def test_note_without_this_suite(self):
        note = _note(record_dict(suite="claude-desktop-host"))
        verdict = evaluate(note, SHA, PITCH)
        assert _codes(verdict.problems) == ["missing-note"]
        assert "pitch-mic" in verdict.problems[0].message

    def test_passing_note(self):
        verdict = evaluate(merge_note(None, evidence()), SHA, PITCH)
        assert verdict.problems == []
        assert verdict.evidence == evidence()

    def test_not_json(self):
        assert _codes(evaluate("hello\n", SHA, PITCH).problems) == ["malformed"]

    def test_empty_note(self):
        assert _codes(evaluate("", SHA, PITCH).problems) == ["malformed"]

    def test_unknown_schema(self):
        verdict = evaluate(_note(record_dict(schema=2)), SHA, PITCH)
        assert _codes(verdict.problems) == ["unknown-schema"]

    def test_malformed_record_of_this_suite(self):
        verdict = evaluate(_note(record_dict(dirty="no")), SHA, PITCH)
        assert _codes(verdict.problems) == ["malformed"]

    def test_a_broken_record_of_another_suite_does_not_block(self):
        other = record_dict(suite="claude-desktop-host", dirty="no")
        note = _note(other, to_dict(evidence()))
        assert evaluate(note, SHA, PITCH).problems == []

    def test_judges_the_parsed_record(self):
        note = merge_note(None, evidence(dirty=True))
        assert _codes(evaluate(note, SHA, PITCH).problems) == ["dirty-tree"]


class TestRenderVerdict:
    def test_pass(self):
        lines = render_verdict(SHA, PITCH, evaluate(merge_note(None, evidence()), SHA, PITCH))
        text = "\n".join(lines)
        assert SHA in lines[0] and "pitch-mic" in lines[0]
        assert "passed   PM1 load start poll stop" in text
        assert "usb" in text and "linux" in text
        assert lines[-1].startswith("PASS")

    def test_blocked_lists_each_problem_by_code(self):
        verdict = evaluate(merge_note(None, evidence(dirty=True, commit=OTHER_SHA)), SHA, PITCH)
        lines = render_verdict(SHA, PITCH, verdict)
        assert "BLOCKED: 2 problems:" in lines
        assert any("[wrong-commit]" in line for line in lines)
        assert any("[dirty-tree]" in line for line in lines)

    def test_skip_reason_and_notes_are_shown(self):
        tests = (CheckResult("PM1 x", "skipped", "mic busy"),)
        verdict = evaluate(merge_note(None, evidence(tests=tests, notes="retry tomorrow")), SHA, PITCH)
        text = "\n".join(render_verdict(SHA, PITCH, verdict))
        assert "(mic busy)" in text
        assert "retry tomorrow" in text
