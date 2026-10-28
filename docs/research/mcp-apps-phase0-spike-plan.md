# MCP Apps Phase 0 spike: Score Viewer on render-mcp

**Status:** Steps 1–9 and the code side of 12 done on `mcp-apps/phase0` (core 0.3.1 UI module and
app-only visibility, render-mcp linking and `render_page_svg`, `ui/` kit and Score Viewer with both
render paths, wheel packaging). Open: CI (step 10), measurements report (11), manual host checks (§6).
**Date:** 2026-10-27
**Parent:** [mcp-apps-ux-proposal.md](mcp-apps-ux-proposal.md) (roadmap phase 0; decisions D1–D7)
**Server:** `render-mcp` only, plus the shared `ui` module in `sheet-music-mcp-core` (0.3.1). The other five servers are untouched.

---

## 1. Goal

Prove the whole MCP Apps path once, on the smallest useful app, before building the P0 apps:

1. A Python server serves a `ui://` resource and links tools to it, without changing what
   text-only clients see.
2. A shared TypeScript UI kit renders MusicXML with Verovio inside the host sandbox.
3. CI builds the HTML and ships it inside the wheel (D1).
4. It works in **Claude Desktop / claude.ai and VS Code** (D5).
5. Measure what the decisions still depend on: bundle size and load time (D4), Blob downloads
   from the iframe (D6), Verovio colour support (§5.4 of the proposal), and Verovio timemap
   availability (needed by the Phase 1 Practice Player).

### In scope

- `render_to_pdf` and `render_to_image` link to `ui://render/score-viewer`.
- Score Viewer: page navigation, zoom, re-flow on resize, theme, and a "Download SVG" button
  (client-side Blob, used to test D6 without building a server-side artifact store).
- The `ui/` workspace with a host bridge, `ScoreView`, a mock host and Playwright tests.
- CI: a UI test and build job, plus a UI build step in `publish.yml` before `uv build`.
- A findings report with measurements and a go/no-go recommendation.

### Out of scope (later phases)

- `get_pdf` and the `ArtifactStore` (Score Viewer polish, roadmap phase 2).
- Voice highlighting and thumbnails.
- Any other server.
- Trimming `content` for UI-capable clients.
- A PyPI release. The spike merges to `main` but is not tagged until the findings are reviewed.

---

## 2. Definition of done

