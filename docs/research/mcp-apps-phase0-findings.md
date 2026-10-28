# MCP Apps Phase 0 findings: Score Viewer on render-mcp

**Status:** Automated results final; manual host checks (§4) pending. Recommendation in §6 is
provisional until they are recorded.
**Date:** 2026-10-28
**Branch:** `mcp-apps/phase0`
**Plan:** [mcp-apps-phase0-spike-plan.md](mcp-apps-phase0-spike-plan.md)

---

## 1. What was built

- **Core 0.3.1** (`sheet_music_mcp_core.ui`, `wiring.make_resource_handlers`): UI resources,
  asset sources, the client capability check, and app-only tool filtering in `make_handlers`.
  Moved from render-mcp to the core so every server reuses it.
- **render-mcp:** `ui://render/score-viewer` linked from `render_to_pdf` and `render_to_image`,
  `structuredContent` with `output_schema` on both, and the app-only `render_page_svg`
  (server-side SVG pages for hosts that refuse WebAssembly). `content` is byte-identical
  (golden test).
- **`ui/` workspace:** kit (`HostBridge`, theme, paging, `ScoreRenderer` with a WASM and a server
  implementation), the Score Viewer app, a mock host, and a single-file Vite build.
- **CI:** `ui.yml` (typecheck, Vitest, build with the AC-R1 check, Playwright, wheel packaging
  test); `publish.yml` builds the UI for `render-mcp/v*` tags.

| Suite | Tests |
|---|---|
| Core unit | 455 |
| render-mcp unit / integration | 231 / 12 |
| Other five servers against core 0.3.1 | unchanged (279, 161, 306, 293, 164) |
| Vitest / Playwright | 124 / 13 |

## 2. Measurements

Built page `score-viewer.html`: **8,464,749 bytes raw, 2.34 MB gzip -9**. Verovio's WASM is
embedded as Emscripten's single-file string encoding (8.16 MB), smaller than base64 would be.

Time to first page, 191-bar SATB fixture, median of 3 (`npm run measure`):

| Profile | Frame start → first page | Peak JS heap | Pages |
|---|---|---|---|
| Desktop Chromium, 1000 px | 609 ms | 20.2 MB | 7 |
| Pixel 5 viewport, 4× CPU throttle | 2528 ms | 20.8 MB | 24 |

Heap excludes WASM linear memory. The throttled run disables iframe process isolation.

Server path (`render_page_svg`, same fixture): first page 0.09 s, later pages 0.01 s (the
parsed score is cached by content hash).

## 3. Findings

1. **The spec's default CSP blocks Verovio WASM.** It has no `'wasm-unsafe-eval'`, and
   `McpUiResourceCsp` lets a server declare only domains, so there is no way to ask for it.
   Verovio ships only a WASM build. The viewer therefore tries WASM first and falls back to
   `render_page_svg`; the `#engine` line under the score shows which one runs.
2. **Tempo-mark note glyphs vanish under the spec CSP.** Verovio embeds its text font as a
   `data:` font and the default policy has no `font-src`. No Verovio option avoids it
   (`linked` loads from verovio.org; `none` needs a local font). Noteheads and staves are
   unaffected; dynamics, also text-font glyphs, are probably affected too (not yet checked). Workaround not built: showing the SVG as an
   `<img src="data:image/svg+xml,…">` renders the glyph in Chromium but loses the SVG DOM needed
   for voice highlighting.
3. **Verovio honours MusicXML `color`.** The comparer's `export_annotated_musicxml` output renders
   with `fill`/`color` `#FF8800` on noteheads, so the Diff Viewer can colour changes client-side.
4. **Downloads (D6).** A Blob download works only when the host's iframe sandbox has
   `allow-downloads`; otherwise it fails silently and the page cannot detect it. The viewer
   always shows the saved path and an "Ask the assistant to open it" button after a download.
   ext-apps 2.0.3 also offers a host-mediated `ui/download-file` (host capability
   `downloadFile`), worth adopting where hosts support it.
5. **The SDK ships MCP Apps helpers** (`mcp.server.apps`) for the high-level `MCPServer` only. The
   core reuses its constants and `client_supports_apps`, which also requires the client to list
   `text/html;profile=mcp-app` in `mimeTypes`.
6. **Render tool errors now set `isError: true`.** A tool with an `output_schema` that returns no
   `structuredContent` otherwise makes the Python SDK client raise. Error `content` is unchanged.

## 4. Manual host checks (owner)

Run render-mcp from the spike branch with the UI built:

```bash
cd ui && npm ci && npm run build && npm run copy-assets
```

Client config: `"command": "uv", "args": ["--directory", "<checkout>/render-mcp", "run", "render-mcp"]`.

| # | Check | Claude Desktop / claude.ai | VS Code |
|---|---|---|---|
| M0 | Engine line shows `wasm` or `server` (decides finding 1) | ☐ | ☐ |
| M1 | "Render this score" shows the viewer inline; the model still answers from the text result | ☐ | ☐ |
| M2 | Page navigation and zoom work without a model turn | ☐ | ☐ |
| M3 | Light and dark themes are followed | ☐ | ☐ |
| M4 | Fullscreen works, or the button is hidden | ☐ | ☐ |
| M5 | "Download SVG" saves a file, or the fallback path and button appear (D6) | ☐ | ☐ |
| M6 | First render time (stopwatch) and any host size warnings | ☐ | ☐ |
| M7 | Claude Code CLI (no MCP Apps): tools behave as before; `render_page_svg` is not listed | ☐ | — |

## 5. Proposed size budget (D4)

Per app page: **≤ 10 MB raw and ≤ 3 MB gzip**, first page **≤ 1 s** on desktop and **≤ 3 s** on
a 4×-throttled mid-range phone viewport. Verovio is ~8 MB of that, so apps share one Verovio
build and add little else. `measure.mjs` enforces nothing yet; Phase 1 should fail CI above the
budget.

## 6. Recommendation (provisional)

**Go, with both render paths kept.** The WASM path is fast enough on desktop and acceptable on a
throttled phone; the server path makes the viewer work in hosts that enforce the spec CSP.

What M0 decides for Phases 1–3:

- **Both hosts run WASM:** keep client-side Verovio as the main path (timemap for playback and
  singing cursors comes free). `render_page_svg` stays as the fallback.
- **Either host refuses WASM:** every notation app needs server-side SVG. Move `SvgPageRenderer`
  from render-mcp into the core behind an optional extra (`sheet-music-mcp-core[notation]`, pulling
  the `verovio` wheel), so synth, pitch, comparer, omr and abc reuse it instead of copying it, and
  add a server-side timemap getter for the Practice Player and Coach cursors.
- **A host lacks resource reads, app tool calls or display modes:** pause, record the gap, and
  re-check host releases.

Do not tag a render-mcp release from this branch until §4 is filled in.
