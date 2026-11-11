# pitch-mcp — Functional Gaps TODO

Found during a full six-server assessment pass (2026-08-16), reading `docs/requirements.md` and
`docs/architecture.md` against actual source. The test suite (100/100 passing) did not catch any
of these — see notes on each item for why. See memory `pitch-mcp-position-tracking-gap` for the
fuller narrative.

**Update (2026-08-16): all items below implemented.** See `docs/HANDOVER.md` Known Gotchas and
`docs/architecture.md` for the resulting design.

---

## Critical — "position in score" is not actually audio-driven

The server's stated goal is mic audio + score → position + accuracy, but position tracking did
not previously derive from the singer's actual performance in either phase:

- [x] **Phase A (`src/pitch_mcp/aligner.py`) doesn't do DTW.** Docstring and `docs/requirements.md`
      both claim DTW alignment via `dtaidistance`, but `dtaidistance` isn't in `pyproject.toml` and
      isn't referenced anywhere in source. The real implementation is a fixed time-window lookup:
      it checks which detected-pitch frames fall inside a note's *expected* start/end time (derived
      from the score's own tempo, ±10% window) and copies position straight from the reference
      sequence. This silently assumes the singer never drifts from nominal tempo — a real tempo
      deviation (rubato, hesitation) will misattribute pitch frames to the wrong note.
      **Fixed:** `align()` now uses `dtaidistance.dtw.warping_path` over the pitch sequences
      (pitch-optimal monotonic alignment), gated by a per-note temporal-plausibility check to keep
      "singer never attempted this note" → `no_signal` (DTW alone can't represent that — see
      `docs/HANDOVER.md` gotcha). Regression tests:
      `tests/test_aligner.py::TestAlign::test_tempo_drift_does_not_misattribute_frames` and
      `test_note_singer_never_attempted_is_no_signal_among_others`.
- [x] **Phase B (`src/pitch_mcp/engine.py::_worker_loop`) position is a wall-clock pointer.**
      `note_idx` only advances based on elapsed time since `start()` — detected pitch is never used
      to determine where the singer actually is. A pause, mistake, or tempo drift desyncs position
      permanently with no recovery. This is Goal 6 ("identify position from hummed/sung melody")
      and it is not implemented as described.
      **Fixed:** extracted `ScoreSession._process_pitch_frame` / `_find_best_note_index` — position
      now picks the note whose expected pitch best matches the detected frequency within a forward
      lookahead, falling back to the timeline only when nothing matches well. See
      `tests/test_engine.py::TestProcessPitchFrame`.
- [x] **`tempo_bpm` override is a silent no-op.** Threaded through `start_monitoring` →
      `ScoreSession.start()` (per IR-4) but never actually applied anywhere in the tracking logic.
      **Fixed:** `start()` stores it; `_process_pitch_frame` scales elapsed wall-clock time into
      score-time by `tempo_bpm / nominal_bpm` (nominal tempo read via
      `utils.extract_nominal_tempo_bpm`) before the lookahead runs. See
      `test_tempo_bpm_override_shifts_score_time`.

## Confirmed bugs

- [x] **`ScoreSession._history` is never populated.** Initialized in `engine.py` but nothing in
      `_worker_loop` appends to it, so `stop_monitoring`'s summary (FR-5) always returns
      zeros/`None` regardless of what was actually sung. Invisible to CI because
      `tests/test_engine.py::test_stop_returns_summary` only checks key *presence*, not values.
      **Fixed:** `_process_pitch_frame` appends to `_history` on each valid frame. See
      `test_valid_frame_populates_history`.
- [x] **`server.py::_active_backend()` defaults to `"aubio"`.** `aubio` is explicitly *not* a
      project dependency (see `docs/HANDOVER.md` gotchas — no Python 3.13 wheel, replaced by
      `librosa`). `_active_backend()` should default to `"librosa"` per IR-8, matching the logic
      that already exists correctly in `pitch_detector.get_backend()`. As-is, `list_capabilities`
      reports the wrong backend name and version (`"unavailable"`) by default.
      **Fixed:** default changed to `"librosa"`; `_backend_version()` also gained a `"librosa"`
      case (it previously only knew `"aubio"`/`"crepe"`, so even a correct default would have
      reported `"unavailable"`). See `tests/test_server.py::TestActiveBackend`.

## Testing gaps vs. requirements.md (TR-2–TR-4)

- [x] **No tests are marked `@pytest.mark.integration` or `@pytest.mark.manual`** despite
      `docs/requirements.md` requiring them. All 100 passing tests are pure unit tests with mocks —
      the offline pipeline has never been run end-to-end on real audio in CI, and Phase B has never
      been manually verified against a real mic despite `docs/HANDOVER.md`'s Definition of Done
      requiring it.
      **Fixed:** added `tests/test_integration.py` (`@pytest.mark.integration`, runs
      `analyze_recording` against the committed fixture pair) and `tests/test_manual.py`
      (`@pytest.mark.manual`, full real-mic session lifecycle). Added `tests/conftest.py` — the
      `integration`/`manual` markers were already declared in `pyproject.toml` but nothing actually
      skipped them by default, so marking tests alone wouldn't have kept `pytest tests/` fast; the
      conftest pattern was copied from `omr-mcp/tests/conftest.py`.
- [x] **`tests/fixtures/` has no committed WAV/MusicXML fixture** — only a placeholder README.
      `docs/HANDOVER.md` step 4 ("Record a short vocal fixture") was never completed. Needed before
      the integration tests above can be written.
      **Partially fixed:** committed `reference.musicxml` (14s, 5-measure Soprano phrase) and a
      matching `soprano_phrase.wav` — but the WAV is a synthesized sine-tone proxy, not a real human
      recording (can't record a human voice in this environment). Recording a real take to replace
      it — same filenames — is still open; see `docs/HANDOVER.md` step 4.

---

## Defects found by the simulated singer (2026-11-11, P5 / S4)

`tests/test_simulated_singer.py` renders `reference.musicxml` with one fault at a time (helper:
`tests/simulated_singer.py`). `docs/HANDOVER.md` does not exist in this checkout, so the findings are
recorded here. Each is an `xfail(strict=True)` test written to the intended behaviour; remove the
marker when fixed.

- [ ] **Octave slips are not graded.** An octave-up note is detected at half its pitch (pYIN) and
      graded `on_pitch` at 0 cents; for both directions the DTW aligner hands the slipped note a
      neighbour's frames (`sung_hz` = a neighbouring note). Expected: `sharp` / `flat` near +-1200.
- [ ] **A note that repeats the previous pitch can get one frame.** On the final C4 (after another
      C4) DTW assigned a single frame, so one vibrato extreme (+50 cents) was graded `sharp`. The same
      vibrato on a note between different pitches grades `on_pitch`.
- Deliberate tolerances, asserted as documented: a note 150 ms late stays `on_pitch` (grading is by
  pitch; the aligner has no timing metric); +25 cents is on the `|cents| <= 25` `on_pitch` edge, so
  that test asserts the deviation, not the label; a 150 ms breath gap or 20 dB SNR noise does not
  change the grade.