| # | Criterion | Verified by |
|---|---|---|
| DoD-1 | All existing render-mcp tests (unit and integration) pass unchanged. `content` of both render tools is byte-identical to before. | pytest (default run) |
| DoD-2 | `tools/list` shows `_meta.ui.resourceUri == "ui://render/score-viewer"` on both render tools **when the asset is packaged**, and no `_meta.ui` when it is not. | pytest, in-memory `Client` |
| DoD-3 | `resources/read ui://render/score-viewer` returns one item with `mimeType "text/html;profile=mcp-app"`, or a clear error when the asset is missing (D1). | pytest |
| DoD-4 | Both tools return `structuredContent` that validates against their new `output_schema`. | pytest |
| DoD-5 | UI unit tests (Vitest) and mock-host browser tests (Playwright) pass in CI. | `ui.yml` workflow |
| DoD-6 | The built wheel contains `render_mcp/ui/assets/score-viewer.html`, and the HTML has no off-origin `src` or `href` (AC-R1). | CI step plus a pytest that runs only against the built wheel |
| DoD-7 | Manual checklist passes in Claude Desktop and VS Code ([§6](#6-manual-host-checklist)). | Recorded in the findings report |
| DoD-8 | The findings report is published, with measured numbers and a proposed size budget (D4). | `docs/research/mcp-apps-phase0-findings.md` |
| DoD-9 | render-mcp `docs/requirements.md` and `docs/architecture.md` are updated. The local `HANDOVER.md` and `PLAN.md` are updated per the document policy. | Review |

---

## 3. Design (SOLID)

### 3.1 Python (shared core + render-mcp)

**Decision (2026-10-28):** the UI resource plumbing lives in the shared core,
`sheet_music_mcp_core.ui` (core 0.3.1), so all six servers reuse it. render-mcp only registers its
resource and links its tools.

```
sheet-music-mcp-core/src/sheet_music_mcp_core/
  ui.py              # DONE UiResource, UiRegistry, AssetSource protocol   [S, O, D]
  wiring.py          # DONE make_resource_handlers(registry) -> (on_list_resources, on_read_resource)

render-mcp/src/render_mcp/
  engine.py          # unchanged; no mcp import
  presenter.py       # NEW  engine result -> (content, structured_content)   [S]
  ui/assets/         # NEW  score-viewer.html, built by CI, gitignored (D1)
  server.py          # registers the resource; Tool(meta=...); Server(..., on_list_resources=...,
                     #   on_read_resource=...) from make_resource_handlers
```

render-mcp's whole UI setup:

```python
from sheet_music_mcp_core.ui import PackageAssetSource, UiRegistry, UiResource
from sheet_music_mcp_core.wiring import make_resource_handlers

SCORE_VIEWER = UiResource("ui://render/score-viewer", "score-viewer.html", "Score Viewer", "...")
registry = UiRegistry([SCORE_VIEWER], PackageAssetSource("render_mcp"))  # reads render_mcp/ui/assets/
_on_list_resources, _on_read_resource = make_resource_handlers(registry, logger=logger)
```

The core API (`sheet_music_mcp_core.ui`):

```python
UI_MIME = "text/html;profile=mcp-app"        # = mcp.server.apps.APP_MIME_TYPE
UI_EXTENSION = "io.modelcontextprotocol/ui"  # = mcp.server.apps.EXTENSION_ID

class AssetSource(Protocol):                 # D: the registry never touches the filesystem
    def read(self, name: str) -> str | None: ...        # None = not packaged

class PackageAssetSource:                    # production: importlib.resources
    def __init__(self, package: str, directory: str = "ui/assets"): ...
class InMemoryAssetSource:                   # tests: {"score-viewer.html": "<!doctype html>..."}
    def __init__(self, mapping: dict[str, str]): ...

@dataclass(frozen=True)
class UiResource:                            # S: describes one resource
    uri: str
    asset: str
    name: str
    description: str | None = None
    def tool_meta(self) -> dict: ...         # {"ui": {"resourceUri": uri}}

class UiRegistry:                            # O: new apps are registered, not coded in
    def __init__(self, resources, source: AssetSource): ...       # duplicate URI -> ValueError
    def meta_for(self, resource: UiResource) -> dict | None: ...  # None when asset missing
    def list_resources(self) -> list[Resource]: ...               # only packaged assets
    def read(self, uri: str) -> ReadResourceResult: ...           # raises UiAssetMissing / UiResourceNotFound

def client_supports_ui(ctx) -> bool: ...     # delegates to mcp.server.apps.client_supports_apps
```

`make_resource_handlers` turns a failed read into an `MCPError` whose `data` is the
`{error, error_code}` envelope plus `uri`: `RESOURCE_NOT_FOUND` as `-32602`, `UI_ASSET_MISSING`
(and anything unexpected) as `-32603`. Without it the SDK would send only an opaque
"Internal server error".

- **S:** `presenter.py` builds both result shapes, so `server.py` only wires and `engine.py` only
  renders.
- **O:** linking another tool later is one line, `meta=registry.meta_for(SCORE_VIEWER)`.
- **L:** `PackageAssetSource` and `InMemoryAssetSource` can replace each other everywhere.
- **I:** `AssetSource` has one method.
- **D:** `server.py` builds the registry from a module-level default source, which tests
  override.

**D1 detail.** When the HTML is missing (a source checkout without a UI build),
`meta_for` returns `None`. Tools then carry no `_meta.ui` (the spec requires the referenced
resource to exist), and `resources/read` returns an error naming the fix:
`npm run build` in `ui/`.

**`structuredContent`**

- `render_to_pdf`: `{"pdf_path", "page_count", "backend"}`, the same data as `content`.
- `render_to_image`: `{"image_path", "format", "page", "width_px", "height_px"}`. As built it is
  the same data as the JSON text, so it also holds `total_pages` and `backend`; `width_px` and
  `height_px` are PNG only.

The Score Viewer renders from the MusicXML in `tool-input`, so it does not need file bytes. The
paths are there for the D6 fallback, which shows where the file was saved.

### 3.1a Finding: the default CSP refuses WebAssembly; build both render paths

**Finding (phase 0b, 2026-10-28).** The ext-apps spec's default CSP for a resource without
`_meta.ui.csp` (`default-src 'none'; script-src 'self' 'unsafe-inline'; …`) has no
`'wasm-unsafe-eval'`, and `McpUiResourceCsp` only lets a server declare domains
(`connectDomains`, `resourceDomains`, …), so there is no way to ask for it. The `verovio` npm
package ships only a WASM build. In a host that enforces the spec default, client-side Verovio
cannot start (`WebAssembly.CompileError`). What Claude Desktop and VS Code enforce is unknown
until the manual checks.

**Decision (2026-10-28): build both paths**, so one manual run is conclusive:

1. **WASM first** (option A): `ScoreView`, unchanged.
2. **Server-side SVG fallback** (option B): render-mcp's app-only tool
   `render_page_svg {musicxml, page, width_px, zoom} → structuredContent {svg, page, page_count}`.
   It is hidden from `tools/list` for clients without MCP Apps (core `make_handlers`, proposal
   §6.5), takes inline MusicXML only (proposal §7), uses the viewer's layout (`page_layout()`
   mirrors `paging.ts` `layoutFor()`, both checked against `layout-cases.json`) and keeps the last
   score parsed by content hash so paging does not re-parse.
3. Only if both fail does the viewer show "could not start the notation engine".

The kit's `ScoreRenderer` interface has two implementations (`ScoreView`, `ServerScoreRenderer`);
`openScore()` takes the first that starts and loads. The viewer names the active engine under the
score (`#engine`, `data-engine="wasm"|"server"`), which the manual checklist records.

**Related: tempo note glyphs.** Verovio draws tempo-mark notes with its SMuFL text font. No
`smuflTextFont` mode works under the default CSP: `embedded` is a `data:` font (no `font-src`),
`linked` imports from verovio.org, `none` needs the font installed. Both paths keep `embedded`;
the glyph shows only in hosts that allow `data:` fonts. An SVG shown through
`<img src="data:image/svg+xml,…">` does render it (checked in Chromium), at the cost of the SVG
DOM; left for the findings report.

### 3.2 TypeScript (`ui/`)

```
ui/
  package.json                 # npm workspaces; exact versions; package-lock.json committed
  packages/kit/src/
    host/HostBridge.ts         # interface: onToolInput, onToolResult, onHostContext,
                               #   callTool, sendMessage, updateModelContext, notifySize
    host/ExtAppsBridge.ts      # adapter over @modelcontextprotocol/ext-apps `App`
    host/FakeBridge.ts         # in-memory, for Vitest
    theme.ts                   # host styles/theme -> CSS custom properties
    score/ScoreView.ts         # Verovio wrapper: load(xml), page(n), zoom(z), svg(), timemap()
    score/paging.ts            # pure: clampPage, zoomSteps, fitWidthScale
  apps/score-viewer/
    index.html, main.ts        # composes kit; no Verovio or bridge details here
  test/mock-host/              # host page: postMessage JSON-RPC, fixture replay, call log
  playwright.config.ts
  vite.config.ts               # vite-plugin-singlefile -> dist/score-viewer.html
  scripts/copy-assets.mjs      # dist -> ../render-mcp/src/render_mcp/ui/assets/
```

- **D:** apps depend on `HostBridge`, not on the ext-apps SDK. The same app code runs on
  `FakeBridge` in tests and, later, on an HTTP bridge in the Phase 2 web PoC.
- **S:** `ScoreView` knows Verovio, `paging.ts` is pure maths, and `main.ts` only composes them.
- Verovio comes from the `verovio` npm package (ESM or WASM build) and is inlined by the
  singlefile build. Step 4 confirms that the package's WASM can be inlined as base64.

---

## 4. Implementation steps (red, green, refactor)

Each step starts with the listed tests failing, then the minimum code to pass them, then a
refactor. One commit per step, with the tests and the code together.

| Step | Tests first (red) | Then implement (green) |
|---|---|---|
| **1. SDK characterisation** (done, in core) | `sheet-music-mcp-core/tests/test_mcp_apps_sdk.py`: an in-memory `Client` with an `extensions` entry for `io.modelcontextprotocol/ui` is seen by the server. A `Tool(meta=...)` is serialised as `_meta` on the wire. `TextResourceContents(mime_type=...)` keeps the profile parameter. | Nothing, or small helpers. This step pins down SDK behaviour that later steps rely on. If one of these assumptions fails, stop and revise the plan. |
| **2. UiRegistry** (done, in core) | `sheet-music-mcp-core/tests/test_ui.py`: `meta_for` returns `{"ui":{"resourceUri":...}}` when the asset exists and `None` when it is missing. `list_resources` omits missing assets. `read` returns `UI_MIME` and the HTML. `read` on a missing asset raises `UiAssetMissing` whose message names `npm run build`. `read` on an unknown URI raises. | `sheet_music_mcp_core/ui.py` with `UiResource`, `UiRegistry`, `InMemoryAssetSource`, `PackageAssetSource`. |
| **3. Resource wiring** | `test_mcp_protocol.py` (extended): `client.list_resources()` contains the viewer when packaged. `client.read_resource(uri)` returns the MIME type and HTML. A missing asset gives an error result, not a crash. (The generic handler behaviour is already tested in core `tests/test_wiring.py`.) | `make_resource_handlers(registry, logger=logger)` from the core in `server.py`, passed to `Server(...)`. |
| **4. Tool linking and structured output** | `test_server.py` (extended): both render tools carry `meta` exactly when the asset exists. A golden test asserts `content` is unchanged for the existing fixtures. `structured_content` validates against `output_schema`. Validation errors still return the `{error, error_code}` content with no `structured_content`. | `presenter.py`. `output_schema` and `meta` on the two `Tool`s. `call_tool` returns `CallToolResult` parts through the presenter. |
| **5. UI workspace scaffold** | Vitest: `paging.test.ts` covers `clampPage` (1..n, NaN to 1), `zoomSteps`, and `fitWidthScale(containerWidth, pageWidth)`. `theme.test.ts` maps the host `theme` and `styles.variables` to CSS variables, with a fallback when absent. | `ui/` workspace, TS config, Vitest, `paging.ts`, `theme.ts`. |
| **6. HostBridge** | Vitest: `FakeBridge` replays tool-input and then tool-result in order. `ExtAppsBridge` contract tests run against a mocked `App` and forward `callTool`, `sendMessage`, `updateModelContext` and `notifySize`. | `HostBridge`, `FakeBridge`, `ExtAppsBridge`. |
| **7. ScoreView** | Vitest in the jsdom or happy-dom environment, or Playwright component tests if Verovio WASM will not load in Node: `load(fixtureXml)` gives `pageCount >= 1`. `svg(1)` contains `<svg`. `zoom(2)` changes the SVG scale. `timemap()` returns entries with `tstamp` and `on`. | `ScoreView.ts` over Verovio. |
| **8. Score Viewer app and mock host** | Playwright against `test/mock-host` with the built HTML: renders page 1 after tool-input (AC-R3 setup). Next and Prev move through a 5-page fixture and stop at both ends (AC-R3). Dark host theme gives a dark background. A container resize re-flows and sends `ui/notifications/size-changed`. "Download SVG" triggers a download event. | `apps/score-viewer`, `mock-host`, singlefile build. |
| **9. Packaging (D1)** | pytest marked `integration` (not in the default run): after `uv build`, the wheel lists `render_mcp/ui/assets/score-viewer.html`, and the HTML has no `<script src=` or `<link href=` pointing off-origin (AC-R1). | `copy-assets.mjs`. A `.gitignore` entry for `assets/*.html`. Hatch `[tool.hatch.build] artifacts = ["src/render_mcp/ui/assets/*.html"]` so gitignored files are still packaged. |
| **10. CI** | The new workflow fails on purpose once (one red test) to prove it gates the PR, then goes green. | `.github/workflows/ui.yml`: SHA-pinned `actions/setup-node`, `npm ci`, `vitest run`, `vite build`, `playwright test` (`npx playwright install --with-deps chromium`), then step 9's wheel check. `publish.yml`: for `render-mcp/v*` tags, build `ui/` before `uv build`. `tests.yml` stays unchanged, since Python unit tests use `InMemoryAssetSource` and need no Node. Add `ui/` to Dependabot (npm) and to the unicode-smuggling-guard paths. |
| **11. Measurements** | Not tests. Scripted measurement (Playwright): HTML size (raw and gzip), time to first rendered page on desktop Chromium and with 4x CPU throttling plus a mid-range phone viewport, and peak JS heap. Verovio colour check: render `comparer-mcp`'s `export_annotated_musicxml` output for the fixture pair and assert that coloured noteheads carry a `fill` or `color`. | `ui/scripts/measure.mjs`, with the output pasted into the findings report. |
| **12. Manual host checks and docs** | The [§6](#6-manual-host-checklist) checklist. | Findings report. render-mcp `requirements.md` gains FR-5 (UI resource) and IR-6 (`structuredContent`). `architecture.md` gains a `ui/` component box. Local `HANDOVER.md` and `PLAN.md` are updated. The status line in the root `CLAUDE.md` is updated if behaviour changed. |

Steps 1–4 (Python) and 5–8 (TypeScript) are independent and can run in parallel after step 1.

---

## 5. Test inventory

| Layer | File | New tests (approx.) | Default run? |
|---|---|---|---|
| Python unit (done) | `sheet-music-mcp-core/tests/test_mcp_apps_sdk.py` | 8 | yes |
| Python unit (done) | `sheet-music-mcp-core/tests/test_ui.py` | 18 | yes |
| Python unit (done) | `sheet-music-mcp-core/tests/test_wiring.py` (extended) | 7 | yes |
| Python unit | `render-mcp/tests/test_mcp_protocol.py` (extended) | 3 | yes |
| Python unit | `render-mcp/tests/test_server.py` (extended) | 6 | yes |
| Python integration | `render-mcp/tests/test_packaging.py` | 2 | no (`-m integration`, run by `ui.yml`) |
| TS unit | `ui/packages/kit/**/*.test.ts` | ~15 | `ui.yml` |
| Browser | `ui/apps/score-viewer/e2e/*.spec.ts` | ~6 | `ui.yml` |

---

## 6. Manual host checklist

Run once in **Claude Desktop** (or claude.ai with a local connector) and once in **VS Code**,
using a local build of render-mcp from the spike branch.

| # | Check | Claude | VS Code |
|---|---|---|---|
| M1 | "Render this score" shows the viewer inline. The model still answers with the text result. | ☐ | ☐ |
| M2 | Page navigation and zoom work without any model turn. | ☐ | ☐ |
| M3 | Light and dark host themes are followed. | ☐ | ☐ |
| M4 | Fullscreen request works, or the button is hidden when the mode is not available. | ☐ | ☐ |
| M5 | "Download SVG" saves a file. **Records D6:** if it is blocked, the fallback shows the path and the "ask Claude" button posts a message. | ☐ | ☐ |
| M6 | First render time (stopwatch) and any host size warnings. | ☐ | ☐ |
| M7 | The same server in the Claude Code CLI (no MCP Apps): tools behave exactly as before. | ☐ | — |

---

## 7. Go / no-go after the spike

The findings report recommends one of the following:

- **Go (client-side Verovio):** both hosts render, and load time is acceptable. Proposed budget:
  the measured size rounded up, with a time-to-first-page target on a throttled phone. Phase 1
  starts.
- **Go with option B (server-side SVG):** the hosts reject or struggle with the inlined WASM. The
  plan for Phase 1 changes to app-only `render_page_svg` tools, and the proposal's §6.2 is
  updated. render-mcp's `render_page_svg` already exists (§3.1a); the other servers would need
  their own or a route through the model. The manual checks read the active engine off the
  viewer's `#engine` line.
- **Go with both:** some hosts allow WASM and others do not. Keep the WASM-first viewer with the
  server fallback as built, and decide per app whether a server-side tool is worth adding.
- **Pause:** a target host lacks MCP Apps features we rely on (resource reads, tool calls from
  the app, display modes). Record the gap and re-check host releases before continuing.

---

## 8. Risks

| Risk | Mitigation |
|---|---|
| `mcp` 2.x client or server API differs from what is assumed (extension negotiation, `_meta` serialisation). | Step 1 characterisation tests run first and stop the plan early if an assumption is wrong. |
| The `@modelcontextprotocol/ext-apps` SDK changes its API. | `ExtAppsBridge` is the only file that imports it. Pin an exact version. |
| Verovio WASM does not load in Node for Vitest. | Move the `ScoreView` tests to Playwright component tests (step 7 note). |
| Node in the release path adds supply-chain surface. | Committed lockfile, `npm ci`, SHA-pinned actions, Dependabot, and the unicode guard on `ui/`. The built HTML is checked for off-origin references (AC-R1). |
| The asset is not packaged because hatch skips gitignored files. | `artifacts` setting plus the step 9 wheel test. |
| **Hosts enforce the spec's default CSP, which refuses WebAssembly** (found in phase 0b; a server cannot request `'wasm-unsafe-eval'`). | Both render paths (§3.1a): WASM first, app-only `render_page_svg` second. The manual checks record which one each host uses. |
| The server fallback costs a round trip per page and zoom, and re-sends the inline score each call. | One parsed score cached by hash on the server; the viewer skips page turns superseded while waiting and reuses the page it already has for downloads. Measure in step 11. |
| Tempo-mark note glyphs vanish under the default CSP (Verovio's `data:` text font). | Documented (§3.1a); `<img>` rendering is a known workaround to weigh in the findings. |

---

## 9. Estimated effort

| Block | Steps | Estimate |
|---|---|---|
| Python server side | 1–4 | 1 day |
| UI kit and app | 5–8 | 2–3 days |
| Packaging and CI | 9–10 | 1 day |
| Measurements, host checks, docs | 11–12 | 1 day |
| **Total** | | **about 5–6 days** |
