"""The schema-1 evidence record: one manual run's result, as stored in a git note.

Design copied (ideas, not code) from agent-cost-analyzer's G2 release evidence
(docs/plans/release-ui-gate.md there, MIT, same owner). This module only knows the shape of a
record; the verdict is judge.py's and the storage gitnotes.py's.

No personal data: the record holds the OS platform and an input-device *type* from closed lists,
versions, test titles and states, and free-text notes the owner writes. No user or host names,
paths or audio.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime

SCHEMA = 1
STATES = ("passed", "failed", "skipped")
PLATFORMS = ("linux", "macos", "windows", "other")
INPUT_DEVICES = ("built-in", "usb", "bluetooth", "headset", "audio-interface", "other", "unspecified")
KNOWN_SUITES = ("pitch-mic", "claude-desktop-host")

FIELDS = ("schema", "suite", "commit", "dirty", "versions", "environment", "tests", "ranAt", "notes")
_ID = re.compile(r"^([A-Z]+\d+) \S")
_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_RAN_AT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


@dataclass(frozen=True)
class CheckResult:
    """One test or checklist row: its title (stable id first), state and skip reason."""

    title: str
    state: str
    skip_reason: str | None = None


@dataclass(frozen=True)
class Environment:
    platform: str
    input_device: str | None  # None for runs without a microphone


@dataclass(frozen=True)
class Evidence:
    suite: str
    commit: str  # full SHA of HEAD when the run started
    dirty: bool  # tracked or untracked changes (ignored files don't count)
    versions: dict[str, str]
    environment: Environment
    tests: tuple[CheckResult, ...]
    ran_at: str  # UTC, ISO 8601 with Z
    notes: str
    schema: int = field(default=SCHEMA)


class RecordError(ValueError):
    """A note that is not a schema-1 record. ``code`` is ``malformed`` or ``unknown-schema``."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def titled(test_id: str, text: str) -> str:
    """A title the gate can find: the stable id, a space, then the words."""
    return f"{test_id} {text}"


def id_of(title: str) -> str | None:
    """The stable id a title starts with (``PM1``, ``M0``), or None."""
    match = _ID.match(title)
    return match.group(1) if match else None


def to_dict(evidence: Evidence) -> dict:
    return {
        "schema": evidence.schema,
        "suite": evidence.suite,
        "commit": evidence.commit,
        "dirty": evidence.dirty,
        "versions": dict(evidence.versions),
        "environment": {
            "platform": evidence.environment.platform,
            "inputDevice": evidence.environment.input_device,
        },
        "tests": [
            {"title": t.title, "state": t.state, "skipReason": t.skip_reason} for t in evidence.tests
        ],
        "ranAt": evidence.ran_at,
        "notes": evidence.notes,
    }


def from_dict(value) -> Evidence:
    """The record in ``value`` (parsed JSON); raises RecordError naming what is wrong."""
    if not isinstance(value, dict):
        raise _malformed("it is not a JSON object")
    schema = value.get("schema")
    if not isinstance(schema, int) or isinstance(schema, bool):
        raise _malformed("it has no schema version")
    if schema != SCHEMA:
        raise RecordError("unknown-schema", f"The record has schema {schema}; this check reads schema {SCHEMA}.")
    for key in value:
        if key not in FIELDS:
            raise _malformed(f'unknown field "{key}"')
    for key in FIELDS:
        if key not in value:
            raise _malformed(f'missing field "{key}"')
    error = _shape_error(value)
    if error:
        raise _malformed(error)
    env = value["environment"]
    return Evidence(
        suite=value["suite"],
        commit=value["commit"],
        dirty=value["dirty"],
        versions=dict(value["versions"]),
        environment=Environment(env["platform"], env["inputDevice"]),
        tests=tuple(CheckResult(t["title"], t["state"], t["skipReason"]) for t in value["tests"]),
        ran_at=value["ranAt"],
        notes=value["notes"],
    )


def _malformed(why: str) -> RecordError:
    return RecordError("malformed", f"The record is malformed: {why}.")


def _is_text(value) -> bool:
    return isinstance(value, str) and value != "" and "\n" not in value


def _is_test(value) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"title", "state", "skipReason"}
        and _is_text(value["title"])
        and value["state"] in STATES
        and (value["skipReason"] is None or isinstance(value["skipReason"], str))
    )


def _shape_error(value: dict) -> str | None:
    if value["suite"] not in KNOWN_SUITES:
        return f"suite must be one of {', '.join(KNOWN_SUITES)}"
    if not isinstance(value["commit"], str) or not _SHA.match(value["commit"]):
        return "commit must be a full lower-case SHA"
    if not isinstance(value["dirty"], bool):
        return "dirty must be true or false"
    versions = value["versions"]
    if not isinstance(versions, dict) or not all(_is_text(k) and _is_text(v) for k, v in versions.items()):
        return "versions must map names to version text"
    env = value["environment"]
    if not isinstance(env, dict) or set(env) != {"platform", "inputDevice"}:
        return "environment must hold platform and inputDevice"
    if env["platform"] not in PLATFORMS:
        return f"environment.platform must be one of {', '.join(PLATFORMS)}"
    if env["inputDevice"] is not None and env["inputDevice"] not in INPUT_DEVICES:
        return f"environment.inputDevice must be null or one of {', '.join(INPUT_DEVICES)}"
    if not isinstance(value["tests"], list) or not all(_is_test(t) for t in value["tests"]):
        return "tests must each have a title, a state (passed, failed or skipped) and a skipReason (text or null)"
    if not isinstance(value["ranAt"], str) or not _RAN_AT.match(value["ranAt"]) or not _is_date(value["ranAt"]):
        return "ranAt must be a UTC ISO date and time"
    if not isinstance(value["notes"], str):
        return "notes must be text"
    return None


def _is_date(text: str) -> bool:
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True
