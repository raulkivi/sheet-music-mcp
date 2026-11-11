"""The git side, against a real temporary repository (never the project's own)."""

import pytest

from release_evidence.gitnotes import (
    FETCH_COMMAND,
    NOTES_REF,
    PUSH_COMMAND,
    GitError,
    SubprocessGit,
    is_dirty,
    read_note,
    resolve_commit,
    toplevel,
    write_note,
)

from .helpers import git, make_repo


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path / "repo")


@pytest.fixture
def runner(repo):
    return SubprocessGit(repo)


def test_commands_name_the_notes_ref():
    assert NOTES_REF == "refs/notes/release-evidence"
    assert PUSH_COMMAND == "git push origin refs/notes/release-evidence"
    assert FETCH_COMMAND == "git fetch origin refs/notes/release-evidence:refs/notes/release-evidence"


class TestResolve:
    def test_head_is_the_full_sha(self, repo, runner):
        assert resolve_commit(runner, "HEAD") == git(repo, "rev-parse", "HEAD")

    def test_unknown_revision(self, runner):
        with pytest.raises(GitError):
            resolve_commit(runner, "no-such-branch")

    def test_option_like_revision_is_not_an_option(self, runner):
        with pytest.raises(GitError):
            resolve_commit(runner, "--all")

    def test_toplevel(self, repo, runner):
        assert toplevel(runner) == repo.resolve()


class TestDirty:
    def test_clean(self, runner):
        assert is_dirty(runner) is False

    def test_tracked_change(self, repo, runner):
        (repo / "README").write_text("changed\n")
        assert is_dirty(runner) is True

    def test_untracked_file(self, repo, runner):
        (repo / "new.txt").write_text("x")
        assert is_dirty(runner) is True

    def test_ignored_file_does_not_count(self, repo, runner):
        (repo / "ignored").mkdir()
        (repo / "ignored" / "cache").write_text("x")
        assert is_dirty(runner) is False


class TestNotes:
    def test_no_note(self, runner):
        assert read_note(runner, resolve_commit(runner, "HEAD")) is None

    def test_write_then_read(self, runner):
        head = resolve_commit(runner, "HEAD")
        write_note(runner, head, '{"a": 1}\n')
        assert read_note(runner, head) == '{"a": 1}\n'

    def test_note_lives_under_the_release_evidence_ref(self, repo, runner):
        head = resolve_commit(runner, "HEAD")
        write_note(runner, head, "x\n")
        assert git(repo, "notes", "--ref=release-evidence", "show", head) == "x"
        assert git(repo, "notes", "list") == ""  # not the default notes ref

    def test_latest_write_wins(self, runner):
        head = resolve_commit(runner, "HEAD")
        write_note(runner, head, "first\n")
        write_note(runner, head, "second\n")
        assert read_note(runner, head) == "second\n"

    def test_writing_a_note_leaves_the_tree_clean(self, runner):
        write_note(runner, resolve_commit(runner, "HEAD"), "x\n")
        assert is_dirty(runner) is False

    def test_read_on_a_bad_commit_raises(self, runner):
        with pytest.raises(GitError):
            read_note(runner, "no-such-rev")

    def test_not_a_repository(self, tmp_path):
        with pytest.raises(GitError):
            resolve_commit(SubprocessGit(tmp_path), "HEAD")
