# UX Wave 3 plan: practice features

**Status:** In progress (see Progress).
**Date:** 2026-10-27
**Parent:** [ux-architecture-and-tool-improvements.md](ux-architecture-and-tool-improvements.md),
roadmap wave 3 (C8–C11, C13, B2, C19, C22).
**Builds on:** [ux-wave2-plan.md](ux-wave2-plan.md) (core 0.2.0), [handover](ux-wave3-handover.md).

## Progress

| Step | Content | Status |
|---|---|---|
| 1 | Plan, owner interview (§8), conventions contract (Measure Ranges, Practice Audio) | ✅ |
| 2 | Core 0.3.0: `measures`, `scores.first_pitches`, `content.audio_block` | ⬜ |
| 3 | Servers: synth (C8–C11, C13, B2), pitch (C19, C22, B2), render and abc (B2), comparer (rename) | ⬜ |
| 4 | Review, relock, docs and status tables, PR | ⬜ |

---

## 1. Goal and scope

Wave 3 turns the tools into a practice kit: play *my* part loud, bars 17–24, three times, with a
count-in; give me the starting notes; tell me in plain words where I went flat. These unlock the
Practice Player and Practice Coach apps ([MCP Apps proposal §5.1–5.2](mcp-apps-ux-proposal.md)).

| Item | What ships | Servers |
|---|---|---|
| **B2** | `measures: [start, end]`, inclusive, **printed** measure numbers (W3-3). The score is cut down to those bars before the engine sees it, keeping the key, time, clef, divisions and tempo in force at `start`. comparer's `options.measure_range` becomes `options.measures` (deprecated alias). | core, render, synth, abc, pitch, comparer |
| **C8** | `part_gains` (0.0–2.0 per part, MIDI CC7) plus `preset: "learning" \| "karaoke" \| "equal"` and `focus_part` (W3-1, W3-2). | synth |
| **C9** | `measures` (B2) and `repeat: 1–20`. | synth |
| **C10** | `count_in_bars: 0–4` and `metronome: bool`, wood-block clicks on GM channel 10 (W3-4). | synth |
| **C11** | `timbre: "score" \| "piano" \| "choir" \| "organ"`, default `"score"` (W3-5). | synth |
| **C13** | New tool `starting_pitches`: each part's first note, then the chord, as text plus a short WAV, inline when ≤ 200 KB; text only when audio is unavailable (W3-6). | core, synth |
| **C19** | New tool `start_practice` = `load_score` + `start_monitoring` in one call. | pitch |
| **C22** | `highlights[]` in `analyze_recording` and in `stop_monitoring` summaries (W3-7). | pitch |

### Out of scope

- Repeat and volta expansion (bars play as written, W3-3).
- `measures` on omr (it produces scores, it does not take them) and on `get_parts` /
  `describe_score`.
- Removing the deprecated Wave 1 aliases, confining image/audio inputs (W2-3), `scores/` cleanup.
- MCP Apps UIs. The presets here are what a UI would call; the UI itself is a later wave.

---

## 2. Definition of done

| # | Criterion |
|---|---|
| DoD-1 | Every server's existing default `pytest` run passes unchanged: every new parameter is optional and its default keeps today's behaviour (no CC7, no program change, no clicks, the whole score). |
| DoD-2 | The acceptance tests in §4 pass, including the two from proposal §7 (C8). |
| DoD-3 | `docs/conventions.md` describes Measure Ranges and Practice Audio before any server implements them. |
| DoD-4 | `measures` imports neither `mcp` nor `music21`; it parses with `scores.parse_score` (defusedxml) and parses numbers with bounded patterns. |
| DoD-5 | synth's MIDI features are tested at MIDI level (no FluidSynth in CI or this container); audio code paths that need FluidSynth are integration tests or mocked. |
| DoD-6 | Core 0.3.0 is released before the servers; servers depend on `sheet-music-mcp-core>=0.3.0,<0.4.0`. Waves 1–3 ship in the same server minors (W3-8). |

---

## 3. Design

### 3.1 Core 0.3.0

