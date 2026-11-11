"""The Claude Desktop host checklist: rows from one data file, and the walk through them.

The walk takes ``ask`` and ``say`` callables, so it is tested with scripted answers; the CLI
passes ``input`` and ``print``.
"""

import json
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Callable

from .record import CheckResult, titled

_ROW_ID = re.compile(r"^[A-Z]+\d+$")
_ROW_KEYS = {"id", "text", "required"}
_ANSWERS = {"p": "passed", "pass": "passed", "f": "failed", "fail": "failed", "s": "skipped", "skip": "skipped"}


@dataclass(frozen=True)
class ChecklistRow:
    id: str
    text: str
    required: bool = True

    @property
    def title(self) -> str:
        return titled(self.id, self.text)


def _data(path: Path | None) -> dict:
    if path is None:
        text = resources.files("release_evidence").joinpath("checklists/claude_desktop_host.json").read_text("utf-8")
    else:
        text = Path(path).read_text("utf-8")
    return json.loads(text)


def setup_text(path: Path | None = None) -> str:
    return _data(path).get("setup", "")


def load_rows(path: Path | None = None) -> list[ChecklistRow]:
    rows, seen = [], set()
    for raw in _data(path)["rows"]:
        if not isinstance(raw, dict) or not set(raw) <= _ROW_KEYS:
            raise ValueError(f"Checklist row {raw!r} has unknown fields.")
        row_id, text = raw.get("id"), raw.get("text")
        if not isinstance(row_id, str) or not _ROW_ID.match(row_id) or row_id in seen:
            raise ValueError(f"Checklist row id {row_id!r} must be unique, like M1.")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Checklist row {row_id} has no text.")
        seen.add(row_id)
        rows.append(ChecklistRow(row_id, text, bool(raw.get("required", True))))
    return rows


def walk(
    rows: list[ChecklistRow], *, ask: Callable[[str], str], say: Callable[[str], None]
) -> tuple[list[CheckResult], str]:
    """Ask pass, fail or skip for each row; return the results and the run's notes."""
    results, notes = [], []
    for row in rows:
        say(f"{row.id}: {row.text}")
        state = _ask_state(ask, say)
        reason = None
        if state == "failed":
            what = ask("  What went wrong? ").strip()
            notes.append(f"{row.id} failed: {what}" if what else f"{row.id} failed")
        elif state == "skipped":
            reason = ask("  Why skipped? (a skip of a required row blocks the release) ").strip() or None
        else:
            note = ask("  Note (optional, e.g. a time or the engine): ").strip()
            if note:
                notes.append(f"{row.id}: {note}")
        results.append(CheckResult(row.title, state, reason))
    final = ask("Notes for the whole run (optional; no names or paths): ").strip()
    if final:
        notes.append(final)
    return results, "\n".join(notes)


def _ask_state(ask, say) -> str:
    while True:
        answer = ask("  [p]ass, [f]ail or [s]kip? ").strip().lower()
        if answer in _ANSWERS:
            return _ANSWERS[answer]
        say("  Please answer pass, fail or skip (p, f or s).")
