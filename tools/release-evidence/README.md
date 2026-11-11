# release-evidence

Records the manual release checks that CI cannot run, and lets the release workflow refuse a
release without them (P7 in [`docs/research/ui-and-sound-testing-plan.md`](../../docs/research/ui-and-sound-testing-plan.md)).
The design follows agent-cost-analyzer's G2 release evidence. This is a standalone uv project
that uses only the standard library. It is not published to PyPI.

| Package released | Suite it needs | What the owner runs |
|---|---|---|
| `pitch-mcp/v*` | `pitch-mic` | pitch-mcp's real-microphone tests (`-m manual`), required ids PM1, PM2 |
| `render-mcp/v*` | `claude-desktop-host` | the Claude Desktop host checklist, rows M0 to M7 ([data file](src/release_evidence/checklists/claude_desktop_host.json)) |
| anything else | none | not gated |

## How it works

- A run writes a **schema-1 JSON record** with these fields: `schema`, `suite`, `commit` (full SHA of HEAD when the run started), `dirty`, `versions`, `environment` (`platform` and an input-device *type*), `tests` (`title`, `state`, `skipReason`), `ranAt` and `notes`.
- The record never holds user names, host names, paths or audio. The home directory and host name are scrubbed from free text.
- The record is stored as a **git note** under `refs/notes/release-evidence` on the commit the run started on. Each suite gets one line, so one commit can carry both suites. A later run of the same suite replaces the earlier one, pass or fail ("latest run wins").
- Recording prints the verdict and the push command. **Nothing here pushes.**
- `publish.yml` fetches the notes ref and runs `check` on the tagged commit before anything is built.
- The check **blocks** a release for any of these problems, each listed by code: `missing-note`, `malformed`, `unknown-schema`, `wrong-commit`, `dirty-tree`, `test-missing`, `test-failed` (a required test, or any other test), and `test-skipped` (a required test skipped, with or without a reason).

## Recording evidence (owner, once per release commit)

Commit everything first. A dirty tree is recorded and then refused.

### pitch-mcp: real microphone

```bash
cd pitch-mcp
uv sync --extra dev
# Input-device type only: built-in, usb, bluetooth, headset, audio-interface or other.
PITCH_MANUAL_EVIDENCE=1 PITCH_MANUAL_INPUT_DEVICE=usb PITCH_MANUAL_NOTES="sang the reference phrase" \
  VIRTUAL_ENV= .venv/bin/pytest tests/ -v -m manual
```

Sing along with `tests/fixtures/reference.musicxml` while the tests run. The run ends with a `release evidence (pitch-mic)` section that shows the verdict.

### render-mcp: Claude Desktop host checklist

```bash
cd ui && npm ci && npm run build && npm run copy-assets && cd ..
# Point Claude Desktop at <checkout>/render-mcp and restart it, then:
uv run --project tools/release-evidence release-evidence host-checklist
```

For each row, answer `p`, `f` or `s` and add an optional note, such as the render time for M6.

## Checking and pushing

```bash
# The verdict the release workflow will give (exit 0 pass, 1 blocked):
uv run --project tools/release-evidence release-evidence check --suite pitch-mic HEAD
uv run --project tools/release-evidence release-evidence check --suite claude-desktop-host HEAD

# Publish the notes, then push the tag on the same commit:
git push origin refs/notes/release-evidence
git tag pitch-mcp/v0.4.1 && git push origin pitch-mcp/v0.4.1
```

On a fresh clone, fetch the notes before checking:

```bash
git fetch origin refs/notes/release-evidence:refs/notes/release-evidence
```

## Development

```bash
cd tools/release-evidence
uv sync
VIRTUAL_ENV= .venv/bin/pytest -q
```

The modules are kept separate:

- `record.py`: the schema
- `note.py`: one line per suite
- `judge.py`: the verdict
- `gitnotes.py`: the git commands
- `checklist.py` and `checklists/*.json`: the host checklist
- `suites.py`: the required ids, and which package needs which suite
- `collect.py`: building a record and scrubbing it
- `cli.py`: the command line

The tests use temporary git repositories only.

A note is a self-check for the owner. It is not a defence against someone with push access.