```
sheet_music_mcp_core
├── measures   (no mcp)  NEW  schema property, validation, printed numbers, select_measures()
├── scores     (no mcp)       + first_pitches()
└── content    (mcp)          + audio_block()
```

**`measures`** (MCP-free, music21-free; engines import it)

| Name | Behaviour |
|---|---|
| `MEASURES_PROPERTY` | `{"measures": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 99999}, "minItems": 2, "maxItems": 2, "description": "Inclusive [start, end] range of printed measure numbers, e.g. [17, 24]. A pickup bar is 0."}}` (read-only mapping, like `RETURN_PROPERTY`) |
| `parse_range(value, *, param="measures")` | `None` → `None`. Otherwise a 2-item list/tuple of non-bool ints, `0 ≤ start ≤ end ≤ 99999` → `(start, end)`. Anything else → `MeasureRangeError` with a hint showing the expected shape. For direct engine calls and `options` dicts, which the top-level schema does not check |
| `printed_numbers(root)` | Printed number of each measure of the first part, in written order: the leading integer of `number` (`"12a"` → 12, `"7"` → 7). A first measure with `implicit="yes"` is 0. A number without a leading integer (`"X1"`, `""`) takes the previous measure's number (0 for the first). Parsed with `\d{1,6}`, never `int()` on raw text |
| `select_measures(text, measures)` | Returns MusicXML text (UTF-8, with an XML declaration) holding only the measures whose printed number `n` satisfies `start ≤ n ≤ end`, in every part (by position, taken from the first part). The first kept measure gets the state in force before it: the latest `divisions`, `key`, `time`, `clef` (per staff number), `staves` and `transpose`, merged into its `<attributes>` where it does not set them itself, and the latest tempo (a `<sound tempo>`) when it has none. `<print>` page or system breaks in the first kept measure are dropped. Header elements (`work`, `identification`, `part-list`, credits) are kept. Timewise scores are filtered by the top-level `<measure>` number. `measures=None` returns `text` unchanged |
| `MeasureRangeError` | `ProcessingError` with code `INVALID_PARAMETER` and a `hint`: `"This score has measures 0–24."` (the first and last printed numbers). Raised when `start > end`, `start` is below the first printed number, `end` is above the last, or no measure falls in the range |

Repeats are not expanded and voltas are not skipped: bars are taken as written (W3-3). `select_measures` never echoes score text in errors.

**`scores.first_pitches(text)`**

Returns `[{"id", "name", "abbreviation", "label", "pitch", "midi"}]`, one per `score-part`, in score
order. `pitch` is the **sounding** pitch of the part's first pitched note in written order (rests and
unpitched notes skipped; in a chord, the first written note), using the same transposition rules as
`describe_score`'s `range`, so `first_pitches(t)[i]["pitch"]` is always within that part's range.
`midi` is the MIDI note number (C4 = 60). Both are `None` for a part without pitches. `label` is the
voice abbreviation when the part name maps to a voice role (`S`, `A`, `T`, `B`, `Ms`, `Ct`, `Bar`,
with a divisi number: `S1`), else the part's abbreviation, else its name, else its ID.

**`content.audio_block(path, *, max_bytes=AUDIO_MAX_BYTES)`**

`AUDIO_MAX_BYTES = 200 * 1024`. Like `png_block`: the WAV at `path` as `AudioContent`
(`mime_type="audio/wav"`), or `None` when the file is larger; size checked before reading.

### 3.2 synth-mcp

`synthesize` gains (all optional): `measures`, `repeat` (1–20, default 1), `count_in_bars` (0–4,
default 0), `metronome` (bool, default false), `timbre` (`score` | `piano` | `choir` | `organ`,
default `score`), `part_gains` (object, part ID/name/voice → number 0.0–2.0), `preset`
(`learning` | `karaoke` | `equal`) and `focus_part` (part ID, name or voice).

Pipeline in `extract_midi` (each step its own small function, so each is testable on its own):

1. `select_measures(text, measures)` (core) before music21 parses the score.
2. Parse, select parts (unchanged).
3. `repeat`: append the selected music `repeat − 1` more times (whole bars, ties not carried
   across the join).
