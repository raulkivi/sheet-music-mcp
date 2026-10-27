"""Practice-track MIDI (UX Wave 3: C8 gains, C9 measures and repeat, C10 count-in and metronome,
C11 timbre; docs/conventions.md, Practice Audio and Measure Ranges).

Everything is checked at MIDI level with music21.midi.MidiFile: no FluidSynth needed.
"""

import pytest
from sheet_music_mcp_core.errors import ProcessingError
from sheet_music_mcp_core.parts import PartInfo

from synth_mcp.engine import extract_midi
from synth_mcp.practice import cc7_value, resolve_gains

from .midi_helpers import (
    cc7,
    click_events,
    first_melodic_note_tick,
    fixture,
    last_melodic_note_off_tick,
    melodic_tracks,
    read_midi,
    tempos,
)

SATB = fixture("satb_4bars.musicxml")  # 4 bars of 4/4, whole notes, 90 BPM, 120 BPM from bar 3
SIX_EIGHT = fixture("six_eight.musicxml")  # 2 bars of 6/8, dotted quarters, 90 quarter-BPM
PICKUP = fixture("pickup_sound_tempo.musicxml")  # 3/4, 1-beat pickup, only <sound tempo="84"/>

SATB_INFOS = [PartInfo("P1", "Soprano", "S."), PartInfo("P2", "Alto", "A."),
              PartInfo("P3", "Tenor", "T."), PartInfo("P4", "Bass", "B.")]


def _midi(text=SATB, parts=None, tempo_factor=1.0, **practice):
    return read_midi(extract_midi(text, parts, tempo_factor, **practice))


def _track_by_name(tracks, name):
    return next(t for t in melodic_tracks(tracks) if t.name == name)


def _error(**kwargs):
    with pytest.raises(ProcessingError) as exc:
        extract_midi(kwargs.pop("text", SATB), kwargs.pop("parts", None), 1.0, **kwargs)
    return exc.value


# ---------------------------------------------------------------------------
# DoD-1: explicit defaults give today's MIDI, byte for byte
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [SATB, SIX_EIGHT, PICKUP])
def test_explicit_defaults_are_byte_identical(text):
    plain = extract_midi(text, None, 1.0)
    explicit = extract_midi(
        text, None, 1.0, measures=None, repeat=1, count_in_bars=0, metronome=False,
        timbre="score", part_gains=None, preset=None, focus_part=None,
    )
    assert explicit == plain


def test_defaults_have_no_cc7_and_no_clicks():
    _, tracks = _midi()
    assert all(cc7(t) == [] for t in tracks)
    assert click_events(tracks) == []


# ---------------------------------------------------------------------------
# C8: part gains and presets
# ---------------------------------------------------------------------------


class TestCc7Value:
    @pytest.mark.parametrize("gain, value", [(0, 0), (0.0, 0), (0.5, 32), (1.0, 64), (1.5, 95), (2.0, 127)])
    def test_mapping(self, gain, value):
        assert cc7_value(gain) == value


