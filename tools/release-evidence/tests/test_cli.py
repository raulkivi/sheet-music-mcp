"""The command line, end to end against a temporary repository."""

import json

import pytest

from release_evidence.cli import main
from release_evidence.gitnotes import SubprocessGit, read_note
from release_evidence.note import find_record

from .helpers import git, make_repo

NOW = "2026-11-11T10:00:00Z"


@pytest.fixture
def repo(tmp_path):
    repo = make_repo(tmp_path / "repo")
    (repo / "render-mcp").mkdir()
    (repo / "render-mcp" / "pyproject.toml").write_text('[project]\nname = "render-mcp"\nversion = "0.5.0"\n')
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "render")
    return repo


def _run(repo, *argv, answers=(), capsys=None):
    replies = iter(answers)
    said = []
    code = main(["--repo", str(repo), *argv], ask=lambda prompt: next(replies), say=said.append, now=NOW)
    return code, "\n".join(said)


def _head(repo):
    return git(repo, "rev-parse", "HEAD")


def _results(tmp_path, *entries):
    path = tmp_path / "results.json"
    path.write_text(json.dumps(list(entries)))
    return path


PASSED = [
    {"name": "test_pm1_load_start_poll_stop", "outcome": "passed", "skipReason": None},
    {"name": "test_pm2_tempo_bpm_override_is_accepted", "outcome": "passed", "skipReason": None},
]


class TestHead:
    def test_prints_commit_and_dirty(self, repo):
        code, out = _run(repo, "head")
        assert code == 0
        assert json.loads(out) == {"commit": _head(repo), "dirty": False}


class TestSuiteFor:
    @pytest.mark.parametrize("package, out", [
        ("pitch-mcp", "pitch-mic"), ("render-mcp", "claude-desktop-host"), ("synth-mcp", ""),
    ])
    def test_prints_the_suite_or_nothing(self, repo, package, out):
        assert _run(repo, "suite-for", package) == (0, out)


