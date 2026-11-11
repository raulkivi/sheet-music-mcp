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
| `test/e2e/` | Spec helpers (`host-helpers.ts`: `openHost`, `messages`, `pageLabel`) and the `renderMcp` Playwright fixture (`host-fixture.ts`) |
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
the spec's default policy, `spec-wasm` = the same plus `'wasm-unsafe-eval'`), `downloads` (`1`/`0`:
`allow-downloads` in the iframe sandbox), `modes` (display modes offered, e.g. `inline,fullscreen`),
`width` (container width in CSS pixels) and `server`: `1` (default) answers `render_page_svg` with five
placeholder pages, `0` offers no tool, `real` relays to render-mcp (needs the `renderMcp` fixture).
