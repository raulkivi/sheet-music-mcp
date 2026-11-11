"""The release verdict on a commit's note: the list of problems that block, each named.

Blocks: no record for the suite (``missing-note``); a record that is not schema-1 JSON
(``malformed``, ``unknown-schema``); a run on another commit (``wrong-commit``); a dirty tree
(``dirty-tree``); a required test missing, failed or skipped, with or without a reason
(``test-missing``, ``test-failed``, ``test-skipped``); any other failed test (``test-failed``).
"""

from dataclasses import dataclass, field

from .gitnotes import FETCH_COMMAND, NOTES_REF, PUSH_COMMAND
from .note import find_record
from .record import Evidence, RecordError, id_of
from .suites import Suite


@dataclass(frozen=True)
class Problem:
    code: str
    message: str


@dataclass(frozen=True)
class Verdict:
    evidence: Evidence | None
    problems: list[Problem] = field(default_factory=list)


def judge(evidence: Evidence, commit: str, suite: Suite) -> list[Problem]:
    commit = commit.lower()
    problems = []
    if evidence.commit != commit:
        problems.append(Problem("wrong-commit", f"The evidence is for commit {evidence.commit}, not the release commit {commit}."))
    if evidence.dirty:
        problems.append(Problem(
            "dirty-tree",
            "The run's working tree had changes, so it did not test the commit alone: commit or remove them and rerun.",
        ))
    for test_id in suite.required_tests:
        problems.extend(_required(evidence, test_id))
    required = set(suite.required_tests)
    for test in evidence.tests:
        if test.state == "failed" and id_of(test.title) not in required:
            problems.append(Problem("test-failed", f'Test "{test.title}" failed; a red run is not released.'))
    return problems


def _required(evidence: Evidence, test_id: str) -> list[Problem]:
    tests = [t for t in evidence.tests if id_of(t.title) == test_id]
    if not tests:
        return [Problem("test-missing", f"Required test {test_id} is not in the run (renamed, deleted or not collected).")]
    failed = next((t for t in tests if t.state == "failed"), None)
    if failed:
        return [Problem("test-failed", f'Required test {test_id} failed: "{failed.title}".')]
    skipped = next((t for t in tests if t.state == "skipped"), None)
    if skipped:
        reason = "no reason recorded" if skipped.skip_reason is None else f'"{skipped.skip_reason}"'
        return [Problem(
            "test-skipped",
            f"Required test {test_id} was skipped ({reason}). A skip proves nothing about the release: fix the cause and rerun.",
        )]
    return []


def evaluate(note: str | None, commit: str, suite: Suite) -> Verdict:
    """The verdict on ``note`` (the text of the commit's note, None when it has none)."""
    missing = Problem(
        "missing-note",
        f"Commit {commit.lower()} has no {suite.name} evidence ({NOTES_REF}): run the suite {suite.run_hint}, "
        f"then {PUSH_COMMAND}.",
    )
    if note is None:
        return Verdict(None, [missing])
    try:
        evidence = find_record(note, suite.name)
    except RecordError as error:
        return Verdict(None, [Problem(error.code, error.message)])
    if evidence is None:
        return Verdict(None, [missing])
    return Verdict(evidence, judge(evidence, commit, suite))


def render_verdict(commit: str, suite: Suite, verdict: Verdict) -> list[str]:
    lines = [f"Release evidence for {commit.lower()}, suite {suite.name} ({NOTES_REF}):"]
    evidence = verdict.evidence
    if evidence:
        device = evidence.environment.input_device
        lines.append(
            f"  ran {evidence.ran_at} on {evidence.environment.platform}"
            + (f", input device {device}" if device else "")
            + (", working tree had changes" if evidence.dirty else "")
        )
        if evidence.versions:
            lines.append("  versions: " + ", ".join(f"{k} {v}" for k, v in evidence.versions.items()))
        for test in evidence.tests:
            reason = "" if test.skip_reason is None else f" ({test.skip_reason})"
            lines.append(f"  {test.state:<8} {test.title}{reason}")
        if evidence.notes:
            lines.append("  notes:")
            lines.extend(f"    {line}" for line in evidence.notes.splitlines())
    if any(p.code == "missing-note" for p in verdict.problems):
        lines.append(f"If the note was pushed from another clone, fetch it first: {FETCH_COMMAND}")
    if not verdict.problems:
        lines.append("PASS: the release gate accepts this commit.")
        return lines
    count = len(verdict.problems)
    lines.append(f"BLOCKED: {count} problem{'' if count == 1 else 's'}:")
    lines.extend(f"  - [{p.code}] {p.message}" for p in verdict.problems)
    return lines
