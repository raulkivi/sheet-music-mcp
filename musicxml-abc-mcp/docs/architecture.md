# musicxml-abc-mcp — Technical Architecture

**Last changed:** 2026-11-11 · **Source:** https://github.com/raulkivi/sheet-music-mcp

## Overview

musicxml-abc-mcp is a stateless MCP server that converts between MusicXML and ABC notation. It uses music21 to parse both formats and a custom ABC serializer to produce ABC output (music21 9.x has no built-in ABC writer). The primary use case is enabling an LLM (Claude) to read and edit scores without handling verbose MusicXML directly.

---

## Component Diagram

```
┌───────────────────────────────────────────────────────────┐
│                      MCP Client                           │
│                   (Claude / web app)                      │
└──────────────────────────┬────────────────────────────────┘
                           │  stdio (JSON-RPC)
┌──────────────────────────▼────────────────────────────────┐
│                       server.py                           │
│                                                           │
│  list_tools()   → 8 tool definitions                      │
│  call_tool()    → dispatches to engine / abc_edit         │
│  load_score / deliver_score / describe_score (core)       │
└──────────┬────────────────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────────┐
│                       engine.py                          │
│                                                          │
│  musicxml_to_abc()          abc_to_musicxml()            │
│  validate_abc()             list_capabilities()          │
│                                                          │
│  ─── Custom ABC serializer ──────────────────────────── │
│  _part_to_abc_tune()        _pitch_to_abc()             │
│  _duration_to_abc()         _key_to_abc()               │
│  _note_to_abc_token()       _wrap_bars()                │
│  _find_title()              _is_dynamic()               │
│  ProcessingError                                         │
└──────────┬──────────────────────────────────────────────┘
           │   abc_edit.py: apply_abc_edit() (bar edits, uses
           │   abc_bars.split_bars() and abc_to_musicxml())
┌──────────▼──────────────┐  ┌──────────────────────────────┐
│        utils.py         │  │          music21             │
│                         │  │                              │
│  validate_musicxml()    │  │  converter.parseData()       │
│  validate_abc_str()     │  │  converter.toData()          │
└─────────────────────────┘  │  Note, Chord, Rest, Key,     │
                             │  MetronomeMark, Dynamic, ...  │
                             └──────────────────────────────┘
```

---

## Module Responsibilities

### `server.py`

MCP protocol layer. Contains no conversion logic.

- Registers eight tools (`get_abc` is app-only and hidden from clients without MCP Apps):
  `musicxml_to_abc`, `abc_to_musicxml`, `apply_abc_edit`, `validate_abc`, `list_capabilities`,
  `health_check`, the shared `describe_score` and `get_abc`
- Reads the score with `sheet_music_mcp_core.references.load_score` (`musicxml` text or a confined
  `musicxml_path`, `.mxl` included), then validates parameters (via `utils.py`) before calling engine
- Returns `abc_to_musicxml` and `apply_abc_edit` results with `deliver_score` (`return` = `auto` /
  `path` / `inline`): large scores go to `<output root>/scores/from-abc-<timestamp>.musicxml`
  (`abc-edit-<timestamp>.musicxml` for edits)
- Converts engine results and `ProcessingError` exceptions to `TextContent` JSON
- Wires the handlers with `make_handlers(..., pass_context=True)`, so `load_score` can ask the
  client for its MCP roots
- Entry point via `mcp.server.stdio.stdio_server()`

### `presenter.py`

Turns engine results into `(content, structured_content)` for the ABC Workbench tools. `content`
is what the tools always returned; `structured_content` adds `abc_id` to the export, and for
`abc_to_musicxml` only `{warnings, delivery, musicxml_bytes}` (never the score). Output schemas
live here. No engine logic.

### `abc_store.py`

`AbcStore` keeps recent `musicxml_to_abc` results behind random `abc_id`s (bounded, TTL, thread
safe, no MCP imports; a core `ExpiringTable` underneath, plus the latest id for `get_abc` without one). The app-only `get_abc` reads from it, so the workbench gets the "original"
side by id and never needs a path. `server.py` holds the module-level instance, replaced in tests.

### `engine.py`

All conversion and serialization logic. No MCP imports.

**High-level functions:**

| Function | Description |
|----------|-------------|
| `musicxml_to_abc(musicxml_str, part_id, measures)` | Cut to `measures` (core `select_measures`); parse MusicXML; resolve the part (ID, name or voice); serialize each part to ABC tune |
| `abc_to_musicxml(abc_str)` | Parse ABC with music21; export to MusicXML |
| `validate_abc(abc_str)` | Check ABC syntax; return errors and warnings |

