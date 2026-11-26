# Implementation Plan

High-level roadmap for the Choir Music Assistant. Each MCP server has its own detailed `docs/PLAN.md`
in its directory. See [Intro.md](Intro.md) for goals, phases, and data flow.
See [conventions.md](conventions.md) for coding standards all servers must follow.

**Last reviewed:** 2026-08-16

---

## Build Order

```
1. omr-mcp            ✅ mostly complete — integration tests pending
2. synth-mcp          ✅ complete — 64 unit + 7 integration tests pass
3. render-mcp         ✅ complete — 73/73 tests pass
4. musicxml-abc-mcp   ✅ complete — 74/74 tests pass
5. pitch-mcp          ✅ complete (Phase A+B) — 112 unit + 4 integration tests pass
6. comparer-mcp       ✅ complete (Phase 4) — 134/134 tests pass (127 unit + 7 integration)
```

---

## Server Summaries

| Server | Purpose | Goals | Detail |
|--------|---------|-------|--------|
| **omr-mcp** | Converts sheet music images to MusicXML using deep learning OCR | 1 | [omr-mcp/docs/PLAN.md](../omr-mcp/docs/PLAN.md) |
| **synth-mcp** | Synthesizes audio from MusicXML with selectable voice parts and tempo control | 3 | [synth-mcp/docs/PLAN.md](../synth-mcp/docs/PLAN.md) |
| **render-mcp** | Renders MusicXML to high-quality PDF or PNG for printing and display | 2 | [render-mcp/docs/PLAN.md](../render-mcp/docs/PLAN.md) |
| **musicxml-abc-mcp** | Converts between MusicXML and ABC notation so Claude can read and edit scores | LLM bridge | [musicxml-abc-mcp/docs/PLAN.md](../musicxml-abc-mcp/docs/PLAN.md) |
| **pitch-mcp** | Real-time pitch detection from microphone, compared against a reference score | 4, 5, 6 | [pitch-mcp/docs/PLAN.md](../pitch-mcp/docs/PLAN.md) |

---

## Dependencies Between Servers

```
omr-mcp  ──produces MusicXML──►  synth-mcp
                              ►  render-mcp
                              ►  musicxml-abc-mcp
                              ►  pitch-mcp

musicxml-abc-mcp  ──produces edited MusicXML──►  (any of the above)
```

All downstream servers accept MusicXML as a string. The calling client (Claude, web app, or
Android app) is responsible for passing MusicXML between servers. Servers are stateless with
respect to storage.

---

## Phase 2 — Web PoC

Once all five MCP servers are built and tested individually, build a minimal web application that
orchestrates them.

**Stack (provisional):**
- Backend: FastAPI (Python) — acts as MCP client, connects to MCP servers via stdio or SSE
- Frontend: React or plain HTML/JS — keep minimal for PoC
- Real-time: WebSockets for pitch monitoring updates from `pitch-mcp`

**Core screens:**
1. **Scan** — camera capture → omr-mcp → MusicXML stored in session
2. **Score view** — render-mcp → display PNG pages
3. **Practice** — synth-mcp → play selected voice at chosen tempo
4. **Sing** — pitch-mcp → real-time position indicator and pitch accuracy
5. **Export** — render-mcp → download PDF

---

## Phase 3 — Android App

Native Kotlin app targeting Android 10+. Reuses the Phase 2 FastAPI backend (running locally or
on a companion device).

- Camera → omr-mcp
- Microphone → pitch-mcp
- Score pages as images fetched from render-mcp
- Audio playback streamed from synth-mcp
