# UI and sound testing: improvement plan

Analysis date: 2026-11-11. Status: **P1 done (U1, U6)**; the other phases are still proposals.

Compared against the testing in `agent-cost-analyzer` (MIT, same owner):
`packages/mcp-apps/e2e/` (Playwright fake MCP Apps host), `packages/mcp-apps/test/theme/` (contrast tests),
`packages/web/e2e/support/axe.ts`, `docs/plans/release-ui-gate.md` (automated pre-release UI gate) and
`scripts/release-evidence/evidence.mts` (recorded evidence for runs that cannot be automated).

---

## 1. Short answer

- **UI: yes, most of it transfers.** The strongest pieces are a fake MCP Apps host built on ext-apps'
  `AppBridge` that talks to the real server over stdio, specs named after acceptance rows, axe and contrast
  checks in every theme, and a rule that a required test which skips blocks a release.
- **Sound: only the process transfers.** `agent-cost-analyzer` has no audio, so there is nothing to copy
  for it. Its useful parts are the evidence record for manual runs and the rule that a skip blocks.
  Audio tests need their own design (section 5).
- **Reuse is cheap.** Both repos are MIT. The reusable code is small (a WCAG contrast function, an axe
  helper, a host page). Copy it with attribution rather than create a cross-repo dependency. Open question 1.

---

## 2. Where sheet-music-mcp is today

### UI (`ui/`)

| Area | Today | Gap |
|---|---|---|
| Pages | One built page: `apps/score-viewer` (render-mcp). Other pages are "not built yet" (CLAUDE.md) | Nothing to test for the other five pages yet |
| Browser tests | 13 Playwright tests in `apps/score-viewer/e2e/`, desktop Chrome only | No phone width, no keyboard, no accessibility scan |
| Host | `test/mock-host/` hand-rolls the postMessage JSON-RPC and logs it in `window.__host` | Not the real protocol library; only `light`/`dark`; the server's fallback path is tested only with five placeholder pages (`server=1`), never with the real render-mcp |
| Theme | `theme=light|dark` query only | No recorded Claude or VS Code colour sets; no contrast check |
| Security | `scripts/check-html.mjs` (AC-R1: no off-origin references), CSP variants in the mock host | Good; keep |
| Performance | `scripts/measure.mjs` prints numbers | Not a gate |
| CI | `ui.yml` runs typecheck, unit, build, e2e, wheel packaging | Playwright `retries: 1` in CI, so a flaky test passes on rerun |

### Sound

| Server | Today | Gap |
|---|---|---|
| synth-mcp | Unit tests use silent WAV headers to check duration. Integration tests check that the WAV exists and is bigger than 44 bytes (`test_engine.py`). Golden JSON covers content, not audio | No check on what the audio contains: pitch, onset timing, level, or whether a part's gain changes its level. Integration needs `SYNTH_SOUNDFONT_PATH` and is not run in CI |
| pitch-mcp | Detector tests on synthetic sines (A4, G4), good. `test_integration.py` uses a sine proxy WAV, not a real voice. `test_manual.py` needs a real microphone and is never run or recorded | No test of grading with realistic singing errors (cents, lateness, octave slips, vibrato, noise). The round-trip doc (`docs/round-trip-testing.md`, priority 2) says this pair is not yet tested with rendered audio |
| All | `tests.yml` runs `-m "not integration"` for every server | No audio test runs in CI at all |

---

## 3. What to reuse from agent-cost-analyzer

