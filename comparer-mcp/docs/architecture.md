# MusicXML Comparer — Vision & Architecture

Created: 2026-03-26
Status: Implemented — Phases 1-4 complete (see `docs/HANDOVER.md`/`docs/PLAN.md` for current
state; this document is the original design vision and is annotated below where the
implementation diverged from it)
Parent research: [../../docs/musicxml-comparison-research.md](../../docs/musicxml-comparison-research.md)

---

## 1. Purpose

An independent MCP server (`comparer-mcp`) for **music-aware comparison** of two
MusicXML files. Like all servers in this project, it follows the conventions in
[../../docs/conventions.md](../../docs/conventions.md) and separates MCP protocol (`server.py`) from
business logic (`engine.py`). It provides a structured, multi-level diff report
that answers:

- **Are these the same piece?** (global similarity score)
- **What is the scale of difference?** (missing parts, measures, voices)
- **Where exactly do they differ?** (per-note detail with measure/beat locations)

### Primary use cases

| Use case | Description |
|----------|-------------|
| **Version / arrangement comparison** | Compare different versions of the same piece (e.g. simplified vs full arrangement, editor A vs editor B) to understand exactly what changed — added harmonies, removed voices, transposed sections, altered rhythms |
| **OMR quality evaluation** | Compare `omr-mcp` output against a known-good reference MusicXML to measure recognition accuracy |
| **Round-trip fidelity** | Verify MusicXML → ABC → MusicXML through `musicxml-abc-mcp` preserves music content |
| **Regression testing** | Detect regressions when OMR models or conversion logic change |
| **Score editing validation** | Confirm that LLM-driven edits (via ABC notation) only changed intended elements |
| **Choir rehearsal preparation** | A conductor compares two editions of a choral work to decide which to use, seeing at a glance which measures/voices differ |

---

## 2. High-Level Architecture

```
┌───────────────────────────────────────────────────────────┐
│                      MCP Client                           │
│        (Claude Desktop / web app / test script)           │
└──────────────────────────┬────────────────────────────────┘
                           │  stdio (JSON-RPC)
┌──────────────────────────▼────────────────────────────────┐
│                     server.py                             │
│                                                           │
│  compare_musicxml()             → full diff JSON           │
│  compare_musicxml_files()       → full diff JSON           │
│  quick_similarity()             → score + summary          │
│  list_changes()                 → filtered note diffs      │
│  generate_comparison_report()   → human-readable report    │
│  export_annotated_musicxml()    → colored MusicXML diff    │
│  health_check()                 → status                   │
│  list_capabilities()            → server metadata          │
└──────────────────────────┬────────────────────────────────┘
                           │
┌──────────────────────────▼────────────────────────────────┐
│                     engine.py                             │
│              (NO mcp imports — unit-testable)             │
│                                                           │
│  compare(ref_xml, tgt_xml, options) → ComparisonResult    │
│  compare_files(ref_path, tgt_path, options)               │
│  compare_with_annotations(...) → (result, ref, tgt, pairs) │
│                                                           │
│  Internally delegates to:                                 │
│   ┌─────────────────────────────────────────────────┐     │
│   │  1. PartMatcher  (part_matcher.py)              │     │
│   │     └─ 2. MeasureComparator (measure_comparator.py) │  │
│   │         └─ 3. NoteAligner (note_aligner.py)     │     │
│   └─────────────────────────────────────────────────┘     │
│  report.py / annotator.py consume ComparisonResult          │
│  downstream of engine.py, no mcp imports either             │
└──────────────────────────┬────────────────────────────────┘
                           │
┌──────────────────────────▼────────────────────────────────┐
│                    music21 library                         │
│   converter.parse() → Score → Part → Measure → Note       │
│   (a custom Wagner-Fischer edit-distance implementation    │
│   in note_aligner.py is used, not the alpha-status         │
│   alpha.analysis.aligner.StreamAligner — see §10/PLAN.md)  │
└───────────────────────────────────────────────────────────┘
```

---

## 3. Comparison Pipeline — Layer by Layer

### Layer 1: Score-Level Comparison

Compares the top-level structure of both scores.