class TestResolveGains:
    def test_nothing_requested_gives_none(self):
        assert resolve_gains(SATB_INFOS, None, None, None) is None

    def test_learning(self):
        assert resolve_gains(SATB_INFOS, None, "learning", "Alto") == [0.5, 1.5, 0.5, 0.5]

    def test_karaoke(self):
        assert resolve_gains(SATB_INFOS, None, "karaoke", "T") == [1.0, 1.0, 0.0, 1.0]

    def test_equal_needs_no_focus(self):
        assert resolve_gains(SATB_INFOS, None, "equal", None) == [1.0, 1.0, 1.0, 1.0]

    def test_part_gains_alone_default_others_to_one(self):
        assert resolve_gains(SATB_INFOS, {"P2": 0}, None, None) == [1.0, 0.0, 1.0, 1.0]

    def test_part_gains_override_the_preset(self):
        gains = resolve_gains(SATB_INFOS, {"Soprano": 2.0}, "learning", "Alto")
        assert gains == [2.0, 1.5, 0.5, 0.5]

    @pytest.mark.parametrize("preset", ["learning", "karaoke"])
    def test_focus_preset_without_focus_part(self, preset):
        with pytest.raises(ProcessingError) as exc:
            resolve_gains(SATB_INFOS, None, preset, None)
        assert exc.value.error_code == "INVALID_PARAMETER"
        assert exc.value.choices == ["Soprano (P1)", "Alto (P2)", "Tenor (P3)", "Bass (P4)"]

    def test_unknown_part_gains_key(self):
        with pytest.raises(ProcessingError) as exc:
            resolve_gains(SATB_INFOS, {"Viola": 1.0}, None, None)
        assert exc.value.error_code == "INVALID_PARAMETER"
        assert "Alto (P2)" in exc.value.choices

    def test_unknown_focus_part(self):
        with pytest.raises(ProcessingError) as exc:
            resolve_gains(SATB_INFOS, None, "learning", "Viola")
        assert exc.value.error_code == "INVALID_PARAMETER"
        assert exc.value.choices

    def test_focus_part_must_be_a_selected_part(self):
        with pytest.raises(ProcessingError) as exc:
            resolve_gains(SATB_INFOS[:1], None, "learning", "Alto")
        assert exc.value.choices == ["Soprano (P1)"]

    @pytest.mark.parametrize("gain", [-0.1, 2.01, True, "1", None])
    def test_gain_outside_range_or_not_a_number(self, gain):
        with pytest.raises(ProcessingError) as exc:
            resolve_gains(SATB_INFOS, {"P1": gain}, None, None)
        assert exc.value.error_code == "INVALID_PARAMETER"

    def test_unknown_preset(self):
        with pytest.raises(ProcessingError) as exc:
            resolve_gains(SATB_INFOS, None, "loud", None)
        assert exc.value.error_code == "INVALID_PARAMETER"

    def test_part_gains_must_be_an_object(self):
        with pytest.raises(ProcessingError) as exc:
            resolve_gains(SATB_INFOS, [("P1", 1.0)], None, None)
        assert exc.value.error_code == "INVALID_PARAMETER"


class TestGainsInMidi:
    def test_muted_part_has_cc7_zero_on_its_channel(self):
        # Proposal §7 acceptance test.
        _, tracks = _midi(part_gains={"P2": 0})
        alto = _track_by_name(tracks, "Alto")
        assert cc7(alto) == [0]
        assert all(cc7(_track_by_name(tracks, n)) == [64] for n in ("Soprano", "Tenor", "Bass"))

    def test_learning_focus_is_loudest(self):
        # Proposal §7 acceptance test.
        _, tracks = _midi(preset="learning", focus_part="Alto")
        alto = cc7(_track_by_name(tracks, "Alto"))[0]
        others = [cc7(_track_by_name(tracks, n))[0] for n in ("Soprano", "Tenor", "Bass")]
        assert alto == 95
        assert all(alto > other for other in others)

    def test_karaoke(self):
        _, tracks = _midi(preset="karaoke", focus_part="Alto")
        assert [cc7(t) for t in melodic_tracks(tracks)] == [[64], [0], [64], [64]]

    def test_part_gains_override_preset(self):
        _, tracks = _midi(preset="learning", focus_part="A", part_gains={"S": 2.0})
        assert [cc7(t) for t in melodic_tracks(tracks)] == [[127], [95], [32], [32]]

    def test_each_part_gets_its_own_channel_never_ten(self):
        # music21 puts parts with the same instrument on one channel; CC7 needs one per part.
        _, tracks = _midi(preset="equal")
        channels = [t.channels for t in melodic_tracks(tracks)]
        assert all(len(c) == 1 for c in channels)
        flat = [next(iter(c)) for c in channels]
        assert len(set(flat)) == 4
        assert 10 not in flat

    def test_cc7_is_at_tick_zero_before_any_note(self):
        _, tracks = _midi(preset="equal", count_in_bars=1)
        for track in melodic_tracks(tracks):
            (event,) = [e for e in track.of("cc") if e.value[0] == 7]
            assert event.tick == 0
            assert track.events.index(event) < track.events.index(track.of("note_on")[0])

    def test_gains_follow_the_selected_parts(self):
        _, tracks = _midi(parts=["S", "A"], preset="learning", focus_part="S")
        assert [t.name for t in melodic_tracks(tracks)] == ["Soprano", "Alto"]
        assert [cc7(t) for t in melodic_tracks(tracks)] == [[95], [32]]

    def test_learning_without_focus_is_invalid_parameter(self):
        error = _error(preset="learning")
        assert error.error_code == "INVALID_PARAMETER"
        assert error.choices

    def test_unknown_part_gains_key_is_invalid_parameter(self):
        error = _error(part_gains={"Viola": 0.5})
        assert error.error_code == "INVALID_PARAMETER"
        assert error.choices

    def test_focus_part_outside_selection(self):
        error = _error(parts=["Soprano"], preset="karaoke", focus_part="Alto")
        assert error.error_code == "INVALID_PARAMETER"
        assert error.choices == ["Soprano (P1)"]


