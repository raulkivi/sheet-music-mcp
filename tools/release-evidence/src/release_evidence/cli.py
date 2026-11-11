"""Command line: record evidence, walk the host checklist, and check a commit for a release.

    release-evidence head                          commit and dirty flag now, as JSON
    release-evidence suite-for PACKAGE             the suite a package's release needs, or nothing
    release-evidence check --suite S [REV]         the gate (exit 0 pass, 1 blocked, 2 error)
    release-evidence record --suite S --tests F    write a pytest run's record (pitch-mcp conftest)
    release-evidence host-checklist                walk the Claude Desktop checklist and record it

Recording writes a git note under refs/notes/release-evidence and prints the verdict and the push
command. Nothing here pushes.
"""

import argparse
import json
import os
import tomllib
from pathlib import Path
from typing import Callable, Sequence

from .checklist import load_rows, setup_text, walk
from .collect import build_evidence, parse_versions, results_from_pytest
from .gitnotes import PUSH_COMMAND, GitError, SubprocessGit, is_dirty, read_note, resolve_commit, toplevel, write_note
from .judge import evaluate, judge, render_verdict, Verdict
from .note import merge_note
from .record import INPUT_DEVICES, Evidence
from .suites import SUITES, suite_for_package


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="release-evidence", description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", default=".", help="the git checkout (default: the current directory)")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("head", help="print the commit and dirty flag as JSON")

    suite_for = commands.add_parser("suite-for", help="print the suite a package's release needs")
    suite_for.add_argument("package")

    check = commands.add_parser("check", help="judge a commit's evidence for a suite")
    check.add_argument("--suite", required=True, choices=sorted(SUITES))
    check.add_argument("revision", nargs="?", default="HEAD")

    record = commands.add_parser("record", help="record a pytest run (written by pitch-mcp's conftest)")
    record.add_argument("--suite", required=True, choices=sorted(SUITES))
    record.add_argument("--tests", required=True, type=Path, help="JSON list of {name, outcome, skipReason}")
    record.add_argument("--commit", help="the commit the run started on (default: HEAD now)")
    record.add_argument("--dirty", action="store_true", help="the tree was dirty when the run started")
    record.add_argument("--version", action="append", default=[], metavar="NAME=VERSION")
    record.add_argument("--input-device", choices=INPUT_DEVICES)
    record.add_argument("--notes", default="")

    host = commands.add_parser("host-checklist", help="walk the Claude Desktop host checklist")
    host.add_argument("--claude-version", help="Claude Desktop's version (asked when left out)")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    ask: Callable[[str], str] = input,
    say: Callable[[str], None] = print,
    now: str | None = None,
) -> int:
    args = _parser().parse_args(argv)
    git = SubprocessGit(args.repo)
    try:
        if args.command == "head":
            say(json.dumps({"commit": resolve_commit(git, "HEAD"), "dirty": is_dirty(git)}))
            return 0
        if args.command == "suite-for":
            suite = suite_for_package(args.package)
            say(suite.name if suite else "")
            return 0
        if args.command == "check":
            return _check(git, args, say)
        if args.command == "record":
            return _record(git, args, say, now)
        return _host_checklist(git, args, ask, say, now)
    except (GitError, ValueError, OSError) as error:
        say(f"error: {error}")
        return 2


def _check(git, args, say) -> int:
    suite = SUITES[args.suite]
    commit = resolve_commit(git, args.revision)
    verdict = evaluate(read_note(git, commit), commit, suite)
    for line in render_verdict(commit, suite, verdict):
        say(line)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        for problem in verdict.problems:
            say(f"::error title=Release evidence ({problem.code})::{problem.message}")
    return 0 if not verdict.problems else 1


def _record(git, args, say, now) -> int:
    suite = SUITES[args.suite]
    commit = resolve_commit(git, args.commit or "HEAD")
    entries = json.loads(args.tests.read_text("utf-8"))
    evidence = build_evidence(
        suite=suite,
        commit=commit,
        # Dirty at the start, or changed by the run itself.
        dirty=args.dirty or is_dirty(git),
        versions=parse_versions(args.version),
        tests=results_from_pytest(entries),
        notes=args.notes,
        input_device=args.input_device,
        now=now,
    )
    _store(git, evidence, say)
    return 0


def _host_checklist(git, args, ask, say, now) -> int:
    suite = SUITES["claude-desktop-host"]
    commit = resolve_commit(git, "HEAD")
    dirty_at_start = is_dirty(git)
    say(f"Claude Desktop host checklist on {commit}{' (working tree has changes: the gate will refuse it)' if dirty_at_start else ''}.")
    if setup_text():
        say(f"Setup: {setup_text()}")
    claude = args.claude_version or ask("Claude Desktop version (Claude menu, About): ").strip()
    versions = {"render-mcp": _package_version(toplevel(git), "render-mcp"), "claude-desktop": claude or "unknown"}
    tests, notes = walk(load_rows(), ask=ask, say=say)
    evidence = build_evidence(
        suite=suite,
        commit=commit,
        dirty=dirty_at_start or is_dirty(git),
        versions=versions,
        tests=tests,
        notes=notes,
        input_device=None,
        now=now,
    )
    _store(git, evidence, say)
    return 0


def _package_version(root: Path, package: str) -> str:
    try:
        with open(root / package / "pyproject.toml", "rb") as f:
            return tomllib.load(f)["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "unknown"


def _store(git, evidence: Evidence, say) -> None:
    write_note(git, evidence.commit, merge_note(read_note(git, evidence.commit), evidence))
    suite = SUITES[evidence.suite]
    verdict = Verdict(evidence, judge(evidence, evidence.commit, suite))
    say(f"Recorded {suite.name} evidence on {evidence.commit} (latest run wins).")
    for line in render_verdict(evidence.commit, suite, verdict):
        say(line)
    say(f"Nothing was pushed. To publish the evidence: {PUSH_COMMAND}")

