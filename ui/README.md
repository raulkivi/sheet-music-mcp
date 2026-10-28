# ui/ — MCP Apps pages

TypeScript workspace for the [MCP Apps](https://github.com/modelcontextprotocol/ext-apps) UIs that the
servers serve as `ui://` resources. Each app builds to one self-contained HTML file (JS, CSS and the
Verovio WASM inlined; no network references). See
[docs/research/mcp-apps-phase0-spike-plan.md](../docs/research/mcp-apps-phase0-spike-plan.md).

| Path | Contents |
|---|---|
| `packages/kit/` | Shared kit: `HostBridge` (interface), `ExtAppsBridge` (the only importer of `@modelcontextprotocol/ext-apps`), `FakeBridge`, `theme.ts`, `score/ScoreView.ts` (the only importer of Verovio), `score/paging.ts` (pure) |
| `apps/score-viewer/` | Score Viewer for render-mcp (`ui://render/score-viewer`); `e2e/` holds its Playwright tests |
| `test/mock-host/` | Host page that embeds the built HTML in a sandboxed iframe, speaks the host side of the postMessage JSON-RPC and logs every message (`window.__host.log`) |
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
| `npm run test:e2e` | Playwright against the built page in the mock host (run `build` first) |
| `npm run copy-assets` | Copies `dist/score-viewer.html` to `../render-mcp/src/render_mcp/ui/assets/` |
| `npm run measure` | Page size, time to first rendered page (desktop; phone viewport with 4x CPU throttle) and peak JS heap |

Playwright uses its cached Chromium; on a fresh machine run `npx playwright install chromium`.

## How the pages reach a server

The built HTML is generated, not committed (decision D1). `npm run build && npm run copy-assets` puts
it in `render-mcp/src/render_mcp/ui/assets/`, which is gitignored; the release workflow does the
same before `uv build`, and hatch packages the file through its `artifacts` setting. Without the
file, render-mcp serves text-only tools.

## Mock host options

`node test/mock-host/server.mjs [port]` serves the host at `/` with these query parameters:
`scenario` (`inline-long`, `inline-satb`, `path-only`), `theme` (`light`, `dark`), `csp` (`spec` =
the spec's default policy, `spec-wasm` = the same plus `'wasm-unsafe-eval'`), `downloads` (`1`/`0`:
`allow-downloads` in the iframe sandbox), `modes` (display modes offered, e.g. `inline,fullscreen`)
and `width` (container width in CSS pixels).
