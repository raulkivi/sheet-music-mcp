# Kannel interactive mockups (Design canvas source)

**Last changed:** 2026-11-11
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
not stored here. Data is sample data, and the colours follow
[../tokens.css](../tokens.css) and [../design-system.md](../design-system.md).
Nothing has been rendered in a browser yet.
