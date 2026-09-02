# Dependency Review

Direct application dependencies for each MCP server, grouped by server. **Current** = version
resolved in that server's `uv.lock`. **Latest stable** = current PyPI release as of 2026-09-02.

## omr-mcp (v0.1.2)

| Package | Constraint | Current | Latest stable | Note |
|---|---|---|---|---|
| mcp | `>=1.28.1,<2.0.0` | 1.29.1 | 2.1.1 (1.29.1 on the v1.x maintenance line) | Capped below 2.0 intentionally — upgraded to 1.29.1, tests pass |
| oemer | `>=0.1.0` | 0.1.8 | 0.1.8 | up to date |
| onnxruntime | `==1.18.1` (pinned, CPU build) | 1.18.1 | 1.29.0 | Deliberately pinned — see below |
| opencv-python-headless | `==4.10.0.84` (pinned) | 4.10.0.84 | 5.0.0.93 | Deliberately pinned — opencv 5.x changed `cv2.HoughLinesP()` return shape, crashing oemer's staffline extraction |
| Pillow | `>=10.0.0` | 12.3.0 | 12.3.0 | up to date |
| defusedxml | `>=0.7.0` | 0.7.1 | 0.7.1 | up to date |

`onnxruntime-gpu` is explicitly excluded via `[tool.uv] override-dependencies` (an "impossible marker") so oemer's own unpinned dependency on it can't silently shadow the pinned CPU build.

## render-mcp (v0.1.2)

| Package | Constraint | Current | Latest stable | Note |
|---|---|---|---|---|
| mcp | `>=1.28.1,<2.0.0` | 1.29.1 | 2.1.1 (1.29.1 on v1.x) | Capped below 2.0 — upgraded, tests pass |
| verovio | `>=3.0.0` | 6.3.0 | 6.3.0 | upgraded, 73/73 tests pass |
| cairosvg | `>=2.7.0` | 2.9.0 | 2.9.0 | up to date |
| pypdf | `>=4.0.0` | 6.16.2 | 6.16.2 | upgraded |
| Pillow | `>=10.0.0` | 12.3.0 | 12.3.0 | up to date |

## synth-mcp (v0.1.3)

| Package | Constraint | Current | Latest stable | Note |
|---|---|---|---|---|
| mcp | `>=1.28.1,<2.0.0` | 1.29.1 | 2.1.1 (1.29.1 on v1.x) | Capped below 2.0 — upgraded, tests pass |
| music21 | `>=9.0.0` | 10.5.0 | 10.5.0 | up to date |
| pyfluidsynth | `>=1.3.0` | 1.4.0 | 1.4.0 | up to date |

## musicxml-abc-mcp (v0.1.2)

| Package | Constraint | Current | Latest stable | Note |
|---|---|---|---|---|
| mcp | `>=1.28.1,<2.0.0` | 1.29.1 | 2.1.1 (1.29.1 on v1.x) | Capped below 2.0 — upgraded, tests pass |
| music21 | `>=9.0.0` | 10.5.0 | 10.5.0 | up to date |

## pitch-mcp (v0.2.0)

| Package | Constraint | Current | Latest stable | Note |
|---|---|---|---|---|
| mcp | `>=1.28.1,<2.0.0` | 1.29.1 | 2.1.1 (1.29.1 on v1.x) | Capped below 2.0 — upgraded, tests pass |
| music21 | `>=9.0.0` | 10.5.0 | 10.5.0 | up to date |
| librosa | `>=1.0.0` | 1.0.0 | 1.0.0 | up to date, see prior deep-dive below |
| numpy | `>=1.24.0` | 2.5.2 | 2.5.2 | up to date |
| scipy | `>=1.10.0` | 1.18.1 | 1.18.1 | upgraded, 112 unit tests pass |
| sounddevice | `>=0.4.0` | 0.5.6 | 0.5.6 | upgraded, 112 unit tests pass |
| dtaidistance | `>=2.4.0` | 2.4.0 | 2.4.0 | new dependency since last review (DTW-based alignment) — up to date |

## comparer-mcp (v0.1.0)

| Package | Constraint | Current | Latest stable | Note |
|---|---|---|---|---|
| mcp | `>=1.28.1,<2.0.0` | 1.29.1 | 2.1.1 (1.29.1 on v1.x) | Capped below 2.0 — upgraded, tests pass |
| music21 | `>=9.0.0` | 10.5.0 | 10.5.0 | up to date |

## What changed since the 2026-08-15 review

- `pitch-mcp` bumped to v0.2.0 and picked up `dtaidistance>=2.4.0` (DTW-based score alignment) —
  new dependency, currently at latest.