# ---------------------------------------------------------------------------
# C9: measures and repeat
# ---------------------------------------------------------------------------


def _note_pitches(tracks, name):
    return [e.value for e in _track_by_name(tracks, name).of("note_on")]


class TestMeasures:
    def test_two_bars_long(self):
        tpq, tracks = _midi(measures=[3, 4])
        assert first_melodic_note_tick(tracks) == 0
        assert last_melodic_note_off_tick(tracks) == 2 * 4 * tpq
        assert _note_pitches(tracks, "Soprano") == [78, 79]  # F#5, G5

    def test_tempo_in_force_at_start_is_kept(self):
        _, tracks = _midi(measures=[3, 4])
        assert [bpm for _, bpm in tempos(tracks)] == [120.0]

    def test_tuple_accepted(self):
        _, tracks = _midi(measures=(2, 2))
        assert _note_pitches(tracks, "Alto") == [71]  # B4

    def test_reversed_range_names_the_score_range(self):
        error = _error(measures=[3, 2])
        assert error.error_code == "INVALID_PARAMETER"
        assert error.hint == "This score has measures 1–4."

    def test_out_of_range_has_hint(self):
        error = _error(measures=[5, 9])
        assert error.error_code == "INVALID_PARAMETER"
        assert error.hint == "This score has measures 1–4."

    @pytest.mark.parametrize("bad", [[4, 3], [3], [True, 4], ["3", "4"], "3-4"])
    def test_malformed(self, bad):
        assert _error(measures=bad).error_code == "INVALID_PARAMETER"


class TestTempoFactor:
    """Tempo given only as <sound tempo> (music21: number None, numberSounding set) must scale."""

    def test_sound_tempo_only_is_scaled(self):
        _, tracks = _midi(PICKUP, tempo_factor=0.5)
        assert [bpm for _, bpm in tempos(tracks)] == [42.0]

    def test_sound_tempo_only_unscaled(self):
        _, tracks = _midi(PICKUP)
        assert [bpm for _, bpm in tempos(tracks)] == [84.0]

    def test_measures_carry_the_scaled_tempo(self):
        # Bar 2 gets bar 1's tempo as a bare <sound tempo> from select_measures.
        _, tracks = _midi(measures=[2, 2], tempo_factor=0.5)
        assert [bpm for _, bpm in tempos(tracks)] == [45.0]

    def test_measures_carry_scaled_tempo_with_metronome_mark(self):
        _, tracks = _midi(measures=[3, 4], tempo_factor=0.5)
        assert [bpm for _, bpm in tempos(tracks)] == [60.0]


