"""The git side: the notes ref, and the few commands that read and write it.

Behind a small runner port so the rest never spawns git itself. Nothing here pushes: the owner
pushes the notes ref.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

NOTES_REF = "refs/notes/release-evidence"
PUSH_COMMAND = f"git push origin {NOTES_REF}"
FETCH_COMMAND = f"git fetch origin {NOTES_REF}:{NOTES_REF}"
_REF_ARG = "--ref=release-evidence"


@dataclass(frozen=True)
class GitResult:
    status: int
    stdout: str
    stderr: str


class GitRunner(Protocol):
    def run(self, args: Sequence[str], stdin: str | None = None) -> GitResult: ...


class GitError(RuntimeError):
    pass


class SubprocessGit:
    def __init__(self, cwd: Path | str):
        self.cwd = Path(cwd)

    def run(self, args: Sequence[str], stdin: str | None = None) -> GitResult:
        result = subprocess.run(
            ["git", "-C", str(self.cwd), *args], input=stdin, capture_output=True, text=True
        )
        return GitResult(result.returncode, result.stdout, result.stderr)


def _failure(what: str, result: GitResult) -> GitError:
    return GitError(f"{what}: {result.stderr.strip() or f'git exited with {result.status}'}")


def resolve_commit(git: GitRunner, revision: str) -> str:
    result = git.run(["rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"])
    if result.status != 0:
        raise _failure(f"Can't resolve {revision!r} to a commit", result)
    return result.stdout.strip()


def toplevel(git: GitRunner) -> Path:
    result = git.run(["rev-parse", "--show-toplevel"])
    if result.status != 0:
        raise _failure("Not in a git repository", result)
    return Path(result.stdout.strip()).resolve()


def is_dirty(git: GitRunner) -> bool:
    """Tracked or untracked changes; ignored files (caches, venvs) don't count."""
    result = git.run(["status", "--porcelain", "--untracked-files=normal"])
    if result.status != 0:
        raise _failure("Can't read the working tree's status", result)
    return result.stdout.strip() != ""


def read_note(git: GitRunner, commit: str) -> str | None:
    result = git.run(["notes", _REF_ARG, "show", commit])
    if result.status == 0:
        return result.stdout
    if "no note found" in result.stderr.lower():
        return None
    raise _failure(f"Can't read the release evidence note of {commit}", result)


def write_note(git: GitRunner, commit: str, text: str) -> None:
    """-f: a later run replaces the earlier note."""
    result = git.run(["notes", _REF_ARG, "add", "-f", "-F", "-", commit], stdin=text)
    if result.status != 0:
        raise _failure(f"Can't write the release evidence note on {commit}", result)
