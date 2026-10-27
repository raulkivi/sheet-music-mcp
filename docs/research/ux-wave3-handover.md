# UX Wave 3 handover: practice features

**Date:** 2026-10-27
**State of `main`:** `9eb0c33` (Wave 2 merged as #167). Waves 1 and 2 are done:
[ux-wave1-plan.md](ux-wave1-plan.md), [ux-wave2-plan.md](ux-wave2-plan.md).
**Next step:** done — Wave 3 is implemented, see [ux-wave3-plan.md](ux-wave3-plan.md) (owner answers W3-1…W3-8, outcome in §7).

---

## 1. Where things stand

| Area | State |
|---|---|
| Core library | `sheet-music-mcp-core` 0.2.0 on `main`, **not on PyPI yet**: `errors`, `parts`, `params`, `annotations`, `paths`, `scores` (MCP-free); `content`, `wiring`, `references` (MCP) |
| Servers | All six on the Wave 2 contract: titles and annotation presets, part selector, `musicxml_path` inputs, `return: auto\|path\|inline` producers, `describe_score` |
| Tests (unit) | core 289, omr 164 (+48 skipped), render 147, synth 158, abc 140, pitch 235 (+2 skipped), comparer 239 |
| Dependencies | mcp 2.3.0 everywhere; msgpack 1.2.4 (security); Dependabot #166 also moved omr to onnxruntime 1.31.0 and onnx 1.23.2, **not yet verified with the OMR integration tests** |

### Owner actions before any release

1. Add a PyPI pending publisher for `sheet-music-mcp-core` (workflow `publish.yml`, environment `pypi`).
2. Tag `sheet-music-mcp-core/v0.2.0` (0.1.0 was never published; skip it).
3. Bump and tag the servers (one per push): omr 0.3.0, render 0.3.0, synth 0.3.0, musicxml-abc 0.3.0,
   pitch 0.4.0, comparer 0.3.0. These carry Waves 1 and 2. Changelog notes: [wave 2 §7](ux-wave2-plan.md#7-outcome-and-follow-ups).

### Open items carried over

- **Code scanning:** the owner asked for a review of
  <https://github.com/raulkivi/sheet-music-mcp/security/code-scanning>. The session's GitHub App
  gets HTTP 403 on the code-scanning API (no `security_events` permission), so the alerts have not
  been read. Get the list from the owner (or grant the permission) and triage before Wave 3 code.
- **onnxruntime 1.31** (omr-mcp): run `-m integration` with real samples to confirm oemer's models
  still load under its stricter validation.
- **`scores/` cleanup:** files written by `deliver_score` are never deleted. Owner to decide whether
  a retention setting is wanted.
- **Images and audio** are not yet confined to the read roots (Wave 2 decision W2-3).
- **Deprecated aliases** (`part_id`, `part_ids`, `options.part_filter`) go in each server's next
  minor release after the one that ships Waves 1–2.
- **Known gaps:** synth `output_path` accepts `.mid` but always writes WAV; the abc round trip sets
  `T:` to a generated part ID instead of the title.

---

## 2. Wave 3 scope

From the roadmap ([proposal §8](ux-architecture-and-tool-improvements.md#8-roadmap-and-interplay-with-mcp-apps)):
**C8–C11, C13, B2, C19, C22.** These unlock the Practice Player and Practice Coach apps
([MCP Apps proposal §5.1–5.2](mcp-apps-ux-proposal.md)).

| # | Server | Change | Where it lands today |
|---|---|---|---|
| **B2** | render, synth, abc, pitch (+ comparer rename) | `measures: [start, end]`, inclusive, printed measure numbers. comparer's `measure_range` becomes `measures` with a deprecated alias (`params.aliased`). | Likely a new MCP-free core module `measures` (schema property + music21 measure slicing, duck-typed like `parts`), used by each engine. comparer: `engine._validate_measure_range`. |
| **C8** | synth | `part_gains` 0.0–2.0 per part (MIDI CC7), plus presets. | `synth_mcp/engine.py`: `extract_midi()` builds the MIDI, `synthesize_midi()` renders it. Gains need part IDs from the shared resolver. |
| **C9** | synth | `measures` (B2) and `repeat: 1–20`. | `extract_midi()` |
| **C10** | synth | `count_in_bars` and `metronome: bool` (GM percussion channel 10). | `extract_midi()` |
| **C11** | synth | `timbre: "piano" \| "choir" \| "organ"` (GM programs 0, 52, 19). | `extract_midi()`; today music21 picks the instrument |
| **C13** | synth (new tool) | `starting_pitches(score, parts?)`: short clip of each part's first note, then the chord, plus text "S: D5, A: A4, T: F#4, B: D3". Return the clip as `AudioContent` when under ~200 KB (proposal B4 note). | New tool; the first-note text can come from `scores.describe_score`-style parsing or music21 |
| **C19** | pitch (new tool) | `start_practice(score, part, tempo_bpm?, measures?)` = `load_score` + `start_monitoring` in one call. `SESSION_STATE` preset (opens the microphone). | `pitch_mcp/server.py` handlers for both tools |
| **C22** | pitch | `highlights[]` in summaries in plain language: "flat on the high E's in m.12–14 (−35 c avg)". | `engine.py`: `Session.stop()` (~l.401), `stop_monitoring()` (~l.715), `analyze_recording()` (l.30) summaries |

### Acceptance criteria already written (proposal §7)

- `part_gains={"P2": 0}` puts CC7 = 0 on P2's channel in the generated MIDI.
- `preset="learning", focus_part="Alto"` gives Alto a higher CC7 than every other part.

Write the rest as failing tests in the plan, e.g.: `measures=[3, 4]` renders/plays/exports only those
bars (and an out-of-range or reversed range is `INVALID_PARAMETER` with a hint); `repeat=3` triples the
duration; `count_in_bars=1` adds one bar of clicks before the music; `timbre="organ"` sets program 19
on every melodic channel; `starting_pitches` text matches `describe_score` ranges' first notes;
`start_practice` gives the same session as the two-call flow; a summary with a run of flat notes
yields one highlight naming the measures and average cents.

---

## 3. Process (as in Waves 1 and 2)

1. **Plan doc** `docs/research/ux-wave3-plan.md`: scope, DoD, design (core API first), tests, steps,
   decisions table. Mirror [ux-wave2-plan.md](ux-wave2-plan.md).
2. **Interview** the owner on §4 with AskUserQuestion; record answers as W3-n decisions.
3. **Contract first:** add the `measures` rules (and any new parameter names) to `docs/conventions.md`.
4. **Core first** (one subagent, test-first) if B2 gets a core module; review and commit it.
5. **Servers in parallel**, one subagent per server directory (disjoint files), with a shared brief
   in the scratchpad (see the Wave 2 brief pattern: scope limits, core API, common changes, tests,
   docs, report). Wave 3 is synth- and pitch-heavy, so render/abc get only B2.
6. **Review each diff, run every suite, commit per server**, update root docs and the plan, open the
   PR, watch it (Claude review, security review and `scan` all run on PRs).

---

## 4. Questions for the owner (interview)

1. **C8 presets:** decision D3 ([MCP Apps proposal §10](mcp-apps-ux-proposal.md)) says presets are
   UI-side only and the tool takes just `part_gains`; proposal C8 puts `preset` + `focus_part` on
   the tool. Which? (Tool-side presets help hosts without MCP Apps.)
2. **Learning-track numbers:** keep D3's 1.5 / 0.5 for "learning" and 0 / 1.0 for "karaoke"?
3. **B2 semantics:** printed measure numbers (can repeat, have pickups "0", or suffixes like "12a")
   vs. ordinal positions. Proposal says printed numbers; confirm handling of pickups and repeats.
4. **C10 count-in:** in the score's time signature and tempo? Click sound (GM 37 side stick / 76 wood
   block)? Metronome through the whole track or count-in only by default?
5. **C11 timbre default:** keep music21's instrument (today) or default to piano?
6. **C13 output:** WAV file + `AudioContent` inline, or text only when audio is unavailable
   (no FluidSynth)? Tempo/length of each note?
7. **C22 thresholds:** what counts as "flat/sharp" for a highlight (±25 c like `classify_accuracy`?),
   minimum run length, maximum number of highlights?
8. **Release:** ship Wave 3 in the same server minors as Waves 1–2 if those are still unreleased, or
   release Waves 1–2 first?

---

## 5. Practical notes and gotchas

- **Tests:** per server `VIRTUAL_ENV= .venv/bin/pytest tests -q -m 'not integration' -p no:cacheprovider`.
  After pulling `main`, run `uvx --from 'uv==0.13.6' uv sync --extra dev` in each package first
  (pytest is in the `dev` extra everywhere; plain `uv sync` removes it).
- **Locks:** always relock with `uvx --from 'uv==0.13.6' uv lock` (local uv writes revision 3; repo
  locks are revision 5). Upgrade selectively with `--upgrade-package`.
- **This container:** no soundfont, no libfluidsynth, no `omr-mcp/test_samples/` (gitignored), so
  synth audio, render/synth/comparer integration tests and real OMR cannot run here. pitch
  integration tests do run. C8–C11/C13 need MIDI-level unit tests (inspect the generated MIDI with
  music21 or `mido`-style parsing) rather than audio assertions.
- **Never `git stash`** while subagents are editing the tree; it stashes their work too.
- **Force pushes are blocked** by the session's classifier. When the branch must restart from `main`
  after a squash merge, use `git checkout -B <branch> origin/main && git merge -s ours origin/<branch>`
  and push normally.
- **Hidden-Unicode guard** (`scan` job) fails on literal invisible characters such as U+FEFF in
  source. Write them as escapes (`"\ufeff"`).
- **Untrusted numbers:** anything parsed from a score must go through bounded parsing (see
  `scores._fraction` / `_signed` / `_int`); `Fraction("1e999999999")` is a DoS.
- **Server docs:** no server has `docs/HANDOVER.md`, `docs/PLAN.md` or a changelog in git; Wave notes
  live in each server's `CLAUDE.md`, `.github/copilot-instructions.md`, `docs/requirements.md` and
  `docs/architecture.md`.
- **MCP client roots** only work on protocol ≤ 2025-11-25 connections; on 2026-07-28 the server has
  no back channel (`client_roots` returns `[]`).
- **Commits** end with the Co-Authored-By and Claude-Session lines; squash-merge titles end "(#NNN)".
