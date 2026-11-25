# ui/ — MCP Apps pages

**Last changed:** 2026-11-25 · **Source:** https://github.com/raulkivi/sheet-music-mcp

TypeScript workspace for the [MCP Apps](https://github.com/modelcontextprotocol/ext-apps) UIs that the
servers serve as `ui://` resources. Each app builds to one self-contained HTML file (JS, CSS and the
Verovio WASM inlined; no network references). See
[docs/research/mcp-apps-phase0-spike-plan.md](../docs/research/mcp-apps-phase0-spike-plan.md).

| Path | Contents |
|---|---|
| `packages/kit/` | Shared kit: `HostBridge` (interface; `openLink` asks the host to open a URL, `ui/open-link`), `ExtAppsBridge` (the only importer of `@modelcontextprotocol/ext-apps`), `FakeBridge`, `toolErrors.ts` (error envelope), `theme.ts`, `score/ScoreRenderer.ts` (interface), `score/ScoreView.ts` (Verovio WASM renderer, the only importer of Verovio; `timemap()` carries `measureOn`, `pageOf(id)` finds the page of a note), `score/ServerScoreRenderer.ts` (pages from render-mcp's app-only `render_page_svg`), `score/openScore.ts` (first renderer that starts wins), `score/paging.ts` (pure; `layout-cases.json` is shared with render-mcp's tests), `audio/loadAudio.ts` (pure; pages synth-mcp's app-only `read_audio_chunk` into a `Blob`; `AudioLoadError` carries the server's error code) |
| `apps/score-viewer/` | Score Viewer for render-mcp (`ui://render/score-viewer`); `e2e/` holds its Playwright tests |
| `apps/practice-player/` | Practice Player for synth-mcp (`ui://synth/practice-player`). Pure modules, each with a unit test: `mixer.ts` (solo, mute, volume, presets to `part_gains`), `tempo.ts` (tempo to `playbackRate`, score time to track time, count-in length), `playhead.ts` (timemap to notes and bar), `track.ts` (the synthesize contract, re-render arguments, model context text). `follower.ts` keeps the score and playhead in step, `player.ts` is the controller over the `HostBridge` and the ports in `ports.ts`, `audio.ts` and `dom.ts` are the browser side. Tempo and loop are local; a change of voices, volumes, count-in or timbre is one `synthesize` call. `e2e/` holds its Playwright specs |
| `apps/practice-coach/` | Practice Coach for pitch-mcp (`ui://pitch/practice-coach`): score with a cursor, cents meter, status per note, Start / Stop, server microphone, Report mode. Pure modules: `meter.ts`, `status.ts`, `history.ts`, `polling.ts` (adaptive 5 to 10 Hz, paused while hidden), `scoreMap.ts`; `coach.ts` (behavior over ports), `scoreStage.ts`, `dom.ts`, `scoreDom.ts` |
| `apps/diff-viewer/` | Diff Viewer for comparer-mcp (`ui://comparer/diff-viewer`): `model.ts` (change list, kinds, filters, selection text), `messages.ts` (app-only tool contract, the one `ui/message`, measure lookup), `viewer.ts` (behavior over `HostBridge`), `dom.ts` and `panes.ts` (DOM and the two Verovio panes); `e2e/` holds its Playwright tests |
| `apps/setup-doctor/` | Setup Doctor for all six servers (`ui://<server>/setup-doctor`): shows the hosting server's own `health_check` report. Pure modules `report.ts` (report to view model and plain-text copy) and `clipboard.ts` (async clipboard, legacy copy, manual fallback), behavior in `doctor.ts`, markup in `dom.ts`; `e2e/` holds its Playwright tests |
| `apps/abc-workbench/` | ABC Workbench for musicxml-abc-mcp (`ui://abc/workbench`). One job per module: `review.ts` (which hunks are kept; pure, on the kit's `abc/hunks.ts`), `validation.ts` (`validate_abc` result parsing and the 300 ms debounce state machine), `messages.ts` (tool contract parsing, fixed texts for the model), `workbench.ts` (behavior over `HostBridge`), `dom.ts` (markup only); specs in `e2e/` |
| `test/mock-host/` | Mock MCP Apps host: embeds the built HTML in a sandboxed iframe and speaks the host side with ext-apps' `AppBridge`; logs every message (`window.__host.log`). `mcp-relay.ts` runs the real render-mcp over stdio for specs that ask for it |
| `test/e2e/` | Spec helpers, one job each: `host-helpers.ts` (`openHost`, `messages`, `pageLabel`), `axe.ts` (axe-core in a frame), `focus.ts` (focused control and its ring), `layout.ts` (sideways scroll, frame width), `view-frame.ts` (`ScoreViewerFrame` page object and the U4 `SIZES`), `coach-frame.ts` (`CoachFrame`, the Practice Coach's page object); and the `renderMcp` Playwright fixture (`host-fixture.ts`) |
| `test/theme/` | U3 contrast (R3), Node only, one job per module: `contrast.ts` (colour parsing, WCAG ratio, `var()`/`color-mix` resolution), `css-vars.ts` (reads `style.css` by selector and property; `light-dark()` and `rgba()`), `host-sets.ts` (host sets: Claude light and dark, recorded, and a fallback set per theme for a host that sends nothing), `recordings/claude-desktop.json` (the recorded Claude Desktop variables), and `theme-contrast.test.ts` |
| `test/fixtures/` | MusicXML fixtures |
| `test/perf/` | U7 `budget.ts`: pure `checkBudget` (named breaches) and `summarise` (measure report to metrics), unit-tested in `budget.test.ts` |
| `apps.config.mjs` | The page registry: app name to the server(s) that serve it. The only shared file a new page edits |
| `perf-budget.json` | The U7 limits |
| `scripts/` | `build.mjs` (every registered app, or the ones named), `lib/apps.mjs` (pure registry functions), `has-pages.mjs` (release workflow: does a server ship pages), `check-html.mjs` (AC-R1), `copy-assets.mjs`, `measure.mjs` (measures; Score Viewer only), `perf.mjs` (joins measure, budget and check; needs Node 22.18+ to import the `.ts` module) |

Node 20 or later. Dependency versions are exact and locked in `package-lock.json`.

Visual identity (Kannel) for these pages: [docs/design/design-system.md](../docs/design/design-system.md).
The tokens in `docs/design/tokens.css` are tested by `test/theme/brand-tokens.test.ts`; the mockups are in `docs/design/mockups/`.

## Scripts

| Command | Does |
|---|---|
| `npm ci` | Installs the locked dependencies |
| `npm test` | Vitest unit tests (kit, app logic, AC-R1 checker; Verovio runs in Node) |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run build` | Builds `dist/<name>.html` for every registered app, then fails if one references anything off-origin (AC-R1). `npm run build -- score-viewer` builds only the named app(s) and keeps the other pages in `dist/` |
| `npm run test:e2e` | Builds the mock host's script, then runs Playwright against the built page in the mock host (run `build` first). No retries |
| `npm run build:host` | Builds `test/mock-host/dist/host.js` (the host page and `AppBridge`) |
| `npm run copy-assets` | Copies each built page to every server registered for it, `<server>/src/<pkg>/ui/assets/<name>.html` |
| `npm run measure` | Page size, time to first rendered page (desktop; phone viewport with 4x CPU throttle) and peak JS heap |
| `npm run perf` | `measure`, then checks the numbers against `perf-budget.json`; exits 1 on a breach (run `build` first) |

Playwright uses its cached Chromium; on a fresh machine run `npx playwright install chromium`, or point
Another worktree may already hold port 4173: set `MOCK_HOST_PORT` to run the e2e server on another port.

Playwright uses its cached Chromium; on a fresh machine run `npx playwright install chromium`, or point
`PLAYWRIGHT_CHROMIUM_EXECUTABLE` at a pre-installed Chromium binary. The real-server spec needs
render-mcp's own venv: `uv sync --frozen --extra dev` in `../render-mcp`.

## How the pages reach a server

The built HTML is generated, not committed (decision D1). `npm run build && npm run copy-assets` puts
each page in `<server>/src/<pkg>/ui/assets/<name>.html` for every server registered for it; those
paths are gitignored, the release workflow does the same before `uv build` (only for servers in the
registry, via `scripts/has-pages.mjs`), and hatch packages the files through the server's
`artifacts = ["src/<pkg>/ui/assets/*.html"]` setting, which all six servers already have. Without
the file, a server serves text-only tools.

### Adding a page

1. Create `apps/<name>/` with `index.html`, `main.ts`, `package.json` and `e2e/` (the specs, see U8).
2. Add one entry to `apps.config.mjs`:

   ```js
   "practice-coach": { targets: [{ server: "pitch-mcp", pkg: "pitch_mcp" }] },
   ```

   A page for several servers lists several targets (Setup Doctor: one entry, six targets).

Setup Doctor is that case: `apps.config.mjs` lists all six servers, so `copy-assets` puts the one built page in each server's own package. Nothing else changes: `vite.config.ts`, `build.mjs`, `check-html.mjs`, `copy-assets.mjs`, the mock
host and the release workflow all read the registry. `test/apps-registry.test.ts` fails if a name is
not a safe file name, a target repeats, or an entry has no `apps/<name>/index.html` or points at a
server package that does not exist.

## Two render paths

The MCP Apps default CSP has no `'wasm-unsafe-eval'`, and a resource cannot ask for it, so a host
that enforces the default refuses Verovio's WebAssembly. The Score Viewer therefore tries
`ScoreView` (Verovio WASM in the page) first and, if it cannot start, `ServerScoreRenderer`, which
asks render-mcp's app-only `render_page_svg` tool for each page. Both lay pages out with
`paging.ts` `layoutFor()`, which render-mcp mirrors. Only if both fail does the viewer show its
"cannot start the notation engine" notice. The line under the score names the active engine
(`#engine`, `data-engine="wasm"` or `"server"`).

## Mock host

`node test/mock-host/server.mjs [port]` serves the host page at `/` (after `npm run build:host`) and
the built app at `/app.html` with the CSP a host would apply. `/app.html` serves the Score Viewer;
`/app.html?app=<name>` serves any registered app's `dist/<name>.html` (404 for a name not in the
registry). The page (`host-page.ts`) uses
ext-apps' own `AppBridge` over a `PostMessageTransport`, so the app is tested against the real
protocol code, not a hand-written copy. Its parts each do one job: `options.ts` parses the query,
`scenarios.ts` supplies the tool call that opens the view, `tool-backends.ts` answers the view's
`tools/call`, and `synth-mock.ts` answers synth-mcp's `synthesize`, `read_audio_chunk`, `get_score_xml` and `starting_pitches` (a silent WAV of the right length, per host page), and `message-log.ts` wraps the transport to record every message in either direction
(`window.__host.log`, `window.__host.messages(method)`). `window.__host.resize(width)` and
`setTheme(name)` send host context changes.

With `server=real` the page has no MCP client of its own: it calls `window.mcpHostRelay`, which the
`renderMcp` fixture (`test/e2e/host-fixture.ts`) exposes. The fixture starts render-mcp from its
venv over stdio for the test (`mcp-relay.ts`, with `SHEET_MUSIC_OUTPUT_ROOT` set to a fresh temporary
folder), the host plays the model and runs `render_to_pdf` there, and the view's own calls (such as
`render_page_svg`) are forwarded and recorded in `renderMcp.calls`.

### Options

Query parameters:
`scenario` (`inline-long`, `inline-satb`, `path-only` open with `render_to_pdf`; `health-mixed`, `health-ready`, `health-empty`, `health-error` open with `health_check`, for the Setup Doctor; `practice`, `practice-empty`, `practice-unknown-audio` open with `synthesize`, run by the host on the placeholder synth server, for the Practice Player), `theme` (`light`, `dark`), `csp` (`spec` =
the spec's default policy, `spec-wasm` = the same plus `'wasm-unsafe-eval'`), `host` (`default` = a partial set of variables; `claude` = the recorded Claude Desktop variables, with `theme` picking the `light-dark()` branch; `test/mock-host/host-styles.ts`), `clipboard` (`1` default, `0`: delegate `clipboard-write` to the frame or not, as a host honoring the resource's `clipboardWrite` permission does), `downloads` (`1`/`0`:
`allow-downloads` in the iframe sandbox), `modes` (display modes offered, e.g. `inline,fullscreen`),
`app` (registered app name, default `score-viewer`; a spec opens another page with `openHost(page, { app: "practice-player", scenario: "practice" })`; 404 if that page is not built), `width` (container width in CSS pixels; in fullscreen the view fills the window) and `server`: `1` (default) answers `render_page_svg` with five
placeholder pages, `0` offers no tool, `real` relays to render-mcp (needs the `renderMcp` fixture).
`scenario` (`inline-long`, `inline-satb`, `path-only` open with `render_to_pdf`; `health-mixed`, `health-ready`, `health-empty`, `health-error` open with `health_check`, for the Setup Doctor; `coach`, `coach-loaded`, `coach-empty`, `coach-error` open with `start_practice` for the Practice Coach (answered by `pitch-backend.ts`; `take=steady|closed|lost` scripts the singing, `latency=` delays the pitch tools); `diff`, `diff-identical`, `diff-error` open with `compare_scores`, for the Diff Viewer: a recorded result with changes, with none, or an error), `abc-edit`, `abc-edit-file`, `abc-export`, `abc-no-original`, `abc-error` open the ABC Workbench (answered by `abc-tools.ts`, which stands in for musicxml-abc-mcp), `theme` (`light`, `dark`), `csp` (`spec` =
the spec's default policy, `spec-wasm` = the same plus `'wasm-unsafe-eval'`), `host` (`default` = a partial set of variables; `claude` = the recorded Claude Desktop variables, with `theme` picking the `light-dark()` branch; `test/mock-host/host-styles.ts`), `clipboard` (`1` default, `0`: delegate `clipboard-write` to the frame or not, as a host honoring the resource's `clipboardWrite` permission does), `downloads` (`1`/`0`:
`allow-downloads` in the iframe sandbox), `modes` (display modes offered, e.g. `inline,fullscreen`),
`app` (registered app name, default `score-viewer`; a spec opens another page with `openHost(page, { app: "practice-coach" })`; 404 if that page is not built), `width` (container width in CSS pixels; in fullscreen the view fills the window) and `server`: `1` (default) answers `render_page_svg` with five
placeholder pages (for `app=diff-viewer`: `get_diff_scores` and `export_diff_scores` from `test/fixtures/diff-*`, made with the real comparer-mcp, see `diff-backend.ts`), `0` offers no tool, `real` relays to render-mcp (needs the `renderMcp` fixture).

## Specs and the rows they cover

Plan rows are in [docs/research/ui-and-sound-testing-plan.md](../docs/research/ui-and-sound-testing-plan.md)
section 4; each spec's title starts with its row. Page objects keep selectors out of the specs.
The theme helpers (`contrast.ts`, `css-vars.ts`, `host-sets.ts`) and the Claude recording are copied the same way from `packages/mcp-apps/test/theme/`, `packages/web/src/lib/contrast.ts` and `docs/plans/mcp-apps-spike-results/claude-{light,dark}.json` (recorded 2026-11-07). `axe.ts` and the focus and layout checks are copied with attribution (MIT) from
raulkivi/agent-cost-analyzer (`packages/web/e2e/support/axe.ts`, `packages/mcp-apps/e2e/support/view-frame.ts`).

| Row | Spec |
|---|---|
| AC-R1 self-contained page; AC-R3 Next and Prev; handshake, zoom, theme, resize, download, fullscreen, both render paths | `apps/score-viewer/e2e/score-viewer.spec.ts` |
| R1 / U1 real render-mcp over stdio; U2 real fallback path (spec CSP, pages from the real `render_page_svg`) | `apps/score-viewer/e2e/real-server.spec.ts` |
| U4 six stops (first page; later page zoomed in; download fallback; server page; path-only notice; no-engine notice) at 1280 px, 360 px and fullscreen: axe on the chrome (SVG notation excluded), Tab order with a visible ring, no sideways scroll | `apps/score-viewer/e2e/u4-stops-and-sizes.spec.ts` |
| Practice Coach: render, empty and error states; call log; AC-P5 (cursor visits the bars in order, meter color per status, uncertain never an error); report and Practice again; T1.4 rate, back-off and hidden-tab pause; reduced motion; keyboard | `apps/practice-coach/e2e/practice-coach.spec.ts` |
| Practice Coach U8: six stops (listening, ready, report, empty, error, server lost) at 1280 px and 360 px in the default host, Claude light and Claude dark: axe, Tab order with a ring, no sideways scroll; Claude theme colors | `apps/practice-coach/e2e/stops-and-sizes.spec.ts` |
| Diff Viewer: render (kinds from the operations present, both scores drawn, diff colors), AC-C3 (clicking bar 19 marks and scrolls both panes), filters, Report tab, export and Open in Score Viewer call log (one `ui/message`, one export call), identical / error / no-engine states | `apps/diff-viewer/e2e/diff-viewer.spec.ts` |
| Diff Viewer U8: five stops in the default host, Claude light and Claude dark at 1280 px and 360 px (axe, ring on every Tab stop, no sideways scroll), Tab order, stacked panes at 360 px, X1 keyboard (list arrows, Home/End, Enter, Space on a kind, tab arrows, `aria-live` summary) | `apps/diff-viewer/e2e/u8-states-and-sizes.spec.ts` |
| Setup Doctor: ok/warn/fail, ready, empty and error states; Check again (the `health_check` call); copy report and copy fix (clipboard, legacy and manual fallback); doc link through `ui/open-link`; Claude light and dark with axe; 360 px and 1280 px without sideways scroll; Tab order with a ring, Enter and Space; `aria-live` copy confirmation; reduced motion | `apps/setup-doctor/e2e/setup-doctor.spec.ts` |
| T1.9 Practice Player: render, empty and error states (`INVALID_PARAMETER` for an unknown audio id), transport and seek, tempo with no call (`playbackRate`, pitch kept), one `synthesize` call per mute, solo, volume, preset, count-in or timbre change and the audio swapped in, loop, starting pitches, model context | `apps/practice-player/e2e/player.spec.ts` |
| T1.9 Practice Player: Claude light and dark at 1280 px and 360 px with axe and no sideways scroll, Tab order with a ring, Enter and Space, live region, reduced motion (bar marked, notes not) | `apps/practice-player/e2e/u4-themes-sizes-keyboard.spec.ts` |
| U3 contrast in Node: text 4.5:1 and marks 3:1 (button borders, focus ring, the score's notes and staff lines in `currentColor`) from the real `style.css`, in Claude light, Claude dark and the fallbacks, each failing pair named | `test/theme/theme-contrast.test.ts` |
| U3 the mock host applies the recorded Claude theme and variables, also on a theme change; the U4 stops also run in Claude dark | `apps/score-viewer/e2e/u3-host-themes.spec.ts`, `u4-stops-and-sizes.spec.ts` |
| ABC Workbench: render, Full text, empty (export without an edit), error, lost original; Accept selected / all (one `abc_to_musicxml` call, `return: "auto"`, file chip or download), Reject all, Ask the assistant to revise (call log: `tools/call`, `ui/update-model-context`, `ui/message`) | `apps/abc-workbench/e2e/abc-workbench.spec.ts` |
| AC-A3 error marker on the reported line within 500 ms; `validate_abc` debounced (one call per typing burst); Accept blocked while invalid | `apps/abc-workbench/e2e/live-validation.spec.ts` |
| ABC Workbench: six states x desktop and 360 px x default host, Claude light and Claude dark: axe, a focus ring on every Tab stop, no sideways scroll; recorded theme; X1 reduced motion | `apps/abc-workbench/e2e/themes-and-sizes.spec.ts` |
| X1 ABC Workbench Tab order, arrow keys between changes, Space, Enter, live regions | `apps/abc-workbench/e2e/keyboard.spec.ts` |
| T4.1 Kannel chrome: the 3 px tricolor bar (blue, black, white; the white band follows the theme), the 2 px ring in `--color-ring-primary`, 40 x 40 px minimum on every control at 360 px | `apps/score-viewer/e2e/t41-kannel-chrome.spec.ts` |
| T4.2 Download PDF beside SVG: `get_pdf` then `read_pdf_chunk` through the mock host (placeholder PDF, `pdf-mock.ts`), `%PDF` bytes, status line, keyboard, the D6 fallback without allow-downloads, a host with no tools; the real render-mcp makes a real PDF (`real-server.spec.ts`) | `apps/score-viewer/e2e/t42-pdf-download.spec.ts`, `real-server.spec.ts` |
| T4.3 part filter (one part or all; paging stops at both ends, AC-R3), highlight (the others dim on every page), the PDF made from the shown part, the server render path receives the filtered score, selects reachable by keyboard with a ring, reduced motion drops the fade, a one-part score hides the choices; the real render-mcp pages the filtered score | `apps/score-viewer/e2e/t43-part-filter.spec.ts` |
| U5 Tab reaches every control with a ring; Enter and Space activate Next, Prev, zoom, Fullscreen and Download; focus is kept when a paging button disables itself; arrow and Page keys (there is no page-jump field) | `apps/score-viewer/e2e/u5-keyboard.spec.ts` |

## Performance budget (U7)

`npm run perf` runs `measure.mjs` (it honours `PLAYWRIGHT_CHROMIUM_EXECUTABLE`), compares the result with
`perf-budget.json` and exits 1 on any breach, naming the metric, the measured value and the limit. The
CI step runs it with `continue-on-error: true`: a warning until the numbers are stable on the runner,
then required (drop that line in `.github/workflows/ui.yml`).

Measured 2026-11-11 on the dev machine (Chromium 1243, median of 3 runs, `satb-long.musicxml`), and the limits set from it:

| Metric | Measured | Limit |
|---|---|---|
| Page size (raw) | 8,595,187 bytes | 13,000,000 (1.5x) |
| Desktop, host navigation to first page | 1,045 to 1,252 ms | 2,500 ms (2x) |
| Phone (Pixel 5, 4x CPU throttle), the same | 4,177 to 4,686 ms | 9,000 ms (2x) |
| Peak JS heap (larger of the two profiles) | 25.3 to 26.6 MB | 55,000,000 bytes (2x) |

Revisit the limits after the first CI runs; tighten them if the runner is steady well below them.

## Every new page ships its specs (U8)

Each new MCP Apps page (Recognition Review, Practice Player, ABC Workbench, Practice Coach, Diff Viewer)
ships with a spec file in `apps/<page>/e2e/`, following the Score Viewer's, covering:

- render (the normal state) and the empty and error states;
- both Claude themes (light and dark, `host=claude`);
- 360 px, as well as desktop, with no sideways scroll;
- axe on the chrome, and Tab order with a visible focus ring;
- its call log: the messages the page sends the host (`window.__host.messages(...)`) and the tool calls it makes.

A page is not done, and does not move to done in CLAUDE.md's status table, until those specs pass.

## Not done (U9)

Visual regression (screenshot baselines for the chrome) is deferred; see decision 5 in the testing plan.