**Inputs:** Two `music21.stream.Score` objects.

**Compares:**
- Number and names of parts (Soprano, Alto, Tenor, Bass)
- Title, composer metadata
- Total measure count

**Part matching strategy:**
Match parts between scores using a priority cascade:
1. Exact part name match (case-insensitive)
2. MIDI program / instrument match
3. Positional order (first↔first, second↔second)
4. Best-effort by note range (soprano range → soprano)

**Output:**
- List of matched part pairs: `[(part_a, part_b), ...]`
- Unmatched parts in A → "missing from target"
- Unmatched parts in B → "extra in target"

### Layer 2: Part-Level Comparison

For each matched part pair, compare structural attributes.

**Compares:**
- Key signatures and where they change
- Time signatures and where they change
- Clef assignments
- Measure count mismatch (part-local)

**Measure matching strategy:**
- Primary: Match by measure number
- Handle pickup measures (measure 0 or anacrusis)
- Handle repeat expansions / unrolling differences

**Output per part:**
- Measures present in A but missing in B (and vice versa)
- Key/time/clef signature differences with measure locations

### Layer 3: Measure-Level Comparison

For each matched measure pair within a part, compare contents.

**Compares:**
- Number of voices
- Total sounding duration
- Presence of rests vs notes

**Voice matching strategy:**
- Match by voice number (most MusicXML uses voice 1, 2, ...)
- Fallback: match by pitch range centroid if voice numbers differ

**As implemented:** only the voice-number match and a positional fallback exist
(`measure_comparator.match_voices`, same cascade shape as `part_matcher.py`). The pitch-range
centroid fallback described above was judged not worth the complexity — voice numbers are reliable
in practice — see `docs/PLAN.md` "Changed decisions".

**Output per measure:**
- Voice count mismatch
- Duration mismatch
- Flag: structurally identical / minor differences / major differences

### Layer 4: Voice-Level Alignment

For each matched voice pair within a measure, align the note sequences.

**Core algorithm:** Edit-distance alignment (Levenshtein-style / Wagner-Fischer).

**As implemented:** a custom Wagner-Fischer implementation in `note_aligner.py`, not
`music21.alpha.analysis.aligner.StreamAligner` — the alpha API's interface didn't map cleanly onto
the MATCH/PITCH_CHANGE/DURATION_CHANGE/SUBSTITUTION/INSERTION/DELETION classification this project
needs, and alpha APIs may change without notice. See `docs/PLAN.md` "Changed decisions".

**Hash dimensions per note element:**
- MIDI pitch (integer)
- Duration in quarter lengths (float)
- Is rest (boolean)
- Is chord (boolean) — and if so, all pitches sorted

**Operations detected:**
| Operation | Meaning |
|-----------|---------|
| `MATCH` | Notes are identical |
| `PITCH_CHANGE` | Same position/duration, different pitch |
| `DURATION_CHANGE` | Same pitch, different duration |
| `SUBSTITUTION` | Both pitch and duration differ |
| `INSERTION` | Note present in target but not reference |
| `DELETION` | Note present in reference but not target |

### Layer 5: Note-Level Detail

For each non-matching note pair, produce a detailed diff.

**Compares (when both notes exist):**
- Pitch: MIDI number, enharmonic spelling, octave
- Duration: quarter-length value, notated type (eighth, quarter, etc.)
- Accidentals: explicit vs implied by key signature
- Ties: start/stop/continue
- Articulations: staccato, accent, fermata, etc.
- Dynamics: attached dynamic markings
- Lyrics: text syllables

**Output per note diff:**
```python
NoteDiff(
    measure_number=14,
    beat=2.5,
    voice=1,
    operation="PITCH_CHANGE",
    reference=NoteInfo(pitch="C#5", duration=0.5, midi=73),
    target=NoteInfo(pitch="D5", duration=0.5, midi=74),
    interval_error=1,  # semitones off
)
```

---

## 4. Data Model

