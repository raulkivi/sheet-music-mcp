# sheet-music-mcp-core 0.1.0: review guide and findings

**Status:** Reviewed. All findings accepted and fixed ([§6](#6-decisions-and-outcome)). §2 describes the API as reviewed; §7 lists what changed.
**Date:** 2026-10-27
**Commit under review:** `46921a0` ("Add sheet-music-mcp-core shared library")
**Plan:** [ux-wave1-plan.md](ux-wave1-plan.md) §3, step 2

---

## 1. How to review

| What | Where | Size |
|---|---|---|
| Source | `sheet-music-mcp-core/src/sheet_music_mcp_core/` | 6 modules, 334 lines |
| Tests | `sheet-music-mcp-core/tests/` | 7 files, 78 tests (all pass) |
| Contract it implements | [docs/conventions.md](../conventions.md): Error Response Format, Part Selection, Deprecated Parameter Names, Tool Annotations and Titles, Result Content, Shared Core Library | |
| CI | `.github/workflows/tests.yml` (matrix entry), `publish.yml` (PyPI only, no MCP Registry), `dependabot.yml` | |

```bash
cd sheet-music-mcp-core
uv sync --extra dev
VIRTUAL_ENV= .venv/bin/pytest tests/ -v
```

Suggested reading order: `errors.py`, `parts.py` (the only module with real logic), `params.py`,
`annotations.py`, `content.py`, `wiring.py`.

---

## 2. API reference

### `errors` (no `mcp` import)

```python
error_payload(message, error_code, *, hint=None, choices=None) -> dict
class ProcessingError(Exception):
    def __init__(self, message, error_code="PROCESSING_FAILED", *, hint=None, choices=None): ...
    error_code: str; hint: str | None; choices: list[str] | None
    def to_payload(self) -> dict
```

- Key order is always `error`, `error_code`, `hint`, `choices`. Omitted fields are absent, not
  `null`, so existing error JSON is byte-identical.
- Positional `(message, code)` matches every server's current `ProcessingError`, so engines can
  switch the import without changing any `raise`.

### `parts` (no `mcp` import)

```python
@dataclass(frozen=True)
class PartInfo:
    id: str
    name: str

resolve_parts(requested: Sequence[str], available: Sequence[PartInfo]) -> list[str]
resolve_part(requested: str, available: Sequence[PartInfo]) -> str
class PartSelectionError(ProcessingError)   # always INVALID_PARAMETER, with hint and choices
```

Matching per request, where the first tier that matches wins:

1. Exact ID.
2. Normalised name or ID (casefold, punctuation stripped, Roman numerals I to IV become 1 to 4).
3. Voice role (alias table in conventions), with an optional divisi number.

```python
SATB = [PartInfo("P1", "Soprano"), PartInfo("P2", "Alto"), PartInfo("P3", "Tenor"), PartInfo("P4", "Bass")]
resolve_parts(["B", "S", "soprano"], SATB)       # ["P4", "P1"]   request order, no duplicates
resolve_part("p3", SATB)                          # "P3"           ID ignores case in tier 2
resolve_parts(["Alto"], [PartInfo("P1", "Alto I"), PartInfo("P2", "Alto II")])  # ["P1", "P2"]
resolve_part("Alto", [PartInfo("P1", "Alto I"), PartInfo("P2", "Alto II")])
#   PartSelectionError: Part 'Alto' matches 2 parts; choose one.
#   choices = ["Alto I (P1)", "Alto II (P2)"]
```

### `params` (no `mcp` import)

```python
aliased(arguments: dict, name: str, deprecated: str) -> Any   # value, or None if neither given
```

- Old name only: the value is returned, with one warning per deprecated name per process.
- Both names with equal values: accepted. Different values: `ProcessingError(INVALID_PARAMETER)`.
- An explicit `None` counts as absent.

### `annotations` (no `mcp` import)

`READ_ONLY`, `READ_ONLY_DOWNLOADS`, `WRITES_FILE`, `WRITES_FILE_DOWNLOADS` and `SESSION_STATE` are
immutable mappings. Use them as `ToolAnnotations(**READ_ONLY)`.

### `content` (imports `mcp`)

```python
error_content(message, error_code, *, hint=None, choices=None) -> list[TextContent]
file_link(path: str, mime_type: str) -> ResourceLink          # file:// URI, name, size
image_block(path: str, *, max_bytes=1_048_576) -> ImageContent | None   # PNG only
```

### `wiring` (imports `mcp`)

```python
on_list_tools, on_call_tool = make_handlers(list_tools, call_tool, *, pass_context=False)
app = Server("render-mcp", on_list_tools=on_list_tools, on_call_tool=on_call_tool)
```

This is behaviour-identical to the six copies it replaces:

- Arguments are checked against the input schema, giving
  `isError` "Input validation error: …".
- Exceptions become `isError` with `str(e)`.
- `call_tool` may return a content list or a full `CallToolResult` (needed later for
  `structuredContent`).
- `pass_context=True` serves omr-mcp, whose `call_tool` takes `ctx` for progress notifications.

---

## 3. Changes from the approved plan

| Change | Reason |
|---|---|
| `error_content()` moved from `errors` to `content`; `errors` gained `error_payload()` | Building a `TextContent` needs `mcp`, and `errors` must stay MCP-free for engines. |
| Tier 2 also matches the **ID** without regard to case (`"p2"` finds `P2`) | Small convenience with no ambiguity. |
| Added the alias `bassus` | Covers Latin part books (W2). |

`docs/conventions.md` and the plan already reflect these changes.

---

## 4. Validation against real scores

The resolver was run against music21 corpus scores after a MusicXML round trip, which is what
the servers see:

| Score | Parts (`part.id`, name) | `Soprano` | `S` | `Alto` | `Tenor` | `Bass` / `B` |
|---|---|---|---|---|---|---|
| Bach BWV 66.6 | Soprano, Alto, Tenor, Bass | ✓ | ✓ | ✓ | ✓ | ✓ |
| Bach BWV 269 | Soprano, Alto, Tenor, Bass | ✓ | ✓ | ✓ | ✓ | ✓ |
| Monteverdi madrigal 3.1 | Canto, Quinto, Alto, Tenor, Basso | ✓ (Canto) | ✓ | ✓ | ✓ | ✓ (Basso) |
| Palestrina Agnus 01 | Soprano, Alto, Tenor, **Tenor**, Bass | ✓ | ✓ | ✓ | ⚠️ see F1 | ✓ |
| Clara Schumann op. 17 (trio) | Violin, Cello, Piano (2 staves) | no match, choices listed | | | | |

The role logic works. The problem is the IDs that would be fed into it (F1).

---

## 5. Findings

<a id="f1"></a>

### F1. music21 `part.id` is not the MusicXML part ID (major; affects how servers adopt the core)

Measured with music21 10.5 on minimal MusicXML documents:

| MusicXML parts | music21 `part.id` | Problem |
|---|---|---|
| `P1` "Soprano", `P2` "Alto" | `"Soprano"`, `"Alto"` | The real ID `P1` is unknown to the servers. |
| `P1` "Tenor", `P2` "Tenor" | `"Tenor"`, `"Tenor"` | Duplicate IDs: `resolve_part("Tenor")` reports two choices that are both labelled `"Tenor (Tenor)"`, and engines filtering on `p.id` always pick both. |
| `P1` (no name), `P2` (no name) | `140320038121744`, … (an integer, **new on every parse**) | `get_parts` returns an ID that no later call can match. Unnamed parts are common in OMR output. |

The real MusicXML ID survives as `part.getInstrument(returnDefault=False).partId` (`"P1"`,
`"P2"`), which is unique and stable.

This also corrects my earlier description of the bug ("`'Soprano'` fails because the IDs are
`P1`…`P4`"). Named parts work today by accident. The real failures are the three rows above. The
proposal and the Wave 1 plan are corrected.

**Proposed fix:** add a small duck-typed adapter to `parts`. It does not import music21, because
it only calls methods on the objects it is given:

```python
def music21_part_infos(parts) -> list[PartInfo]:
    """PartInfo per music21 part: id = MusicXML score-part id (instrument.partId),
    falling back to f"P{index}" when absent; name = partName or ""."""
```

Engines then select parts **by position**: they zip the infos with `score.parts` and keep the
parts whose info ID was resolved. They never use `p.id`. `get_parts` returns the same stable IDs.
The core gets tests with fake part objects. Each server gets the three regressions in the table,
which fail on `main` today.

### F2. Choice labels for same-named parts (minor; fixed by F1)

With stable MusicXML IDs the labels become `"Tenor (P3)"` and `"Tenor (P4)"`. No separate change
is needed.

### F3. Part abbreviations are not used (minor, optional)

MusicXML `<part-abbreviation>` (`S.`, `Q.`, `Pno.`) is available. Matching it in tier 2 would let
`"Q"` find the Monteverdi Quinto. **Proposal:** add `abbreviation: str = ""` to `PartInfo` and
match it in tier 2. The cost is small.

### F4. Wiring logs under the core's logger name (minor)

`make_handlers` logs "Tool X failed" as `sheet_music_mcp_core.wiring`. The conventions say
"logger name = package name", so server logs would change. **Proposal:** add an optional
`logger=` parameter that each server passes as its own logger.

### F5. `image_block` is PNG-only by name (cosmetic)

It always sets `image/png`. **Proposal:** rename it to `png_block` before anything uses it, or add
a `mime_type` parameter. Renaming is clearer, since only PNG is planned (SVG is excluded).

### F6. Voice aliases not included (question)

`Treble` (boys' and Anglican choirs) and `Countertenor` / `Contratenor` are not in the table.
Treble would map to soprano. Countertenor could be its own role or map to alto. Add either?

### Checked and fine

- `ProcessingError` positional signature is compatible with all six servers.
- `error_content` text is byte-identical to the servers' current `json.dumps({...})`.
- The import isolation test shows `errors`, `parts`, `params` and `annotations` load no `mcp`
  module.
- The wheel builds with all six modules. CI runs the tests on Python 3.12 and 3.13.

---

## 6. Decisions and outcome

Owner decisions on 2026-10-27. All were implemented test-first: the new tests failed before the
change, and 91 tests pass after it.

| # | Decision | Outcome |
|---|---|---|
| R1 | Fix F1 in the core | `parts.music21_part_infos(parts)` builds a `PartInfo` per music21 part from `instrument.partId`. It falls back to `P<position>`, keeps music21 staff IDs for multi-staff parts (`P3-Staff1`), and numbers any remaining duplicates. It is duck-typed, so the core still never imports music21. The conventions now require engines to select parts by position against this list. |
| R2 | Match abbreviations | `PartInfo.abbreviation` (default `""`) is matched in tier 2: `"Q"` finds Quinto. |
| R3 | `logger=` on `make_handlers` | Failures are logged under the server's logger when one is given, otherwise under `sheet_music_mcp_core.wiring`. |
| R4 | Rename | `image_block` is now `png_block`. |
| R5 | Voice aliases | `tr`, `treble` and `trebles` map to soprano. Countertenor is its own role (`ct`, `countertenor`, `counter tenor`, `contratenor`, …). |

**Checked against real music21 10.5 parses:**

- Named, same-named and unnamed parts get the same IDs on every parse (`P1`/`P2`, `P3`/`P4`).
- `"P1"` resolves on a named SATB score.
- The Palestrina tenors resolve to two distinct IDs.
- The Schumann piano staves become `P3-Staff1` and `P3-Staff2`.
- Monteverdi `"Q"` finds Quinto.

## 7. Changes since the reviewed commit

```python
@dataclass(frozen=True)
class PartInfo:
    id: str
    name: str
    abbreviation: str = ""                       # new (R2)

music21_part_infos(parts) -> list[PartInfo]      # new (R1)
png_block(path, *, max_bytes=1_048_576)          # renamed from image_block (R4)
make_handlers(list_tools, call_tool, *, pass_context=False, logger=None)   # logger new (R3)
```