class TestRepeat:
    def test_three_times_as_long(self):
        _, once = _midi()
        _, thrice = _midi(repeat=3)
        assert last_melodic_note_off_tick(thrice) == 3 * last_melodic_note_off_tick(once)
        assert _note_pitches(thrice, "Bass") == _note_pitches(once, "Bass") * 3

    def test_repeat_of_a_measure_range(self):
        tpq, tracks = _midi(measures=[3, 4], repeat=2)
        assert last_melodic_note_off_tick(tracks) == 4 * 4 * tpq
        assert _note_pitches(tracks, "Soprano") == [78, 79, 78, 79]

    def test_tempo_changes_repeat_too(self):
        tpq, tracks = _midi(repeat=2)
        bar = 4 * tpq
        assert tempos(tracks) == [(0, 90.0), (2 * bar, 120.0), (4 * bar, 90.0), (6 * bar, 120.0)]

    def test_ties_are_not_carried_across_the_join(self):
        # Bar 2 of TIED holds a note tied in from bar 1 and out to bar 3: each repeat restarts it.
        tpq, tracks = _midi(TIED, measures=[2, 2], repeat=2)
        notes = _track_by_name(tracks, "Soprano").of("note_on")
        assert [(e.tick, e.value) for e in notes] == [(0, 60), (4 * tpq, 60)]

    @pytest.mark.parametrize("bad", [0, 21, 1.5, True, "2"])
    def test_out_of_range(self, bad):
        assert _error(repeat=bad).error_code == "INVALID_PARAMETER"


TIED = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Soprano</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><tie type="start"/><type>whole</type></note>
    </measure>
    <measure number="2">
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><tie type="stop"/><tie type="start"/><type>whole</type></note>
    </measure>
    <measure number="3">
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><tie type="stop"/><type>whole</type></note>
    </measure>
  </part>
