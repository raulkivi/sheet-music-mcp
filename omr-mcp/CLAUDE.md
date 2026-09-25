# omr-mcp — Claude Code Instructions

## What This Server Does

Converts sheet music images (PNG/JPEG) to MusicXML. Two selectable OMR backends: `oemer` (default,
in-process) and `audiveris` (opt-in via `engine="audiveris"`, subprocess). Entry point of the choir
pipeline — all other servers consume MusicXML produced here.

**Status:** Phases 1–4 code complete, including the Audiveris backend option (shipped 2026-08-16).
111 unit tests pass. Integration tests run against real oemer for the first time (2026-08-15):
fixing a 100%-blocking API bug plus pinning `onnxruntime` and `opencv-python-headless` took the
suite from 0/41 to 20/41 passing. **oemer's default output is not usable for SATB scores** — it
reads multi-staff systems sequentially instead of simultaneously, so a 4-voice choir score comes
out as one part with the clef alternating back and forth instead of 4 parts sounding together;
root-caused 2026-08-16 as an architectural limitation (`build_system.py` hard-asserts at most 2
simultaneous staff tracks). **Fixed via `engine="audiveris"`**, validated against real Audiveris on
both of oemer's failure modes (crash case + silent-flattening case) — correctly recovers separate
SATB parts in both. Not yet the default engine (see `docs/HANDOVER.md` "Audiveris engine option"
for why). 2/4 CPDL images also hit further oemer-internal crashes on this specific input data —
both root-caused 2026-08-16 (one is the SATB bug itself manifesting as a hard crash; see
`docs/HANDOVER.md` for the full writeup).

---

## Running Tests

```bash
# From this directory
VIRTUAL_ENV= .venv/bin/pytest tests/ -v                # 111 unit tests (fast; all subprocess/network calls mocked)
VIRTUAL_ENV= .venv/bin/pytest tests/ -v -m integration # invokes real oemer (~3–5 min/page)
```

Install dependencies: `uv sync`

---

## Key Files

| File | Purpose |
|------|---------|
| `src/omr_mcp/server.py` | MCP tool definitions and handlers |
| `src/omr_mcp/omr_engine.py` | oemer + Audiveris wrappers, `_ENGINE_RUNNERS` dispatch table (no MCP imports) |
| `src/omr_mcp/utils.py` | Image validation, base64 helpers |
| `tests/test_omr.py` | Unit + integration tests |
| `test_samples/pdmx_satb_samples/` | 10 SATB PNG + MXL ground-truth fixtures |
| `docs/HANDOVER.md` | Status, remaining work, definition of done |
| `docs/PLAN.md` | Architecture decisions and rationale |
| `docs/requirements.md` | Functional/non-functional requirements |
| `docs/architecture.md` | Component diagram and data-flow |

---

## Implemented Tools

| Tool | Input | Output |
|------|-------|--------|
| `recognize_sheet` | Image path or base64; optional `engine` ("oemer"\|"audiveris") | MusicXML string + metadata |
| `recognize_sheet_to_file` | Image path; optional `engine` | MusicXML file path + metadata |
| `recognize_sheets` | List of image paths/base64; optional `engine` | Single merged MusicXML (multi-page) |
| `list_capabilities` | — | Server capabilities incl. per-engine availability |
| `list_supported_formats` | — | Deprecated alias for `list_capabilities` |
| `health_check` | — | Runtime dependency status incl. oemer/model cache/Audiveris |

---

## Hard Rules

- **Never `pip install`** — use `uv sync` or `uv add`
- **`omr_engine.py` must not import from `mcp`** — keeps it unit-testable
- **All tool handlers must be `async def`**
- **All errors** → `{"error": "...", "error_code": "..."}` (codes: `FILE_NOT_FOUND`, `UNSUPPORTED_FORMAT`, `FILE_TOO_LARGE`, `INVALID_INPUT`, `PROCESSING_FAILED`, `INVALID_PARAMETER`)
- **Integration tests** must be `@pytest.mark.integration` and skipped in the default run

---

## MCP Server Startup Pattern

```python
import asyncio
import mcp.server.stdio

async def _run():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

asyncio.run(_run())
```

`run_server()` does not exist in the installed MCP SDK — use the context manager above.

---

## Known Gotchas

- **oemer downloads ~100 MB on first run** and takes ~10 min. Subsequent runs use cache.
- **oemer output varies slightly between runs** — never assert byte-identical XML; parse and
  compare structure instead.
- **MusicXML from oemer may not validate against strict schema** — check for parseable content
  and presence of parts/measures.
- **The full PDMX dataset (14 GB) lives in `test_samples/pdmx_full/`** — never load or iterate
  it in tests; use `pdmx_satb_samples/` only.
- **`.python-version` (`llm311`) is a pyenv-virtualenv name `uv` doesn't understand** — `uv sync`
  silently falls back to whatever `python3` is on `PATH` instead of erroring. Always check
  `.venv/bin/python --version` after `uv venv`/`uv sync`; use `uv venv --python 3.11` if it's wrong.
- **`omr_engine.py` forces `CUDA_VISIBLE_DEVICES=""` at import time.** On this dev host,
  onnxruntime's CUDA execution provider hard-aborts the process instead of raising a catchable
  Python exception. Real GPU inference would need a matched onnxruntime-gpu/CUDA driver pair.
- **`opencv-python-headless` is pinned** in `pyproject.toml`, and `onnxruntime-gpu` is excluded
  via `[tool.uv] override-dependencies` — oemer's own packaging leaves both unpinned; opencv 5.x
  changed `cv2.HoughLinesP`'s return shape. `onnxruntime` is current (>=1.30): its stricter
  ConvTranspose validation is handled by `onnx_compat.fix_negative_convtranspose_pads()`, which
  `_run_oemer()` applies to the cached `unet_big` model before every recognition. Full details
  in `docs/HANDOVER.md`.
- **`engine="audiveris"` downloads ~80 MB on first use** (self-contained, bundles its own JRE) into
  `~/.cache/omr-mcp/audiveris/`, extracted via `dpkg-deb -x` — no root, no system `apt`/`dpkg -i`.
  Requires `dpkg-deb` (present on virtually all Debian/Ubuntu systems).
- **Audiveris needs genuinely 300+ DPI input** — unlike oemer, which normalizes every input to a
  fixed internal pixel budget and is DPI-insensitive in practice. Audiveris explicitly rejects
  lower-resolution sheets rather than degrading gracefully.
- **Audiveris can exit 0 while producing no output** (e.g. it rejected every sheet for low
  resolution) — `_run_audiveris()` detects failure by checking for the expected `.mxl` output
  file's existence, not the subprocess exit code.

---

## Claude Desktop Config

```json
{
  "mcpServers": {
    "omr": {
      "command": "uv",
      "args": ["--directory", "/path/to/omr-mcp", "run", "omr-mcp"]
    }
  }
}
```

---

## Document Update Policy

When you finish work or reach a milestone, update:
1. `docs/HANDOVER.md` — check off done items, add new gotchas
2. `docs/PLAN.md` — check off phase items, note changed decisions
3. `docs/requirements.md` — update if behaviour changed
4. `docs/architecture.md` — update if implementation changed