| # | Pattern (source) | What it gives sheet-music | Adaptation |
|---|---|---|---|
| R1 | **Fake host on `AppBridge`, real server over stdio** (`packages/mcp-apps/e2e/support/mcp-host.ts`, `host/host-page.ts`) | Replaces the hand-rolled mock. Tests the real protocol, and the real render-mcp `render_page_svg` fallback | Start `render-mcp` as a stdio server per test, as the agent's `mcp-host.ts` starts its server. Keep the mock's `window.__host` log for asserts |
| R2 | **Specs named after acceptance rows** (`e2e/README.md` table) | Each spec traces to an AC (`AC-R1`, `AC-R3` already exist) | Title every spec with its AC id; keep a table like the agent's |
| R3 | **Recorded host theme sets + contrast test** (`test/theme/host-sets.ts`, `theme-contrast.test.ts`: text ≥ 4.5:1, marks ≥ 3:1, computed from the real CSS tokens) | Contrast checked in each host's light and dark, not just a guess | Record Claude's sets from the host as the agent did (`docs/plans/mcp-apps-spike-results/`); the score's own marks (highlights, cursor) get the 3:1 rule |
| R4 | **axe at every stop** (`web/e2e/support/axe.ts`, used in `view-frame.ts`) | Accessibility checked in each state, not once | Same helper; the score is SVG, so exclude the notation subtree and check the chrome around it |
| R5 | **Layout at 360 px, fullscreen, no sideways scroll** (`layout-footer-permissions.spec.ts`) | Phone width is untested today | `host.show(…, { width: 360 })` equivalent |
| R6 | **Call-log asserts** (`support/call-log.ts`: which tools the view called, what the model was sent) | Proves a Next/Prev click makes no server call, and that a view makes only the calls it should | Add a `toolCallsIn` helper to the mock |
| R7 | **Automated pre-release gate** (`docs/plans/release-ui-gate.md`: "every UI check is automated"; required jobs; no retries: "a flaky spec is fixed, not re-run") | Turns the manual host checks in `docs/research/mcp-apps-phase0-findings.md` §4 into named specs or recorded evidence | Adopt the rule; drop CI retries |
| R8 | **Evidence record for runs that can't be automated** (`scripts/release-evidence/evidence.mts`: commit, dirty flag, tool versions, pass/skip per required test, "latest run wins", a skip of a required test blocks) | Real-host checks and the real-microphone run leave an auditable record instead of a sentence in a plan | Same record shape; store as a git note or a JSON file in `docs/research/evidence/` |
| R9 | **Bundle-size and no-forwarding security tests** (`packages/mcp-apps/test/bundle-size.test.ts`, `security/no-forwarding.test.ts`) | Size budget and the "view does not forward data" rule as tests | Add next to `check-html` |

Not transferable: the WebdriverIO VS Code automation (sheet-music's real hosts are Claude and Copilot
Chat, and only the Copilot part needs it, if at all).

---

## 4. UI improvements

- **U1. Protocol-faithful host.** Replace the mock's postMessage code with `AppBridge` (R1). Acceptance:
  the existing 13 specs pass unchanged on it, and one new spec runs `render-mcp` over stdio.
- **U2. Real fallback path.** One spec where WASM is blocked by the CSP (`spec` policy) and the page
  renders through the real `render_page_svg`, not placeholders. Keep the placeholder mode for unit-speed runs.
- **U3. Host themes.** Record Claude light and dark sets, and VS Code Light/Dark/High Contrast if the VS Code
  host is in scope (open question 2). Run contrast tests (R3) on each set.
- **U4. Stops and sizes.** Each spec runs at 1280 px and 360 px, and in fullscreen where the host offers it.
  At each stop: axe (R4), focus visible on Tab, no horizontal scroll.
- **U5. Keyboard.** Next, Prev, zoom and page-jump reachable by Tab with visible focus; Enter activates.
- **U6. No retries in CI.** Set `retries: 0`. A flaky spec is fixed, not re-run (R7).
- **U7. Performance budget as a gate.** Turn `measure.mjs` output into a test with a generous budget on the
  CI runner (time to first page, JS heap). Start as a warning, then make it required once the numbers are stable.
- **U8. Per-page matrix as pages land.** Every new page (Recognition Review, Practice Player, ABC Workbench,
  Practice Coach, Diff Viewer) ships with a spec file in the same shape: render, empty and error state,
  both themes, 360 px, axe, call log. A page is not "done" in CLAUDE.md's status table until its specs pass.
- **U9. Optional visual regression.** Screenshot baselines for the chrome only, not the SVG score (its
  rendering varies by engine). Defer until U1-U5 are in.

---

## 5. Sound improvements

Principle: test what the audio **contains** (timing, pitch, level, structure), not whether a file exists.
Compare against tolerances, not byte-for-byte: fluidsynth and float output can drift between versions.

- **S1. Audio feature module.** A pure, MCP-free module (single responsibility, like `engine.py` in each server)
  that reads a WAV and returns: duration, sample rate, channels, peak, clipped-sample count, RMS per 50 ms window,
  and silence spans. TDD with generated signals (sine, silence, clipped square). No server or soundfont needed.
- **S2. Synth content tests** (uses S1). Assert:
  - the duration matches the MIDI length, including repeats and count-in;
  - no clipping, and no silence where a part sounds;
  - a `part_gains` change moves that part's level and leaves the others alone (this is the Wave 3 learning-track
    promise, and it's testable);
  - note onsets fall within ±20 ms of the MIDI onsets (by cross-correlating the RMS envelope).
- **S3. Pitch round-trip (the existing priority 2 in `round-trip-testing.md`, now a running test).** Render a
  short SATB fixture with synth-mcp, then run pitch-mcp's detector on each part. Assert each note's pitch is
  within ±25 cents and its onset within ±50 ms of the score. This replaces the sine-only proxy for detection.
  Needs a soundfont in CI (open question 4).