```python
@dataclass
class ComparisonResult:
    """Top-level result of comparing two MusicXML files."""
    similarity_score: float          # 0.0 (completely different) – 1.0 (identical)
    summary: ComparisonSummary
    part_diffs: list[PartDiff]

@dataclass
class ComparisonSummary:
    """Aggregate statistics."""
    total_parts_reference: int
    total_parts_target: int
    parts_matched: int
    parts_missing: list[str]         # in reference but not target
    parts_extra: list[str]           # in target but not reference
    total_measures: int
    measures_missing: int
    measures_extra: int
    total_notes_compared: int
    notes_identical: int
    notes_pitch_changed: int
    notes_duration_changed: int
    notes_substituted: int
    notes_missing: int               # in reference but not target
    notes_extra: int                 # in target but not reference
    key_signature_diffs: int
    time_signature_diffs: int

@dataclass
class PartDiff:
    """Comparison result for one matched pair of parts."""
    part_name: str
    reference_part_id: str
    target_part_id: str
    similarity_score: float
    key_sig_diffs: list[SignatureDiff]
    time_sig_diffs: list[SignatureDiff]
    measure_diffs: list[MeasureDiff]
    measures_missing: list[int]      # measure numbers
    measures_extra: list[int]

@dataclass
class MeasureDiff:
    """Comparison result for one matched pair of measures."""
    measure_number: int
    similarity_score: float
    voice_count_reference: int
    voice_count_target: int
    note_diffs: list[NoteDiff]

@dataclass
class NoteDiff:
    """Single note-level difference."""
    measure_number: int
    beat: float                      # beat position within measure
    voice: int
    operation: str                   # MATCH | PITCH_CHANGE | DURATION_CHANGE | ...
    reference: NoteInfo | None       # None for INSERTION
    target: NoteInfo | None          # None for DELETION
    interval_error: int | None       # semitones, for pitch differences

@dataclass
class NoteInfo:
    """Snapshot of a single note's properties."""
    pitch: str                       # e.g. "C#5", "rest"
    midi: int | None                 # MIDI number, None for rests
    duration: float                  # in quarter lengths
    duration_type: str               # "quarter", "eighth", etc.
    is_rest: bool
    is_chord: bool
    tie: str | None                  # "start" | "stop" | "continue" | None
    lyrics: str | None

@dataclass
class SignatureDiff:
    """Key or time signature that differs between reference and target."""
    measure_number: int
    reference_value: str             # e.g. "G major", "3/4"
    target_value: str | None         # None if missing
```

---

## 5. Similarity Score Calculation

The global `similarity_score` is a weighted aggregate:

```
similarity = w_structure × structure_score + w_notes × note_score

where:
  structure_score = matched_parts / max(parts_ref, parts_tgt)
                  × matched_measures / max(measures_ref, measures_tgt)

  note_score = (notes_identical + 0.5 × partial_matches) / total_notes_compared

  partial_matches = notes with only pitch OR only duration wrong

Default weights:
  w_structure = 0.3
  w_notes     = 0.7
```

This ensures that a file with the right structure but many wrong notes still
scores lower than a file that gets most notes right but is missing a measure.

---

## 6. Public API

```python
from comparer_mcp.engine import compare, compare_files

# From file paths
result: ComparisonResult = compare_files(
    reference="reference.musicxml",
    target="omr_output.musicxml",
)

# From MusicXML strings
result: ComparisonResult = compare(
    reference_xml="<score-partwise>...</score-partwise>",
    target_xml="<score-partwise>...</score-partwise>",
)

# Quick similarity check
score = result.similarity_score          # 0.0 – 1.0

# Summary
print(result.summary.notes_missing)      # 3
print(result.summary.parts_missing)      # ["Alto"]

# Iterate note-level diffs
for part_diff in result.part_diffs:
    for measure_diff in part_diff.measure_diffs:
        for note_diff in measure_diff.note_diffs:
            if note_diff.operation != "MATCH":
                print(f"m{note_diff.measure_number} beat {note_diff.beat}: "
                      f"{note_diff.operation} "
                      f"{note_diff.reference} → {note_diff.target}")

# Structured export
import json
print(json.dumps(result.to_dict(), indent=2))
```

---

## 7. Module Layout