</score-partwise>"""


# ---------------------------------------------------------------------------
# C10: count-in and metronome
# ---------------------------------------------------------------------------


def _clicks(tracks, tpq):
    return [(e.tick / tpq, e.value) for e in click_events(tracks)]


class TestCountIn:
    def test_one_bar_in_four_four(self):
        tpq, tracks = _midi(count_in_bars=1)
        assert _clicks(tracks, tpq) == [(0, 76), (1, 77), (2, 77), (3, 77)]
        assert first_melodic_note_tick(tracks) == 4 * tpq

    def test_music_moves_later_by_the_count_in(self):
        tpq, plain = _midi()
        _, counted = _midi(count_in_bars=2)
        assert first_melodic_note_tick(counted) == first_melodic_note_tick(plain) + 8 * tpq
        assert last_melodic_note_off_tick(counted) == last_melodic_note_off_tick(plain) + 8 * tpq

    def test_count_in_plays_at_the_first_bar_tempo(self):
        tpq, tracks = _midi(count_in_bars=1)
        assert tempos(tracks)[0] == (0, 90.0)

    def test_count_in_uses_the_scaled_tempo(self):
        _, tracks = _midi(count_in_bars=1, tempo_factor=0.5)
        assert tempos(tracks)[0] == (0, 45.0)

    def test_count_in_uses_the_tempo_at_the_first_played_bar(self):
        _, tracks = _midi(measures=[3, 4], count_in_bars=1)
        assert tempos(tracks)[0] == (0, 120.0)

    def test_count_in_with_sound_tempo_only(self):
        _, tracks = _midi(PICKUP, count_in_bars=1, tempo_factor=0.5)
        assert tempos(tracks)[0] == (0, 42.0)

    def test_count_in_without_any_tempo_uses_default(self):
        _, tracks = _midi(TIED, count_in_bars=1)
        assert [bpm for _, bpm in tempos(tracks)] == [120.0]

    def test_six_eight_has_two_clicks_per_bar(self):
        tpq, tracks = _midi(SIX_EIGHT, count_in_bars=1)
        assert _clicks(tracks, tpq) == [(0, 76), (1.5, 77)]
        assert first_melodic_note_tick(tracks) == 3 * tpq

    def test_pickup_count_in_is_whole_bars(self):
        tpq, tracks = _midi(PICKUP, count_in_bars=1)
        assert _clicks(tracks, tpq) == [(0, 76), (1, 77), (2, 77)]
        assert first_melodic_note_tick(tracks) == 3 * tpq

    @pytest.mark.parametrize("bad", [-1, 5, 1.0, True])
    def test_out_of_range(self, bad):
        assert _error(count_in_bars=bad).error_code == "INVALID_PARAMETER"


class TestMetronome:
    def test_click_on_every_beat(self):
        tpq, tracks = _midi(metronome=True)
        clicks = _clicks(tracks, tpq)
        assert [tick for tick, _ in clicks] == list(range(16))
        assert [pitch for _, pitch in clicks] == [76, 77, 77, 77] * 4
        assert first_melodic_note_tick(tracks) == 0

    def test_count_in_and_metronome(self):
        tpq, tracks = _midi(count_in_bars=1, metronome=True)
        assert [tick for tick, _ in _clicks(tracks, tpq)] == list(range(20))

    def test_six_eight(self):
        tpq, tracks = _midi(SIX_EIGHT, metronome=True)
        assert _clicks(tracks, tpq) == [(0, 76), (1.5, 77), (3, 76), (4.5, 77)]

    def test_pickup_bar_clicks_its_last_beat(self):
        tpq, tracks = _midi(PICKUP, metronome=True)
        assert _clicks(tracks, tpq) == [(0, 77), (1, 76), (2, 77), (3, 77), (4, 76), (5, 77), (6, 77)]

    def test_metronome_follows_repeat(self):
        tpq, tracks = _midi(measures=[3, 4], repeat=2, metronome=True)
        assert [tick for tick, _ in _clicks(tracks, tpq)] == list(range(16))

    def test_click_track_is_channel_ten_with_standard_kit(self):
        _, tracks = _midi(count_in_bars=1, metronome=True)
        click_tracks = [t for t in tracks if 10 in t.channels]
        assert len(click_tracks) == 1
        assert click_tracks[0].channels == {10}
        assert [e.value for e in click_tracks[0].of("program")] in ([], [0])

    def test_no_melodic_track_on_channel_ten(self):
        _, tracks = _midi(count_in_bars=1, metronome=True, preset="equal")
        assert all(10 not in t.channels for t in melodic_tracks(tracks))
        assert [t.name for t in melodic_tracks(tracks)] == ["Soprano", "Alto", "Tenor", "Bass"]

    def test_gains_with_clicks_still_follow_parts(self):
        _, tracks = _midi(count_in_bars=1, part_gains={"Tenor": 0})
        assert [cc7(t) for t in melodic_tracks(tracks)] == [[64], [64], [0], [64]]


# ---------------------------------------------------------------------------
# C11: timbre
# ---------------------------------------------------------------------------


class TestTimbre:
    @pytest.mark.parametrize("timbre, program", [("piano", 0), ("choir", 52), ("organ", 19)])
    def test_one_program_change_per_melodic_channel(self, timbre, program):
        _, tracks = _midi(timbre=timbre)
        programs = {}
        for track in melodic_tracks(tracks):
            for event in track.of("program"):
                programs.setdefault(event.channel, []).append((event.tick, event.value))
        assert programs
        assert all(events == [(0, program)] for events in programs.values())

    def test_score_keeps_todays_programs(self):
        assert extract_midi(SATB, None, 1.0, timbre="score") == extract_midi(SATB, None, 1.0)

    def test_timbre_with_gains_and_count_in(self):
        _, tracks = _midi(timbre="organ", preset="equal", count_in_bars=1)
        for track in melodic_tracks(tracks):
            assert [(e.tick, e.value) for e in track.of("program")] == [(0, 19)]

    def test_timbre_leaves_the_click_track_alone(self):
        _, tracks = _midi(timbre="organ", metronome=True)
        click_track = next(t for t in tracks if 10 in t.channels)
        assert all(e.value != 19 for e in click_track.of("program"))

    @pytest.mark.parametrize("bad", ["violin", "", "Organ", 19])
    def test_unknown_timbre(self, bad):
        assert _error(timbre=bad).error_code == "INVALID_PARAMETER"


# ---------------------------------------------------------------------------
# Channels: score percussion, many parts
# ---------------------------------------------------------------------------

WITH_DRUM = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Soprano</part-name></score-part>
    <score-part id="P2"><part-name>Drum</part-name>
      <score-instrument id="P2-I1"><instrument-name>Snare Drum</instrument-name></score-instrument>
      <midi-instrument id="P2-I1"><midi-channel>10</midi-channel><midi-unpitched>39</midi-unpitched></midi-instrument>
    </score-part>
  </part-list>
  <part id="P1"><measure number="1">
    <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
    <note><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration><type>whole</type></note>
  </measure></part>
  <part id="P2"><measure number="1">
    <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time>
      <clef><sign>percussion</sign></clef></attributes>
    <note><unpitched><display-step>C</display-step><display-octave>5</display-octave></unpitched>
      <duration>4</duration><instrument id="P2-I1"/><type>whole</type></note>
  </measure></part>
</score-partwise>"""


