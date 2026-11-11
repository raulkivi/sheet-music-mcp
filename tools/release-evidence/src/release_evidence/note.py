"""The body of a commit's evidence note: one record per suite, one JSON object per line.

A commit can be tagged for pitch-mcp and render-mcp, so the note keeps each suite's latest run
side by side. Writing a suite's record replaces that suite's line, pass or fail ("latest run
wins"), keeps the other suites' lines and drops lines that cannot be read.
"""

import json

from .record import Evidence, RecordError, from_dict, to_dict


def merge_note(note: str | None, evidence: Evidence) -> str:
    kept = []
    for line in (note or "").splitlines():
        value = _json(line)
        if isinstance(value, dict) and isinstance(value.get("suite"), str) and value["suite"] != evidence.suite:
            kept.append(line.strip())
    kept.append(json.dumps(to_dict(evidence), ensure_ascii=False, separators=(",", ":")))
    return "\n".join(kept) + "\n"


def find_record(note: str, suite: str) -> Evidence | None:
    """``suite``'s record in the note, None when it has none; RecordError when unreadable.

    A line that is not a JSON object with a suite is malformed: it could have been this suite's.
    A broken record of another suite is that suite's problem and is not parsed here.
    """
    lines = [line for line in note.splitlines() if line.strip()]
    if not lines:
        raise RecordError("malformed", "The release evidence note is empty.")
    found = []
    for line in lines:
        value = _json(line)
        if not isinstance(value, dict) or not isinstance(value.get("suite"), str):
            raise RecordError("malformed", "The release evidence note has a line that is not a record with a suite.")
        if value["suite"] == suite:
            found.append(value)
    if len(found) > 1:
        raise RecordError("malformed", f"The release evidence note holds {len(found)} records for {suite}.")
    return from_dict(found[0]) if found else None


def _json(line: str):
    try:
        return json.loads(line)
    except ValueError:
        return None