- **S4. Grading with a simulated singer.** A test helper (under `tests/`, not `src/`) renders the reference
  phrase with known faults: +25 cents, 150 ms late, octave slip, vibrato, white noise at 20 dB SNR, a breath gap.
  Each case asserts the expected grade and highlight. Deterministic, so it runs in CI. Gives coverage the
  real-voice fixture cannot give on its own.
- **S5. Practice features.** Count-in and metronome clicks: assert event times in the MIDI or click track
  against the tempo, not by listening. Repeat expansion: assert the sequence of bar numbers.
- **S6. Real-voice and real-mic runs, recorded.** These stay manual, as the owner decided for VS Code (R8).
  `test_manual.py` writes an evidence record: commit, device, OS, date, pass/fail per test, notes. A
  release or doc check reads it. Recording a real take for `tests/fixtures/` stays open (`pitch-mcp/docs/HANDOVER.md`
  step 4).
- **S7. CI jobs.**
  - pitch-mcp `-m integration`: numpy only, deterministic, so it can run in CI.
  - synth-mcp `-m integration`: `apt install libfluidsynth3`, and a cached soundfont if licence allows (open question 4).
  - `-m manual` never runs in CI.

---

## 6. Phased plan

Each code task starts with a failing test (TDD). Exceptions, recorded in the PR: workflow YAML and browser
configuration, which only a real run can test.

| Phase | Task | Size | Depends | Exit |
|---|---|---|---|---|
| P0 | Decisions in section 7; check soundfont licence | low | — | Answers recorded here |
| P1 ✅ | U1 + U6: `AppBridge` host, real `render-mcp` over stdio, no CI retries | medium | P0 | Existing 13 specs green on the new host; one real-server spec green |
| P2 ✅ | U2, U4, U5: real fallback path, 360 px, axe, keyboard | medium | P1 | Each AC id has a spec; CI job green |
| P3 ✅ | U3: host theme sets and contrast (R3) | medium | P1 | Contrast tests green in each recorded set |
| P4 | S1 + S2: audio feature module and synth content tests | medium | — | Module unit-tested; synth integration asserts content (done 2026-11-11: `synth-mcp/tests/audio_features.py` + `test_audio_content.py`; content tests unrun here, no soundfont; onset check deferred to P6) |
| P5 ✅ | S4 + S7 (pitch part): simulated-singer grading, pitch integration job in CI | medium | — | Each fault case has a spec; integration job green (done 2026-11-11: 6 fault cases as unit tests in `pitch-mcp/tests/test_simulated_singer.py`, 2 defects (3 strict xfail tests) recorded in `pitch-mcp/docs/todo.md`; job `pitch-integration` added, not yet run on GitHub) |
| P6 | S3 + S7 (synth part): pitch round-trip, soundfont in CI | medium-high | P4, P5, P0 | Round-trip green in CI (done 2026-11-11, not yet run on GitHub: `pitch-mcp/tests/test_round_trip.py` green locally for all 4 parts; job `synth-integration` installs `timgm6mb-soundfont` (GPL-2) by apt; the +-20 ms onset check found a 2.27 ms/s drift, which was the test's own window timing (fixed in `tests/audio_features.py`), and part gains found a 7.7 dB drop (CC7 mapping fixed); see `pitch-mcp/docs/todo.md`) |
| P7 ✅ | S5, S6, R7/R8 evidence record | medium | P4 | Manual runs write records; a check reads them (done 2026-11-11: `synth-mcp/tests/test_practice_timing.py`; `tools/release-evidence`; `publish.yml` job `evidence`) |
| P8 | U7, U8 (per page, with each page), U9 optional | ongoing | P2 | Each new page ships its spec file (U7 and the U8 rule done 2026-11-11; U9 deferred, decision 5; U8 specs follow with each page) |

P1 status (2026-11-11): done. The 13 existing specs and the new real-server spec
(`apps/score-viewer/e2e/real-server.spec.ts`) pass on the `AppBridge` host, and `retries` is 0.
Not TDD (browser plumbing that only a real run tests): `playwright.config.ts`, `host-page.ts`, the
host's vite build and the `ui.yml` step order (render-mcp's venv is now installed before e2e).

