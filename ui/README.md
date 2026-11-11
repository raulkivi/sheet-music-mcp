# ui/ — MCP Apps pages

TypeScript workspace for the [MCP Apps](https://github.com/modelcontextprotocol/ext-apps) UIs that the
servers serve as `ui://` resources. Each app builds to one self-contained HTML file (JS, CSS and the
Verovio WASM inlined; no network references). See
[docs/research/mcp-apps-phase0-spike-plan.md](../docs/research/mcp-apps-phase0-spike-plan.md).

| Path | Contents |
|---|---|
| `packages/kit/` | Shared kit: `HostBridge` (interface), `ExtAppsBridge` (the only importer of `@modelcontextprotocol/ext-apps`), `FakeBridge`, `toolErrors.ts` (error envelope), `theme.ts`, `score/ScoreRenderer.ts` (interface), `score/ScoreView.ts` (Verovio WASM renderer, the only importer of Verovio), `score/ServerScoreRenderer.ts` (pages from render-mcp's app-only `render_page_svg`), `score/openScore.ts` (first renderer that starts wins), `score/paging.ts` (pure; `layout-cases.json` is shared with render-mcp's tests) |
| `apps/score-viewer/` | Score Viewer for render-mcp (`ui://render/score-viewer`); `e2e/` holds its Playwright tests |
| `test/mock-host/` | Mock MCP Apps host: embeds the built HTML in a sandboxed iframe and speaks the host side with ext-apps' `AppBridge`; logs every message (`window.__host.log`). `mcp-relay.ts` runs the real render-mcp over stdio for specs that ask for it |
| `test/e2e/` | Spec helpers, one job each: `host-helpers.ts` (`openHost`, `messages`, `pageLabel`), `axe.ts` (axe-core in a frame), `focus.ts` (focused control and its ring), `layout.ts` (sideways scroll, frame width), `view-frame.ts` (`ScoreViewerFrame` page object and the U4 `SIZES`); and the `renderMcp` Playwright fixture (`host-fixture.ts`) |
| `test/theme/` | U3 contrast (R3), Node only, one job per module: `contrast.ts` (colour parsing, WCAG ratio, `var()`/`color-mix` resolution), `css-vars.ts` (reads `style.css` by selector and property; `light-dark()` and `rgba()`), `host-sets.ts` (host sets: Claude light and dark, recorded, and a fallback set per theme for a host that sends nothing), `recordings/claude-desktop.json` (the recorded Claude Desktop variables), and `theme-contrast.test.ts` |
| `test/fixtures/` | MusicXML fixtures |
| `scripts/` | `check-html.mjs` (AC-R1), `copy-assets.mjs`, `measure.mjs` |

Node 20 or later. Dependency versions are exact and locked in `package-lock.json`.

## Scripts

| Command | Does |
|---|---|
| `npm ci` | Installs the locked dependencies |
| `npm test` | Vitest unit tests (kit, app logic, AC-R1 checker; Verovio runs in Node) |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run build` | Builds `dist/score-viewer.html`, then fails if it references anything off-origin (AC-R1) |
| `npm run test:e2e` | Builds the mock host's script, then runs Playwright against the built page in the mock host (run `build` first). No retries |
| `npm run build:host` | Builds `test/mock-host/dist/host.js` (the host page and `AppBridge`) |
| `npm run copy-assets` | Copies `dist/score-viewer.html` to `../render-mcp/src/render_mcp/ui/assets/` |
| `npm run measure` | Page size, time to first rendered page (desktop; phone viewport with 4x CPU throttle) and peak JS heap |

Playwright uses its cached Chromium; on a fresh machine run `npx playwright install chromium`, or point
`PLAYWRIGHT_CHROMIUM_EXECUTABLE` at a pre-installed Chromium binary. The real-server spec needs
render-mcp's own venv: `uv sync --frozen --extra dev` in `../render-mcp`.

## How the pages reach a server

The built HTML is generated, not committed (decision D1). `npm run build && npm run copy-assets` puts
it in `render-mcp/src/render_mcp/ui/assets/`, which is gitignored; the release workflow does the
same before `uv build`, and hatch packages the file through its `artifacts` setting. Without the
file, render-mcp serves text-only tools.

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
the built app at `/app.html` with the CSP a host would apply. The page (`host-page.ts`) uses
ext-apps' own `AppBridge` over a `PostMessageTransport`, so the app is tested against the real
protocol code, not a hand-written copy. Its parts each do one job: `options.ts` parses the query,
`scenarios.ts` supplies the tool call that opens the view, `tool-backends.ts` answers the view's
`tools/call`, and `message-log.ts` wraps the transport to record every message in either direction
(`window.__host.log`, `window.__host.messages(method)`). `window.__host.resize(width)` and
`setTheme(name)` send host context changes.

With `server=real` the page has no MCP client of its own: it calls `window.mcpHostRelay`, which the
`renderMcp` fixture (`test/e2e/host-fixture.ts`) exposes. The fixture starts render-mcp from its
venv over stdio for the test (`mcp-relay.ts`, with `SHEET_MUSIC_OUTPUT_ROOT` set to a fresh temporary
folder), the host plays the model and runs `render_to_pdf` there, and the view's own calls (such as
`render_page_svg`) are forwarded and recorded in `renderMcp.calls`.

### Options

Query parameters:
`scenario` (`inline-long`, `inline-satb`, `path-only`), `theme` (`light`, `dark`), `csp` (`spec` =
the spec's default policy, `spec-wasm` = the same plus `'wasm-unsafe-eval'`), `host` (`default` = a partial set of variables; `claude` = the recorded Claude Desktop variables, with `theme` picking the `light-dark()` branch; `test/mock-host/host-styles.ts`), `downloads` (`1`/`0`:
`allow-downloads` in the iframe sandbox), `modes` (display modes offered, e.g. `inline,fullscreen`),
`width` (container width in CSS pixels; in fullscreen the view fills the window) and `server`: `1` (default) answers `render_page_svg` with five
placeholder pages, `0` offers no tool, `real` relays to render-mcp (needs the `renderMcp` fixture).

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
| U3 contrast in Node: text 4.5:1 and marks 3:1 (button borders, focus ring, the score's notes and staff lines in `currentColor`) from the real `style.css`, in Claude light, Claude dark and the fallbacks, each failing pair named | `test/theme/theme-contrast.test.ts` |
| U3 the mock host applies the recorded Claude theme and variables, also on a theme change; the U4 stops also run in Claude dark | `apps/score-viewer/e2e/u3-host-themes.spec.ts`, `u4-stops-and-sizes.spec.ts` |
| U5 Tab reaches every control with a ring; Enter and Space activate Next, Prev, zoom, Fullscreen and Download; focus is kept when a paging button disables itself; arrow and Page keys (there is no page-jump field) | `apps/score-viewer/e2e/u5-keyboard.spec.ts` |