def _named(tracks, name):
    return next(t for t in tracks if t.name == name)


class TestChannels:
    def test_score_percussion_stays_on_ten_and_the_voice_moves_off_it(self):
        # music21 itself puts this Soprano on channel 10 (today's MIDI, left as is by default).
        _, tracks = _midi(WITH_DRUM, metronome=True)
        assert _named(tracks, "Soprano").channels == {1}
        assert _named(tracks, "Percussion").channels == {10}

    def test_score_percussion_with_gains(self):
        _, tracks = _midi(WITH_DRUM, part_gains={"Drum": 0.5})
        assert _named(tracks, "Soprano").channels == {1}
        assert cc7(_named(tracks, "Soprano")) == [64]
        assert _named(tracks, "Percussion").channels == {10}
        assert cc7(_named(tracks, "Percussion")) == [32]

    def test_gains_need_a_channel_per_part(self):
        many = _many_parts(16)
        assert len(melodic_tracks(_midi(many)[1])) == 16  # fine without gains
        error = _error(text=many, preset="equal")
        assert error.error_code == "INVALID_PARAMETER"
        assert "15" in str(error)

    def test_fifteen_parts_get_fifteen_channels(self):
        _, tracks = _midi(_many_parts(15), preset="equal")
        channels = [next(iter(t.channels)) for t in melodic_tracks(tracks)]
        assert sorted(channels) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16]


def _many_parts(count):
    part_list = "".join(f'<score-part id="P{i}"><part-name>Voice {i}</part-name></score-part>' for i in range(count))
    body = "".join(
        f'<part id="P{i}"><measure number="1"><attributes><divisions>1</divisions>'
        "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
        "<note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>"
        "</measure></part>"
        for i in range(count)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><score-partwise version="3.1">'
        f"<part-list>{part_list}</part-list>{body}</score-partwise>"
    )


def test_count_in_meter_is_the_first_bar_meter():
    tpq, tracks = _midi(SIX_EIGHT, count_in_bars=1)
    signatures = [(e.tick, e.value[:2]) for t in tracks for e in t.of("time_signature")]
    assert signatures[0] == (0, bytes([6, 3]))  # 6/8 from tick 0, not MIDI's default 4/4


def test_practice_and_clip_modules_do_not_import_mcp():
    import subprocess
    import sys

    code = (
        "import sys, synth_mcp.practice, synth_mcp.clip, synth_mcp.engine; "
        "print(any(m == 'mcp' or m.startswith('mcp.') for m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"