4. Tempo factor (unchanged).
5. Count-in and metronome on a separate percussion part on MIDI channel 10: `count_in_bars` bars
   of clicks in the time signature and scaled tempo in force at the first bar, shifting the music
   later by that length; with `metronome`, clicks on every beat of the music too. Beats follow
   music21's `TimeSignature.beatCount` (6/8 = 2 beats). Accented beat 1: GM 76 (hi wood block),
   other beats: GM 77 (low wood block).
6. Export to MIDI with music21, then post-process the `MidiFile` per melodic track: `timbre`
   sets one program change (piano 0, choir 52, organ 19) on every melodic channel; gains insert one
   CC7 at tick 0 per melodic channel: `cc7 = round(127 × gain / 2)` (0 → 0, 1.0 → 64, 1.5 → 95,
   2.0 → 127). No melodic track uses channel 10.

Gains: `preset` + `focus_part` give the base gains (W3-2): learning focus 1.5 / others 0.5,
karaoke focus 0 / others 1.0, equal all 1.0. `part_gains` entries (resolved with
`resolve_parts`) override the preset per part. Parts without an entry get 1.0. No `part_gains`
and no `preset` → no CC7 at all (today's MIDI). `preset` `learning` / `karaoke` without
`focus_part` → `INVALID_PARAMETER` with the part `choices`. `focus_part` and `part_gains` keys
must name a selected part, else `INVALID_PARAMETER` with `choices`. Gains outside 0.0–2.0 are
rejected by the schema (`minimum`/`maximum` on `additionalProperties`).

**`starting_pitches`** (new tool, `WRITES_FILE`, title "Play starting pitches"): takes `musicxml` /
`musicxml_path` (exactly one) and optional `parts`. Text from `scores.first_pitches`, joined in
score order: `"S: D5, A: A4, T: F#4, B: D3"` (parts without pitches are left out). Clip: piano
(program 0), each selected part's first note for 1 s in score order, then all of them together for
2 s, at velocity 80. The WAV is rendered with the existing FluidSynth path, then downmixed to mono
16 kHz 16-bit (about 32 KB/s, so a 4-part clip is about 192 KB) and written to
`<output root>/audio/starting-pitches-<timestamp>.wav` (`paths.new_output_path(..., subdir="audio")`),
or to `output_path` when given (confined like `synthesize`). Content:
`content[0]` = `{"text", "parts": [{"id", "name", "label", "pitch"}], "audio_path", "duration_seconds"}`,
then `audio_block(...)` when ≤ 200 KB, then `file_link(audio_path, "audio/wav")`. Without a
soundfont or FluidSynth: `content[0]` has `"audio_path": null` and
`"audio_unavailable": "<reason>"`, no other blocks, and it is **not** an error (W3-6).

### 3.3 pitch-mcp

- `measures` on `load_score`, `analyze_recording` and `start_practice`: the engine calls
  `select_measures` before `extract_part_notes`, so the session timeline starts at `start` and
  reported measures keep their printed numbers.
- **`start_practice`** (new tool, `SESSION_STATE`, title "Start practice"): `musicxml` /
  `musicxml_path`, `part` (required), `tempo_bpm`, `measures`. Returns `load_score`'s fields plus
  `start_monitoring`'s (`session_id` once). If the microphone fails to open, the session just
  loaded is removed before the error is returned, so no orphan session is left.
- **`highlights`** (W3-7): `aligner.highlights(note_results, *, threshold=25, min_run=2, limit=3)`.
  Entries are first grouped into notes: consecutive entries with the same `(measure, beat,
  expected)` are one note (live history has one entry per frame) with the median cents. A run is
  ≥ `min_run` consecutive notes all flat (`< −threshold`) or all sharp (`> threshold`); a
  `no_signal` or on-pitch note ends it. Runs are ranked by `notes × |avg cents|`, the top
  `limit` are returned in that order as
  `{"direction": "flat"|"sharp", "measures": [first, last], "notes": n, "avg_cents": c, "text": ...}`.
  Text: `"flat on E5 in m.12–14 (-35 cents avg)"` when every note of the run is the same pitch,
  else `"flat in m.12–14 (-35 cents avg over 4 notes)"`; one measure is `"m.12"`; ASCII minus,
  en dash between measures. `summarize()` adds `highlights`, so both `analyze_recording` and the
  `stop_monitoring` summary carry it.

### 3.4 render, abc, comparer

| Server | Change |
|---|---|
| render | `measures` on `render_to_pdf` and `render_to_image`; `select_measures` before either backend (MuseScore and Verovio see the same cut score). |
| abc | `measures` on `musicxml_to_abc`; `select_measures` before music21 parses. |
| comparer | `options.measures` with `options.measure_range` as a deprecated alias (`params.aliased` on the options dict); `_validate_measure_range` becomes `measures.parse_range(..., param="options.measures")`. Semantics stay as today: differences are filtered by printed measure number, the scores are not cut. |

Every server that adds `measures` adds one line to its `instructions`, and its
`list_capabilities.input_parameters` (where present) lists the new parameters.

---

## 4. Tests first

Core (`sheet-music-mcp-core/tests/`):

- `test_measures.py`: `parse_range` accepts `[3, 4]`, `(3, 4)`, `None`; rejects `[4, 3]`, `[3]`,
  `[True, 4]`, `["3", "4"]`, `[-1, 2]`, `[1, 100000]` with `INVALID_PARAMETER`. `printed_numbers`
  on a pickup score gives `[0, 1, 2, …]`, `"12a"` → 12, `"X1"` → previous. `select_measures([3, 4])`
  on a 6-bar SATB fixture keeps exactly bars 3–4 in every part; a key/time/clef change in bar 2 is
  in force in the cut score's first bar; a tempo set in bar 1 is carried; `[0, 0]` on a pickup score
  keeps only the pickup; `[5, 99]` and `[4, 3]` raise `MeasureRangeError` whose hint names the
  score's first and last numbers; `describe_score(select_measures(t, [3, 4]))["measures"] == 2`;
  a timewise fixture; the result parses with `parse_score`; `None` returns the text unchanged.
- `test_scores.py`: `first_pitches` on the SATB fixture gives labels `S A T B` and pitches inside
  each part's `describe_score` range; a part of rests only gives `None`; a transposing part gives
  the sounding pitch; an unnamed part's label falls back to its ID.
- `test_content.py`: `audio_block` returns `AudioContent` with `audio/wav` at the limit and `None`
  one byte above it.
- `test_import_isolation.py`: `measures` imports neither `mcp` nor `music21`.

synth (`tests/test_practice_midi.py`, `tests/test_starting_pitches.py`), inspecting MIDI bytes with
`music21.midi.MidiFile`:

- C8: `part_gains={"P2": 0}` → CC7 = 0 on P2's channel (proposal §7). `preset="learning",
  focus_part="Alto"` → Alto's CC7 is above every other part's (proposal §7). Karaoke → focus 0,
  others 64. `part_gains` overrides the preset for that part. No gains → no CC7 events. Learning
  without `focus_part` and an unknown `part_gains` key → `INVALID_PARAMETER` with `choices`.
- C9: `measures=[3, 4]` → the MIDI is two bars long; `repeat=3` → three times the `repeat=1`
  length; `measures` out of range → `INVALID_PARAMETER` with the hint.
- C10: `count_in_bars=1` in 4/4 → four channel-10 note-ons (76, 77, 77, 77) before the first
  melodic note-on, which is one bar later than without count-in; `metronome=True` → a click on
  every beat through the music; 6/8 → two clicks per bar; defaults → no channel-10 events.
- C11: `timbre="organ"` → program 19 on every melodic channel; `"score"` → today's programs.
- C13: text `"S: …, A: …, T: …, B: …"` matches `first_pitches`; the clip MIDI holds one note per
  part, then the chord; with no soundfont the result has `audio_unavailable` and is not an error;
  with `synthesize_midi` mocked to write a WAV, the result has `AudioContent` when small and only a
  link when large; the downmix gives mono 16 kHz.
- Schema: every new property is in `synthesize`'s input schema; `starting_pitches` is listed with
  its title and `WRITES_FILE`.

pitch (`tests/test_practice.py`, `tests/test_highlights.py`):

- C19: with the stream factory faked, `start_practice` returns a monitoring session whose fields
  equal `load_score` + `start_monitoring`; a mic failure leaves `list_sessions` empty; the tool is
  `SESSION_STATE`.
- B2: `load_score(measures=[3, 4])` → `measure_count` 2 and the first note's measure is 3;
  `analyze_recording` with `measures` reports only those measures.
- C22: four flat notes in m.12–14 averaging −35 c → exactly one highlight,
  `"flat on E5 in m.12–14 (-35 cents avg)"` when all are E5; a single flat note → none; a
  `no_signal` note splits a run; four runs → the three ranked highest; frame-level history
  (several entries per note) gives the same highlight as note-level results.

render, abc: `measures=[3, 4]` passes only those bars to the backend (mock the backend and inspect
its input with `describe_score`); out of range → `INVALID_PARAMETER`. comparer: `options.measures`
gives the same result as `options.measure_range`; both with different values →
`INVALID_PARAMETER`; the deprecation warning is logged once.

---

## 5. Steps and subagents

1. **Me:** this plan, the interview and the conventions contract.
2. **One subagent:** core 0.3.0 test-first against §3.1. I review the diff before step 3.
3. **Five subagents in parallel**, one per server directory (disjoint files): synth, pitch,
   render, abc, comparer. Shared brief in the scratchpad. Each bumps the core constraint to
   `>=0.3.0,<0.4.0`, relocks with `uvx --from 'uv==0.13.6' uv lock` and updates its docs
   (`CLAUDE.md`, `.github/copilot-instructions.md`, `docs/requirements.md`, `docs/architecture.md`).
4. **Me:** review each diff, run every suite, commit per server, update root `CLAUDE.md`,
   `README.md`, `.github/copilot-instructions.md` and this plan, open the PR.

---

## 6. Release sequencing

Waves 1–3 ship together (W3-8):

1. Publish `sheet-music-mcp-core` 0.3.0 (tag `sheet-music-mcp-core/v0.3.0`, after the PyPI pending
   publisher is added). 0.1.0 and 0.2.0 were never published and are skipped.
2. Then bump and tag the servers: omr 0.3.0, render 0.3.0, synth 0.3.0, musicxml-abc 0.3.0,
   pitch 0.4.0, comparer 0.3.0.

---

## 7. Outcome and follow-ups

*(Filled in at step 4.)*

---

## 8. Decisions

Agreed with the project owner on 2026-10-27.

| # | Question | Decision |
|---|---|---|
| W3-1 | Presets on the tool or only in the UI (D3)? | **On the tool**: `preset` + `focus_part` compute the gains; explicit `part_gains` entries override them. Hosts without MCP Apps get learning tracks in one call. Supersedes the "UI-side only" part of D3. |
| W3-2 | Preset numbers | **D3's values**: learning focus 1.5 / others 0.5; karaoke focus 0 / others 1.0; equal 1.0. |
| W3-3 | Measure numbering | **Printed numbers in written order.** Pickup is 0; `"12a"` belongs to 12; repeats are not expanded. Out-of-range or reversed → `INVALID_PARAMETER` with the score's range as hint. |
| W3-4 | Count-in and metronome | Score's time signature and scaled tempo; GM 76 hi wood block on beat 1, 77 low wood block on other beats; `count_in_bars` default 0, `metronome` default false. |
| W3-5 | Timbre default | **`"score"`**: music21's instrument as today; piano, choir and organ are opt-in. |
| W3-6 | `starting_pitches` output | Always text; WAV written and inline `AudioContent` when ≤ 200 KB; without FluidSynth or a soundfont, text plus `audio_unavailable`, not an error. Each note 1 s, then the chord 2 s, piano. |
| W3-7 | Highlight thresholds | ±25 c (as `classify_accuracy`), runs of ≥ 2 notes, at most 3, ranked by notes × \|avg cents\|. |
| W3-8 | Release | Waves 1–3 in the same server minors, after core 0.3.0 is on PyPI. |