P2 status (2026-11-11): done locally (CI run pending). U2 was already covered by `real-server.spec.ts`.
`u4-stops-and-sizes.spec.ts` checks six stops at 1280 px, 360 px and fullscreen (18 tests: axe on the
chrome with the notation excluded, Tab order with a visible ring, no sideways scroll);
`u5-keyboard.spec.ts` (7 tests) covers Tab, Enter and Space. They found two defects, fixed test-first:
Prev's visible text was not part of its name (axe `label-content-name-mismatch`; now "‹ Previous"), and
focus was lost when Next or Prev disabled itself at the end (now handed to the other button). There is
no page-jump control; the arrow and Page keys are tested instead. axe-core 4.14.0 added (exact pin).
Not TDD: the mock host's fullscreen sizing (`host-page.ts`, `index.html`) and the spec helpers.

P3 status (2026-11-11): done locally. `ui/test/theme/` holds the contrast helpers, the recorded Claude light and
dark sets (`recordings/claude-desktop.json`, copied from agent-cost-analyzer, recorded 2026-11-07) and a fallback set
per theme; `theme-contrast.test.ts` reads the real `style.css` (60 checks). It found one real failure, fixed
test-first: the button border (`--color-border-primary`) reached only 1.5:1 to 2.9:1 on every set, now
`--color-text-secondary`. The mock host takes `host=claude` and the U4 stops also run in Claude dark (36 tests).
VS Code sets stay out of scope (Claude Desktop is the only real host). Not TDD: the mock host's `host-page.ts` wiring
and `u3-host-themes.spec.ts`, which tests that wiring.

P7 status (2026-11-11): done locally (the gate runs on the next `pitch-mcp/v*` or `render-mcp/v*` tag). S5:
`synth-mcp/tests/test_practice_timing.py` (31 tests, MIDI only) adds what `test_practice_midi.py` did not cover:
click onsets in seconds through the tempo map (tempo change, tempo factor, 6/8, repeat), clicks across a meter
change, written repeats and volta endings as printed bar numbers, and part gains as CC7 with velocities untouched.
It found one defect, fixed test-first: with volta endings and `repeat` > 1 (no clicks), every pass after the first
played the first ending again; `extract_midi` now expands written repeats before `repeat_music`. S6/R8:
`tools/release-evidence` (own uv project, stdlib only, not published) mirrors agent-cost-analyzer's G2 design: a
schema-1 record (commit, dirty, versions, platform and input-device type, tests, ranAt, notes; no names or paths)
in a git note under `refs/notes/release-evidence`, one line per suite, latest run wins; never pushes. Suites:
`pitch-mic` (`-m manual` with `PITCH_MANUAL_EVIDENCE=1`, required PM1 and PM2) and `claude-desktop-host` (CLI
walk of the §4 rows M0 to M7 from one data file). R7: `publish.yml`'s `evidence` job (no id-token) runs before
`publish` and gates pitch-mcp and render-mcp only; `release-evidence.yml` runs the tool's 156 tests. Not TDD: the
workflow YAML, the conftest hooks and the interactive terminal prompts (the walk itself is tested with scripted
answers); both were run once against a scratch clone.

P8 status (2026-11-11): U7 and the U8 rule done locally; U9 stays deferred (decision 5). `npm run perf` checks
`measure.mjs` output against `ui/perf-budget.json` (limits 1.5x to 2x the measured values, recorded in `ui/README.md`);
`ui.yml` runs it after the build with `continue-on-error: true` until the runner's numbers are stable. The comparison
(`ui/test/perf/budget.ts`, 8 tests) was written test-first. Not TDD: `measure.mjs`, `perf.mjs` and the YAML step. U8 is
now a written rule in `ui/README.md`; the per-page specs land with each page.

Design: keep each test's seam an interface, as `ui/packages/kit` already does with `HostBridge`. The fake and real
hosts implement the same port, and the synth test reaches the pitch detector through an interface, not an import.
Each module has one reason to change (feature extraction does not know about MCP or soundfonts).

---

## 7. Decisions (interview, 2026-11-11)

1. **Shared code:** copy the contrast and axe helpers with attribution (both MIT). No shared package for now.
2. **Real host for manual checks:** Claude Desktop, matching `mcp-apps-phase0-findings.md` §4. VS Code Copilot Chat is out of scope.
3. **Real singing take:** not soon. S4 (simulated singer) is the grading test until a real take exists.
4. **Soundfont in CI:** cache `TimGM6mb.sf2` if its licence allows. Check the licence before the P6 work starts.
5. **Visual regression:** deferred (U9). No screenshot baselines yet.
6. **Priority:** UI harness first (P1-P2), then sound (P4-P5), then the round trip (P6).
7. **Manual-run evidence:** record and check. Manual runs write an evidence record, and a release check refuses a release without one (S6, P7).
