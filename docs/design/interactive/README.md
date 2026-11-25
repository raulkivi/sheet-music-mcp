# Kannel interactive mockups (Design canvas source)

**Last changed:** 2026-11-25
**Source:** https://github.com/raulkivi/sheet-music-mcp

This is the canonical Kannel mockup set; [mockups/](../mockups/) is superseded.

Source of the clickable Kannel prototypes published as a Design canvas
(one artboard per MCP App, plus a start page). The published canvas is the
live copy; these files are its source.

| File | Contents |
|---|---|
| `canvas.json` | The canvas index: artboard frames, order, title |
| `Main.dc.html` | Start page with links to every app |
| `ScoreViewer.dc.html` | Score Viewer: page turns, zoom, theme, download |
| `PracticePlayer.dc.html` | Practice Player: play, parts, tempo, loop, playhead |
| `RecognitionReview.dc.html` | Recognition Review: engine, re-run, issues, accept |
| `AbcWorkbench.dc.html` | ABC Workbench: change keep or undo, accept or reject |
| `PracticeCoach.dc.html` | Practice Coach: start or stop, simulated pitch meter, history |
| `DiffViewer.dc.html` | Diff Viewer: kind filters, change selection, report and export |
| `SetupDoctor.dc.html` | Setup Doctor: fix-it actions, all-ready state |

The artboards load `./support.js`, which the Design runtime provides; it is
not stored here. The colors follow [../tokens.css](../tokens.css) and
[../design-system.md](../design-system.md).
Nothing has been rendered in a browser yet.

## Sample data

The data lives in `fixtures/`, one JSON file per board, shaped like the
server's `structuredContent` (`Main.dc.html` and `canvas.json` hold none):

| Board | Fixture |
|---|---|
| `ScoreViewer.dc.html` | `fixtures/score-viewer.json` |
| `PracticePlayer.dc.html` | `fixtures/practice-player.json` |
| `RecognitionReview.dc.html` | `fixtures/recognition-review.json` |
| `AbcWorkbench.dc.html` | `fixtures/abc-workbench.json` |
| `PracticeCoach.dc.html` | `fixtures/practice-coach.json` |
| `DiffViewer.dc.html` | `fixtures/diff-viewer.json` |
| `SetupDoctor.dc.html` | `fixtures/setup-doctor.json` |

The boards hold no sample data in their visible markup. Each board
embeds its fixture in an `<script type="application/json" id="fixture">`
block, because `fetch()` fails when a file is opened from disk. The block is a
copy of the fixture file: after editing a fixture, copy it into the board
too.

Fields that are not server output are marked here, so no one reads them as
`structuredContent`:

- `score-viewer.json`: `zoom` is the default zoom, not server output.
- `practice-player.json`: `loop` and `count_in` are control defaults.
- `recognition-review.json`: `current_page`, `staves_by_engine` and the
  warning `code` values are the board's view; the warning shape follows
  `WARNINGS_SCHEMA`.
- `abc-workbench.json`: `original_abc`, `proposed_abc` and `changed_lines`
  are the board's view of the score text; `warnings` follows `_WARNING_ITEMS`.
- `practice-coach.json`: `frames` replays `position` snapshots in order;
  `history` is the board's view of recent measures.
- `diff-viewer.json`: `changes` is a flat list the board derives from
  `ComparisonResult` (`part_diffs`); the kinds are the board's labels.
- `setup-doctor.json`: `checks` follows `HealthCheck`; `servers` and
  `checked_label` are the board's header.

The staff drawings on the boards are placeholder graphics, not data.