**ABC serializer (private functions):**

| Function | Description |
|----------|-------------|
| `_part_to_abc_tune(part, tune_num, score)` | Serialize one music21 Part to an ABC tune string |
| `_note_to_abc_token(element)` | Convert Note, Chord, or Rest to an ABC token |
| `_pitch_to_abc(pitch)` | Convert music21.Pitch to ABC pitch string (octave + accidental) |
| `_duration_to_abc(quarter_length)` | Convert quarter-note duration to ABC duration suffix |
| `_key_to_abc(key_sig)` | Convert music21.Key or KeySignature to ABC K: value |
| `_wrap_bars(bars, line_width=78)` | Join bar tokens with `\|`, wrap at 78 chars |
| `_tempo_number(tempo_mark)` | A MetronomeMark's shown tempo, else its sounding tempo (a bare `<sound tempo>`) |
| `_find_title(part, score)` | Extract title from score metadata |
| `_is_dynamic(elem)` | True if element is a music21 Dynamic |

### `abc_edit.py`

`apply_abc_edit(musicxml_str, part, measures, abc)` (C16). No MCP imports. Works on the score text,
not a re-serialised tree, so everything outside the edited bars keeps its bytes:

1. `select_measures` checks the range (same errors and hints as `musicxml_to_abc`); `parse_score`
   (defusedxml) parses the score; partwise only.
2. The part is resolved from the part list (`resolve_part`, score-part IDs); positions come from
   the first part's printed numbers (`printed_numbers`), as in `select_measures`.
3. `abc_bars.split_bars` cuts the ABC at its bar lines; the count must equal the range length
   before any bar is converted. Each bar is converted alone with `abc_to_musicxml`, under a 64/4
   meter so music21 never re-bars it, and ties across bar lines get their stop back.
4. Each edited bar is the original bar's shell (attributes, `<print>`, leading `<attributes>`,
   bar lines, tempo/rehearsal/segno/coda directions) around the ABC bar's notes, with ABC
   `attributes`, `print`, `barline` and tempo dropped. Durations are rescaled to the part's
   divisions; when they do not fit, the bar gets finer divisions and the next untouched bar gets
   the part's own value back.
5. `expat` finds the byte span of each `<measure>` of the part; the new bars are spliced in, in
   the indentation of the line they replace. A non-UTF-8 encoding declaration becomes UTF-8.

Warnings (conventions: Warnings) report dynamics, lyrics and articulations the edited bars lost
and bars whose length changed.

### `abc_bars.py`

`split_bars(abc)`: one standalone tune per bar (`X:1`, `M:64/4`, the `L:` and `K:` in force, the bar
body). Handles `|`, `||`, `|]`, `[|`, `|:`, `:|`, `::`, volta numbers and `[1`; does not split inside
chords `[...]`, inline fields `[K:...]`, quoted annotations or `!...!` decorations. Drops comments
and `w:` lines; rejects several tunes (`X:`), voices (`V:`) and ABC without `K:`. No music21.

### `utils.py`

Minimal input validation.

| Function | Description |
|----------|-------------|
| `validate_musicxml(xml)` | Non-empty; contains `<score-partwise>` or `<score-timewise>` |
| `validate_abc_str(abc)` | Non-empty string check |

---

## Data Flow

### MusicXML → ABC

```
call_tool("musicxml_to_abc", {musicxml | musicxml_path, part: "Soprano", measures: [3, 4]})
                                                            (part_id: deprecated alias)
  │
  ├─ core: load_score   inline text as is, or the path confined to the read roots and read
  │                     (.mxl unzipped); INVALID_PARAMETER / FILE_NOT_FOUND / FILE_TOO_LARGE / INVALID_INPUT
  ├─ utils: validate_musicxml
  │
  └─ engine: musicxml_to_abc(musicxml, part_id="Soprano", measures=[3, 4])
        │
        ├─ if measures given:
        │     musicxml = select_measures(musicxml, [3, 4])   core, before music21 sees the score
        │     keeps printed bars 3–4 (pickup = 0) in every part; the first kept bar gets the
        │     divisions, key, time, clefs and tempo (<sound tempo>) in force before it
        │     MeasureRangeError (INVALID_PARAMETER, hint "This score has measures 1–6.") if
        │     reversed, malformed or outside the score
        │
        ├─ score = music21.converter.parseData(musicxml, format="musicxml")
        │
        ├─ infos = music21_part_infos(score.parts)   stable IDs "P1"…, never music21's part.id
        ├─ if part_id given:
        │     resolve_part("Soprano", infos) → "P1"   (ID, name or voice)
        │     PartSelectionError with choices if unknown or ambiguous
        │     parts = [soprano_part]                  selected by position
        │
        ├─ for i, (part, info) in enumerate(parts):
        │     (tune_str, warnings) = _part_to_abc_tune(part, i+1, score, info.name or info.id)
        │
        ├─ join tune strings with "\n\n"
        └─ return {abc: str, parts_included: ["P1", ...], warnings: [...]}
```

