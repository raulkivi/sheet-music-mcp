"""Content tests: what the synthesized audio contains (length, clipping, silence, part level).

Needs a real soundfont and libfluidsynth, so everything here is an integration test and skips
when ``SYNTH_SOUNDFONT_PATH`` is unset. Run with::

    SYNTH_SOUNDFONT_PATH=/usr/share/sounds/sf2/TimGM6mb.sf2 .venv/bin/pytest tests/test_audio_content.py -m integration

Tolerances, not byte equality: FluidSynth output drifts between versions. Tuned against real
renders with TimGM6mb.sf2 and libfluidsynth 2.3.4 (P6, 2026-11-11): every render runs 3.00-3.01 s
past the last MIDI note-off, and a render's start moves by up to about 3 ms between runs.
"""

import math
import os

import pytest

from synth_mcp.engine import extract_midi, synthesize_midi

from .audio_features import analyze_wav, onsets_near, read_wav
from .midi_helpers import (
    fixture,
    last_melodic_note_off_tick,
    melodic_tracks,
    read_midi,
    tempos,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("SYNTH_SOUNDFONT_PATH"),
        reason="SYNTH_SOUNDFONT_PATH not set - skipping audio content tests",
    ),
]

SATB = fixture("satb_4bars.musicxml")
RELEASE_TAIL_S = 3.5  # measured 3.00-3.01 s of release and reverb after the last note-off
LEVEL_TOLERANCE_DB = 1.5
ONSET_TOLERANCE_S = 0.02


def tick_seconds(tick: int, tpq: int, tracks) -> float:
    """Seconds from the start of the MIDI to ``tick``, following tempo changes."""
    changes = tempos(tracks) or [(0, 120.0)]
    if changes[0][0] != 0:
        changes.insert(0, (0, 120.0))
    seconds = 0.0
    for i, (at, bpm) in enumerate(changes):
        upto = min(tick, changes[i + 1][0]) if i + 1 < len(changes) else tick
        if upto > at:
            seconds += (upto - at) / tpq * 60.0 / bpm
    return seconds


def midi_seconds(midi_bytes: bytes) -> float:
    """Seconds from the start of the MIDI to the last melodic note-off."""
    tpq, tracks = read_midi(midi_bytes)
    return tick_seconds(last_melodic_note_off_tick(tracks), tpq, tracks)


def midi_onsets(midi_bytes: bytes) -> list[float]:
    """Seconds of each distinct melodic note-on time."""
    tpq, tracks = read_midi(midi_bytes)
    ticks = sorted({e.tick for t in melodic_tracks(tracks) for e in t.of("note_on")})
    return [tick_seconds(tick, tpq, tracks) for tick in ticks]


def render_wav(tmp_path, name: str, **kwargs):
    midi = extract_midi(SATB, kwargs.pop("parts", None), kwargs.pop("tempo", 1.0), **kwargs)
    wav = tmp_path / f"{name}.wav"
    synthesize_midi(midi, str(wav))
    return midi, wav


def render(tmp_path, name: str, **kwargs):
    midi, wav = render_wav(tmp_path, name, **kwargs)
    return midi, analyze_wav(wav)


def mean_rms(features) -> float:
    return sum(features.rms) / len(features.rms)


def db(ratio: float) -> float:
    return 20 * math.log10(ratio)


@pytest.mark.parametrize(
    "name, kwargs",
    [
        ("plain", {}),
        ("slow", {"tempo": 0.5}),
        ("repeat", {"repeat": 2}),
        ("count_in", {"count_in_bars": 1, "metronome": True}),
    ],
)
def test_duration_matches_the_midi(tmp_path, name, kwargs):
    midi, features = render(tmp_path, name, **kwargs)
    expected = midi_seconds(midi)
    assert expected <= features.duration_s <= expected + RELEASE_TAIL_S, (
        f"{features.duration_s:.2f}s audio vs {expected:.2f}s of MIDI"
    )


def test_all_parts_do_not_clip(tmp_path):
    _, features = render(tmp_path, "all")
    assert features.clipped_samples == 0
    assert features.peak < 0.999


def test_no_silence_while_the_parts_sound(tmp_path):
    midi, features = render(tmp_path, "all")
    sounding_until = midi_seconds(midi)
    inside = [(s, e) for s, e in features.silence_spans if s < sounding_until - 0.1]
    assert inside == [], f"silence while notes should sound: {inside}"
    assert features.silence_spans == [] or features.silence_spans[-1][1] == pytest.approx(
        features.duration_s
    ), "silence is only allowed as the trailing tail"


def test_part_gain_moves_only_that_part(tmp_path):
    _, full = render(tmp_path, "full")
    _, bass_off = render(tmp_path, "bass_off", part_gains={"P4": 0.0})
    _, upper_only = render(tmp_path, "upper_only", parts=["P1", "P2", "P3"])
    _, bass_only = render(tmp_path, "bass_only", parts=["P4"])
    _, bass_quiet = render(tmp_path, "bass_quiet", parts=["P4"], part_gains={"P4": 0.25})

    assert mean_rms(bass_off) < mean_rms(full), "silencing the bass lowers the mix"
    assert abs(db(mean_rms(bass_off) / mean_rms(upper_only))) < LEVEL_TOLERANCE_DB, (
        "the other parts keep their level when the bass is silenced"
    )
    assert mean_rms(bass_quiet) < mean_rms(bass_only), "a lower gain makes that part quieter"


@pytest.mark.parametrize(
    "name, kwargs",
    [
        ("plain", {}),  # 90 BPM, then 120 BPM from bar 3
        ("slow", {"tempo": 0.5}),
        ("count_in", {"count_in_bars": 1}),
    ],
)
def test_note_onsets_follow_the_midi(tmp_path, name, kwargs):
    midi, wav = render_wav(tmp_path, name, **kwargs)
    expected = midi_onsets(midi)
    samples, rate, _ = read_wav(wav)
    found = onsets_near(samples, rate, expected)
    late = [
        (round(e, 3), None if f is None else round(f - e, 3))
        for e, f in zip(expected, found)
        if f is None or abs(f - e) > ONSET_TOLERANCE_S
    ]
    assert late == [], f"onsets off the MIDI by more than 20 ms: (expected s, error s) {late}"