- All six servers' patch versions moved forward (0.1.1→0.1.2/0.1.3), no dependency-relevant changes.
- **Applied**: `mcp` 1.29.0 → 1.29.1 in all six servers' `uv.lock` files (`uv lock
  --upgrade-package mcp && uv sync`) — pure bug-fix backport, no API changes. Full test suites
  re-run per server after the bump, all green (see per-server tables above for pass counts).
- **Applied**: `verovio` 6.2.1 → 6.3.0 and `pypdf` 6.16.1 → 6.16.2 in render-mcp — 73/73 tests pass.
- **Applied**: `scipy` 1.18.0 → 1.18.1 and `sounddevice` 0.5.5 → 0.5.6 in pitch-mcp — 112 unit
  tests pass (4 skipped for missing audio fixtures, unrelated to this change).
- `mcp` 2.x moved 2.0.0 → 2.0.1 → 2.1.0 → 2.1.1 on the v2 line; still not adopted (see below).
- Not touched: transitive tooling packages (`click`, `cryptography`, `uvicorn`, `pydantic`, etc.)
  with patch updates available across every server — low priority, no direct app impact.
- No new evidence changes either of the two standing pin decisions (`onnxruntime` in omr-mcp,
  the `mcp<2.0.0` cap everywhere) — both re-verified below.

## Dev dependencies (shared across all six)

| Package | Constraint | Current | Latest stable | Note |
|---|---|---|---|---|
| pytest | `>=8.0.0` | 9.1.1 | 9.1.1 | up to date |
| pytest-asyncio | `>=0.23.0` | 1.4.0 | 1.4.0 | up to date |

## Release-note findings for updatable packages

### `mcp` 1.29.0 → 1.29.1 / 2.1.1 (all six servers) — **take the 1.29.1 patch, still don't cross to 2.x**

The `>=1.28.1,<2.0.0` constraint already keeps every server on the v1.x maintenance line; the lock
files are simply one patch behind what that constraint allows. **1.29.1** (2026-08-24) is a
pure backport of three fixes from the 2.x line: completing the `FastMCP` settings model at import
time, applying the Streamable HTTP/SSE/OAuth request-body size limit, and giving recursive tool
return types an object-rooted `outputSchema` (client compatibility fix). No API changes — safe to
let `uv sync` / `uv lock --upgrade-package mcp` pick it up.

The 2.x line itself (now at 2.1.1) has moved past the initial 2.0.0 stable release with two more
minors since the last review:
- **2.1.0**: `Client` accepts `StdioServerParameters` directly, prompts can return `Image`/`Audio`
  content, the 4 MiB request-body limit now also covers SSE and OAuth endpoints, and unhandled
  handler exceptions are logged server-side instead of leaking their text to the client (raise
  `ToolError`/`ResourceError` for messages meant for the model).
- **2.1.1** / **2.0.1**: docs-only patches (FastMCP import-warning wording).

None of this changes the underlying migration calculus from the last review: v2 still removes the
decorator API surface for the low-level `Server` these six servers use — handlers move to
constructor kwargs — `mcp.types` is still split into `mcp-types`, and tool exceptions still
propagate differently (JSON-RPC errors vs. `CallToolResult(is_error=True)`). v1.x remains
security-fix-only maintenance, which is sufficient for now. Re-evaluate when a coordinated v2
migration is actually scheduled.
(Sources: [v2.1.0](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.1.0),
[v2.1.1](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.1.1),
[v1.29.1](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v1.29.1))

### `onnxruntime` 1.18.1 → 1.29.0 (omr-mcp) — **stay pinned, re-confirmed**

Re-checked the v1.29.0 changelog (the version now current since the last review's 1.28.0): still
no mention of the ConvTranspose negative-pad shape-validation strictness being relaxed. The
1.29.0 notes are dominated by CUDA/WebGPU/MLAS feature work and a large batch of CPU-side
bounds/input-validation hardening (`AveragePool`, `MaxPool`, `GridSample`, RNN activations, etc.) —
consistent with the pattern already observed: this project's ONNX Runtime keeps getting *more*
shape-strict, not less. No new session option surfaced to disable strict shape checks. The
conclusion from the last review stands unchanged: the only real path off the pin is graph surgery
on oemer's exported ONNX models; absent that, keep `onnxruntime==1.18.1` indefinitely.
(Source: [v1.29.0 release notes](https://github.com/microsoft/onnxruntime/releases/tag/v1.29.0))

### `librosa` 1.0.0 (pitch-mcp) — unchanged, no new release since last review

Still the latest stable (1.0.0, 2026-08-11). The deep-dive from the 2026-08-15 review — API
stabilization only, no breaking changes touching this server's `librosa.pyin`/`librosa.load`
usage — remains current; nothing new to re-verify.