### ABC → MusicXML

```
call_tool("abc_to_musicxml", {abc, return: "auto"})
  │
  ├─ engine: abc_to_musicxml(abc_str)
        │
        ├─ stream = music21.converter.parseData(abc_str, format="abc")
        │
        ├─ if isinstance(stream, Opus):    ← multiple X: tunes
        │     score = Score()
        │     for s in stream.scores:
        │         score.append(s.parts[0])
        │
        ├─ musicxml_str = music21.converter.toData(score, fmt="musicxml")
        └─ return {musicxml: str, warnings: []}
  │
  └─ core: deliver_score(result, field="musicxml", mode=return, stem="from-abc")
        ├─ inline (or auto ≤ SHEET_MUSIC_INLINE_MAX_BYTES, 8192): json.dumps(result, indent=2)
        └─ path (or auto above it): write <output root>/scores/from-abc-<ts>.musicxml,
              content[0] = {musicxml_path, warnings, score_summary}, content[1] = ResourceLink
```

---

## ABC Serializer

### Why a custom serializer?

music21 9.x removed ABC output support (`ConverterABC.registerOutputExtensions` is an empty tuple). A custom serializer was written that walks the music21 object model directly.

### ABC Tune Structure

Each part becomes one ABC tune. The header fields are:

```
X:1                 ← tune reference number (sequential)
T:Soprano           ← title / part name
M:4/4               ← time signature (from first TimeSignature in part)
L:1/8               ← default note length = eighth note
Q:1/4=120           ← quarter-note tempo (first MetronomeMark's number, else its sounding
                      tempo from a bare <sound tempo>, else 120)
K:C                 ← key (from first Key/KeySignature in part)
```

### Pitch Encoding

ABC v2.1 octave convention (uppercase C = C4 = middle C; music21 parses ABC the same way,
so ABC → MusicXML → ABC round-trips keep every note in its octave):

```
Octave 6:  c'  d'  e'  f'  g'  a'  b'
Octave 5:  c   d   e   f   g   a   b
Octave 4:  C   D   E   F   G   A   B     ← middle C
Octave 3:  C,  D,  E,  F,  G,  A,  B,
```

Accidentals:
- `^` = sharp, `^^` = double sharp
- `_` = flat, `__` = double flat

Implementation in `_pitch_to_abc(pitch)`:
```python
name = pitch.step          # "C", "D", ... "B"
octave = pitch.octave      # integer
accidental = pitch.accidental

if octave >= 5:
    base = name.lower()
    ticks = "'" * (octave - 5)
else:
    base = name.upper()
    ticks = "," * (4 - octave)

return accidental_prefix + base + ticks
```

### Duration Encoding

Base length is L:1/8 (one eighth note = 1 unit). Quarter note = 2 units.

```python
def _duration_to_abc(quarter_length):
    units = Fraction(quarter_length * 2).limit_denominator(64)
    if units == 1:
        return ""          # e.g. eighth note → "c" (no suffix)
    if units.denominator == 1:
        return str(units.numerator)   # e.g. quarter → "c2"
    return f"{units.numerator}/{units.denominator}"   # e.g. dotted → "c3/2"
```

### Note Token Formats

| Music | Token | Description |
|-------|-------|-------------|
| Single note (C4, quarter) | `c2` | pitch + duration |
| Chord (C4+E4, quarter) | `[ce]2` | `[pitches]duration` |
| Rest (quarter) | `z2` | `z` + duration |
| Single note (E4, eighth) | `e` | no duration suffix for 1 unit |

### Dynamics Handling

Any `music21.dynamics.Dynamic` object (forte, piano, crescendo, etc.) encountered while walking the measure is silently dropped. A warning is appended to the `warnings` list:

```
"Dynamic markings (forte, piano, etc.) were dropped — not supported in ABC v2.1"
```

### Bar Line Wrapping