class TestRecordAndCheck:
    def test_record_writes_the_note_and_prints_verdict_and_push(self, repo, tmp_path):
        code, out = _run(repo, "record", "--suite", "pitch-mic", "--tests", str(_results(tmp_path, *PASSED)),
                         "--version", "pitch-mcp=0.4.0", "--input-device", "usb", "--notes", "fine")
        assert code == 0
        assert "PASS" in out
        assert "git push origin refs/notes/release-evidence" in out
        record = find_record(read_note(SubprocessGit(repo), _head(repo)), "pitch-mic")
        assert record.versions == {"pitch-mcp": "0.4.0"}
        assert record.notes == "fine"
        assert record.ran_at == NOW
        assert [t.title for t in record.tests] == ["PM1 load start poll stop", "PM2 tempo bpm override is accepted"]

    def test_record_never_pushes(self, repo, tmp_path):
        remote = tmp_path / "remote.git"
        git(tmp_path, "init", "-q", "--bare", str(remote))
        git(repo, "remote", "add", "origin", str(remote))
        _run(repo, "record", "--suite", "pitch-mic", "--tests", str(_results(tmp_path, *PASSED)))
        assert git(remote, "for-each-ref") == ""

    def test_check_passes_after_a_clean_record(self, repo, tmp_path):
        _run(repo, "record", "--suite", "pitch-mic", "--tests", str(_results(tmp_path, *PASSED)))
        code, out = _run(repo, "check", "--suite", "pitch-mic", "HEAD")
        assert code == 0
        assert out.splitlines()[-1].startswith("PASS")

    def test_check_without_note_is_blocked(self, repo):
        code, out = _run(repo, "check", "--suite", "pitch-mic")
        assert code == 1
        assert "[missing-note]" in out
        assert "git fetch origin refs/notes/release-evidence" in out

    def test_a_skip_recorded_blocks_the_check(self, repo, tmp_path):
        results = _results(tmp_path, PASSED[0], {**PASSED[1], "outcome": "skipped", "skipReason": "no mic"})
        code, out = _run(repo, "record", "--suite", "pitch-mic", "--tests", str(results))
        assert code == 0  # recorded; the verdict says it would block
        assert "BLOCKED" in out and "[test-skipped]" in out
        assert _run(repo, "check", "--suite", "pitch-mic")[0] == 1

    def test_dirty_at_start_is_recorded(self, repo, tmp_path):
        code, out = _run(repo, "record", "--suite", "pitch-mic", "--tests", str(_results(tmp_path, *PASSED)),
                         "--dirty")
        assert "[dirty-tree]" in out

    def test_dirty_tree_found_at_record_time(self, repo, tmp_path):
        (repo / "scratch.txt").write_text("x")
        _, out = _run(repo, "record", "--suite", "pitch-mic", "--tests", str(_results(tmp_path, *PASSED)))
        assert "[dirty-tree]" in out

    def test_record_on_the_start_commit_not_a_later_head(self, repo, tmp_path):
        start = _head(repo)
        (repo / "later").write_text("x")
        git(repo, "add", "later")
        git(repo, "commit", "-q", "-m", "later")
        _run(repo, "record", "--suite", "pitch-mic", "--tests", str(_results(tmp_path, *PASSED)), "--commit", start)
        assert _run(repo, "check", "--suite", "pitch-mic", start)[0] == 0
        assert "[missing-note]" in _run(repo, "check", "--suite", "pitch-mic", "HEAD")[1]

    def test_unknown_suite_is_a_usage_error(self, repo):
        with pytest.raises(SystemExit) as exc:
            _run(repo, "check", "--suite", "nope")
        assert exc.value.code == 2

    def test_bad_revision_exits_2(self, repo):
        code, out = _run(repo, "check", "--suite", "pitch-mic", "no-such-rev")
        assert code == 2

    def test_github_annotations(self, repo, monkeypatch):
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        _, out = _run(repo, "check", "--suite", "render-mcp".replace("render-mcp", "claude-desktop-host"))
        assert "::error title=Release evidence (missing-note)::" in out


ALL_PASS = ["1.2.3"] + ["p", ""] * 8 + ["done"]


class TestHostChecklist:
    def test_walks_every_row_and_records(self, repo):
        code, out = _run(repo, "host-checklist", answers=ALL_PASS)
        assert code == 0
        assert "PASS" in out and "git push origin refs/notes/release-evidence" in out
        record = find_record(read_note(SubprocessGit(repo), _head(repo)), "claude-desktop-host")
        assert [t.title.split()[0] for t in record.tests] == [f"M{n}" for n in range(8)]
        assert record.versions == {"render-mcp": "0.5.0", "claude-desktop": "1.2.3"}
        assert record.environment.input_device is None
        assert record.notes == "done"

    def test_keeps_the_pitch_record_on_the_same_commit(self, repo, tmp_path):
        _run(repo, "record", "--suite", "pitch-mic", "--tests", str(_results(tmp_path, *PASSED)))
        _run(repo, "host-checklist", answers=ALL_PASS)
        assert _run(repo, "check", "--suite", "pitch-mic")[0] == 0
        assert _run(repo, "check", "--suite", "claude-desktop-host")[0] == 0

    def test_a_skipped_row_blocks(self, repo):
        answers = ["1.2.3", "s", "no dark mode", *(["p", ""] * 7), ""]
        _, out = _run(repo, "host-checklist", answers=answers)
        assert "[test-skipped]" in out and "no dark mode" in out

    def test_claude_version_from_the_flag(self, repo):
        code, _ = _run(repo, "host-checklist", "--claude-version", "1.4.0", answers=ALL_PASS[1:])
        record = find_record(read_note(SubprocessGit(repo), _head(repo)), "claude-desktop-host")
        assert record.versions["claude-desktop"] == "1.4.0"