```
comparer-mcp/
├── pyproject.toml
├── .python-version              # 3.11
├── README.md
├── SETUP.md
├── TROUBLESHOOTING.md
├── install.sh
├── .github/
│   └── copilot-instructions.md
├── src/
│   └── comparer_mcp/
│       ├── __init__.py
│       ├── server.py            # MCP tool definitions, dispatches to engine
│       ├── engine.py            # ScoreComparator — orchestrates the pipeline
│       │                        # (NO mcp imports — independently testable)
│       ├── part_matcher.py      # Part matching logic (name, instrument, range)
│       ├── measure_comparator.py # Measure-level structural comparison
│       ├── note_aligner.py      # Voice/note alignment using edit distance
│       ├── models.py            # Dataclasses: ComparisonResult, NoteDiff, etc.
│       ├── report.py            # Phase 4: human-readable comparison report (pure ComparisonResult -> str)
│       ├── annotator.py         # Phase 4: colored MusicXML diff export (music21, no mcp import)
│       └── utils.py             # Validation, pitch names, duration formatting
├── tests/
│   ├── __init__.py
│   ├── test_engine.py           # End-to-end comparison tests (unit + integration)
│   ├── test_server.py           # Tool schemas, error propagation, list_capabilities
│   ├── test_part_matcher.py     # Part matching edge cases
│   ├── test_note_aligner.py     # Alignment algorithm tests
│   ├── test_measure_comparator.py # Key/time signature + voice matching tests
│   ├── test_report.py           # generate_comparison_report tests
│   ├── test_annotator.py        # export_annotated_musicxml tests
│   └── test_utils.py
│   # No static tests/fixtures/ directory: unit-test fixtures are built
│   # programmatically via music21 objects (see docs/PLAN.md "Changed decisions");
│   # the 7 @pytest.mark.integration tests instead read real compressed .mxl SATB
│   # samples from ../omr-mcp/test_samples/pdmx_satb_samples/mxl/, shared with omr-mcp.
├── examples/
│   ├── claude_desktop_config.json
│   ├── continue_config.json
│   ├── cursor_mcp.json
│   ├── windsurf_mcp.json
│   └── zed_settings.json
└── docs/
    ├── HANDOVER.md
    ├── PLAN.md
    ├── requirements.md
    └── architecture.md          # (this document)
```

---

## 8. MCP Server — Tools

`comparer-mcp` is a full MCP server, deployed identically to the other servers
(stdio transport, `uv run comparer-mcp`). All tool handlers are `async def`.
All error responses use `{"error": "...", "error_code": "..."}` per conventions.

| Tool | Input | Output |
|------|-------|--------|
| `compare_musicxml` | `reference_xml` (string), `target_xml` (string), optional `options` | Full `ComparisonResult` JSON |
| `compare_musicxml_files` | `reference_path` (string), `target_path` (string), optional `options` | Full `ComparisonResult` JSON |
| `quick_similarity` | `reference_xml` (string), `target_xml` (string) | `{ "similarity_score": 0.87, "summary": {...} }` |
| `list_changes` | `reference_xml`, `target_xml`, optional `part` filter, optional `measure_range` | Filtered list of `NoteDiff` entries (for targeted queries) |
| `generate_comparison_report` | `reference_xml`, `target_xml`, optional `options` | `{ "report": "...", "similarity_score": 0.87 }` — human-readable summary |
| `export_annotated_musicxml` | `reference_xml`, `target_xml`, optional `options` | `{ "reference_annotated_musicxml": "...", "target_annotated_musicxml": "...", "similarity_score": ..., "legend": {...} }` |
| `health_check` | — | `{ "status": "ok", "music21_version": "..."}` |
| `list_capabilities` | — | Server metadata per conventions |

### Options object

```json
{
  "expand_repeats": false,        // unfold repeats before comparing (default: false — opt-in, see docs/PLAN.md)
  "normalize_pitch": false,       // transpose to concert pitch (default: false)
  "ignore_articulations": false,  // skip articulation comparison (default: false)
  "part_filter": ["Soprano"],     // compare only named parts (default: all)
  "measure_range": [1, 32]        // compare only measures 1–32 (default: all)
}
```