Measures are serialized as bar strings (a series of note tokens). Multiple bars are joined with `|` separators and lines are wrapped at 78 characters to keep ABC files readable:

```
C2 D2 E2 F2 | G2 A2 B2 c2 | ...
```

---

## ABC Validation

`validate_abc(abc_str)` performs two stages:

1. **Header check** (lightweight, before music21):
   - `X:` field present (required)
   - `K:` field present (required)
   - `T:` field present (warning if missing, not an error)

2. **Parse check** (music21):
   - `music21.converter.parseData(abc_str, format="abc")`
   - Any exception → `errors` list
   - Returns `{valid: bool, errors: [...], warnings: [...]}`

---

## Error Handling

```json
{"error": "<message>", "error_code": "<CODE>"}
```

| Scenario | Code |
|----------|------|
| MusicXML parse failure | `INVALID_INPUT` |
| ABC parse failure | `INVALID_INPUT` |
| Requested part name not found | `INVALID_PARAMETER` |
| `measures` reversed, malformed or outside the score (`hint` names the score's bars) | `INVALID_PARAMETER` |
| `apply_abc_edit`: ABC bar count differs from the range, several tunes or voices, no `K:`, timewise score | `INVALID_INPUT` |
| Both or neither of `musicxml` / `musicxml_path`; path outside the read roots | `INVALID_PARAMETER` |
| Score file missing / too large | `FILE_NOT_FOUND` / `FILE_TOO_LARGE` |
| music21 conversion failure | `PROCESSING_FAILED` |

---

## Key Dependencies

| Package | Role |
|---------|------|
| `music21` ≥9.0 | MusicXML parsing, ABC parsing, MusicXML export |
| `fractions.Fraction` | Duration arithmetic (stdlib) |
| `mcp` | MCP protocol SDK |
| `sheet-music-mcp-core` | Shared error envelope, `ProcessingError`, handler wiring (input validation, error results) and score references (`load_score`, `deliver_score`, `describe_score`; 0.2.x); see [docs/conventions.md](../../docs/conventions.md#shared-core-library) |

No system libraries required. Pure Python.

---

## Known Limitations

| Limitation | Detail |
|-----------|--------|
| Dynamics not preserved | music21 Dynamic objects are dropped with a warning |
| Articulations not preserved | Trills, ornaments, slurs are not emitted |
| Lyrics not preserved | Not implemented in the custom serializer |
| Round-trip is lossy | Note content preserved ±2%; everything else may differ |
| `apply_abc_edit` replaces a bar's music | Dynamics, lyrics and articulations of edited bars are lost (warned); ABC `w:` lyrics and key/time/clef changes in the ABC are not applied; a multi-staff part is edited as a whole and new notes carry no `<staff>`; ties and slurs into or out of the range are not joined |

These limitations are by design and are documented in the `warnings` field of every `musicxml_to_abc` response.

---

## File Layout

```
musicxml-abc-mcp/
├── pyproject.toml
├── src/
│   └── musicxml_abc_mcp/
│       ├── __init__.py
│       ├── server.py     ← MCP layer (tool registration, dispatch)
│       ├── presenter.py  ← structuredContent + output schemas (ABC Workbench)
│       ├── abc_store.py  ← abc_id handles to musicxml_to_abc results
│       ├── engine.py     ← Conversion logic + custom ABC serializer
│       ├── abc_edit.py   ← apply_abc_edit: splice edited bars into the score text
│       ├── abc_bars.py   ← split ABC at its bar lines, one tune per bar
│       └── utils.py      ← Minimal input validation
└── tests/
    ├── test_server.py
    ├── test_score_references.py  ← musicxml_path, return modes, describe_score
    ├── test_measures.py  ← measures ranges (Wave 3): cut bars, carried K:/M:/Q:, errors
    ├── test_abc_workbench.py  ← ui:// resource, linking, structuredContent, get_abc
    ├── test_abc_store.py
    ├── test_content_golden.py  ← content byte-identical (golden/abc_content.json)
    ├── test_engine.py
    ├── test_abc_edit.py  ← apply_abc_edit engine (other parts identical, shell, divisions, warnings)
    ├── test_abc_bars.py  ← ABC bar splitting
    ├── test_apply_abc_edit_tool.py  ← apply_abc_edit tool: schema, paths, return modes, errors
    ├── edit_fixtures.py  ← three-part score and helpers for the edit tests
    ├── test_utils.py
    └── fixtures/
        ├── simple.musicxml
        ├── satb.musicxml
        └── simple.abc
```
