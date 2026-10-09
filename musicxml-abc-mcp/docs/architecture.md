# musicxml-abc-mcp — Technical Architecture

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
│  list_tools()   → 4 tool definitions                      │
│  call_tool()    → dispatches to engine                    │
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
           │
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

- Registers four tools: `musicxml_to_abc`, `abc_to_musicxml`, `validate_abc`, `list_capabilities`
- Validates parameters (via `utils.py`) before calling engine
- Converts engine results and `ProcessingError` exceptions to `TextContent` JSON
- Entry point via `mcp.server.stdio.stdio_server()`

### `engine.py`

All conversion and serialization logic. No MCP imports.

**High-level functions:**

| Function | Description |
|----------|-------------|
| `musicxml_to_abc(musicxml_str, part_id)` | Parse MusicXML; serialize each part to ABC tune |
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
| `_find_title(part, score)` | Extract title from score metadata |
| `_is_dynamic(elem)` | True if element is a music21 Dynamic |

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
call_tool("musicxml_to_abc", {musicxml, part_name: "Soprano"})
  │
  ├─ utils: validate_musicxml
  │
  └─ engine: musicxml_to_abc(musicxml, part_id="Soprano")
        │
        ├─ score = music21.converter.parseData(musicxml, format="musicxml")
        │
        ├─ if part_id given:
        │     find part where part.id == "Soprano"
        │     error if not found (list valid part IDs)
        │     parts = [soprano_part]
        │
        ├─ for i, part in enumerate(parts):
        │     (tune_str, warnings) = _part_to_abc_tune(part, tune_num=i+1, score)
        │
        ├─ join tune strings with "\n\n"
        └─ return {abc: str, parts_included: [...], warnings: [...]}
```

### ABC → MusicXML

```
call_tool("abc_to_musicxml", {abc})
  │
  └─ engine: abc_to_musicxml(abc_str)
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
Q:120               ← tempo in BPM (from first MetronomeMark, or 120)
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
| music21 conversion failure | `PROCESSING_FAILED` |

---

## Key Dependencies

| Package | Role |
|---------|------|
| `music21` ≥9.0 | MusicXML parsing, ABC parsing, MusicXML export |
| `fractions.Fraction` | Duration arithmetic (stdlib) |
| `mcp` | MCP protocol SDK |

No system libraries required. Pure Python.

---

## Known Limitations

| Limitation | Detail |
|-----------|--------|
| Dynamics not preserved | music21 Dynamic objects are dropped with a warning |
| Articulations not preserved | Trills, ornaments, slurs are not emitted |
| Lyrics not preserved | Not implemented in the custom serializer |
| Round-trip is lossy | Note content preserved ±2%; everything else may differ |

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
│       ├── engine.py     ← Conversion logic + custom ABC serializer
│       └── utils.py      ← Minimal input validation
└── tests/
    ├── test_server.py
    ├── test_engine.py
    ├── test_utils.py
    └── fixtures/
        ├── simple.musicxml
        ├── satb.musicxml
        └── simple.abc
```