### Engine reuse

`engine.py` contains all comparison logic with no MCP imports, so it can also be
imported directly by other servers or test scripts:

```python
from comparer_mcp.engine import compare, compare_files
result = compare_files("version_a.musicxml", "version_b.musicxml")
```

---

## 9. Dependencies

| Package | Purpose | License |
|---------|---------|---------|
| `mcp>=2.2.0,<3.0.0` | MCP server framework | MIT |
| `jsonschema>=4.20.0` | Tool input validation | MIT |
| `music21` | MusicXML parsing, score object model, stream alignment | BSD-3 |
| `numpy` | Distance matrix in alignment (transitive via music21) | BSD-3 |

Dev dependencies: `pytest`, `pytest-asyncio` (per conventions).

---

## 10. Edge Cases & Design Decisions

| Edge case | Decision |
|-----------|----------|
| Different `<divisions>` values | music21 normalizes these on parse — no special handling needed |
| Enharmonic spelling (C# vs Db) | Compare by MIDI pitch number, flag spelling difference as informational |
| Pickup measures (anacrusis) | Match by measure number; measure 0 is pickup |
| Transposed scores | Compare as-written by default; option to normalize to concert pitch |
| Repeat signs expanded vs collapsed | Pre-process: use music21's `expandRepeats()` on both before comparing |
| Grace notes | Include in alignment with duration 0; flag as grace in `NoteInfo` |
| Chord notes | Hash all pitches sorted ascending; compare as sets |
| Missing voice numbers | Fall back to pitch-range matching between voices |
| Empty measures (multi-rest) | Treat as a single whole-rest; match structurally |
| Same piece, different arrangement | Works naturally — parts/voices added or removed show as missing/extra; note changes show as substitutions |
| Simplified vs full score | Part matcher handles unequal part counts; unmatched parts listed separately |
| Different editions / publishers | music21 normalizes formatting; comparison focuses on musical content not layout |

---

## 11. Implementation Phases

### Phase 1 — Core comparison (MVP) — COMPLETE

- [x] Parse two MusicXML files via music21
- [x] Match parts by name
- [x] Compare measure counts per part
- [x] Align notes within matched measures (pitch + duration)
- [x] Produce `ComparisonResult` with summary + similarity score
- [x] Unit tests with simple SATB fixtures

### Phase 2 — Rich detail — COMPLETE

- [x] Key/time signature comparison
- [x] Voice-aware alignment (multi-voice measures)
- [x] Detailed `NoteDiff` with beat positions
- [x] Articulation and tie comparison
- [x] `to_dict()` / JSON export

### Phase 3 — MCP server & integration — COMPLETE

- [x] `server.py` with all 6 tools (compare, compare_files, quick_similarity, list_changes, health_check, list_capabilities)
- [x] `test_server.py` — tool schemas, error propagation
- [x] Integration tests with real MusicXML fixtures (`@pytest.mark.integration`)
- [x] `install.sh`, `SETUP.md`, `TROUBLESHOOTING.md`, client config examples
- [ ] Integration with omr-mcp test suite (import engine directly) — deferred, not part of the Phase 3 scope in docs/PLAN.md
- [ ] Batch comparison CLI for evaluating OMR across sample sets — not part of Phase 3 or Phase 4's
      scope in docs/PLAN.md; remains a stretch item (see docs/HANDOVER.md "Next steps (beyond Phase 4)")

### Phase 4 — Advanced features — COMPLETE

- [x] `options` dict wired up (`part_filter`, `measure_range`, `ignore_articulations`,
      `normalize_pitch`, `expand_repeats`)
- [x] Version comparison report: human-readable summary (`report.py`, `generate_comparison_report`
      tool) — grounded in computed diff data (measure-range grouping, constant-`interval_error`
      transposition detection), not full semantic/arrangement-intent inference
- [x] Diff export to MusicXML with colored annotations (`annotator.py`, `export_annotated_musicxml`
      tool) — chainable directly into render-mcp's `render_to_pdf`/`render_to_image` for
      visualization, without comparer-mcp calling render-mcp directly (see §2: independent servers)
