"""Practice timing at MIDI level (S5 in docs/research/ui-and-sound-testing-plan.md).

test_practice_midi.py already checks click and note positions in ticks (quarter notes). These tests
add what it does not: click onsets in **seconds** through the tempo map (so a tempo change or a
tempo factor really moves the clicks), clicks across a meter change, written repeats and volta
endings played out as the expected **printed bar numbers**, and part gains as per-part channel
volume with the note velocities left alone. No soundfont: MIDI events only.
"""

import pytest

from synth_mcp.engine import extract_midi

from .midi_helpers import cc7, click_events, fixture, melodic_tracks, read_midi, tempos

SATB = fixture("satb_4bars.musicxml")  # 4 bars of 4/4, whole notes, 90 BPM, 120 BPM from bar 3
SIX_EIGHT = fixture("six_eight.musicxml")  # 2 bars of 6/8, dotted quarters, 90 quarter-BPM


def _midi(text, tempo_factor=1.0, parts=None, **practice):
    return read_midi(extract_midi(text, parts, tempo_factor, **practice))


def _seconds(tick, tempo_map, tpq):
    """Seconds at ``tick`` under ``tempo_map`` [(tick, bpm), ...] (120 BPM before the first)."""
    seconds, at, bpm = 0.0, 0, 120.0
    for change_tick, change_bpm in tempo_map:
        if change_tick >= tick:
            break
        seconds += (change_tick - at) / tpq * 60.0 / bpm
        at, bpm = change_tick, change_bpm
    return seconds + (tick - at) / tpq * 60.0 / bpm


def _click_seconds(text, tempo_factor=1.0, **practice):
    tpq, tracks = _midi(text, tempo_factor, **practice)
    tempo_map = tempos(tracks)
    return [round(_seconds(e.tick, tempo_map, tpq), 6) for e in click_events(tracks)]


def _beats(start, bpm, count, beat_quarters=1.0):
    """``count`` beat onsets in seconds from ``start`` at ``bpm`` quarter notes per minute."""
    step = beat_quarters * 60.0 / bpm
    return [round(start + n * step, 6) for n in range(count)]


# ---------------------------------------------------------------------------
# Click onsets in seconds
# ---------------------------------------------------------------------------


class TestClickSeconds:
    def test_count_in_beats_are_two_thirds_of_a_second_at_90_bpm(self):
        assert _click_seconds(SATB, count_in_bars=1) == _beats(0.0, 90, 4)

    def test_metronome_follows_the_tempo_change_at_bar_3(self):
        # Bars 1-2 at 90 BPM (8 beats), bars 3-4 at 120 BPM (8 beats).
        expected = _beats(0.0, 90, 8) + _beats(8 * 60 / 90, 120, 8)
        assert _click_seconds(SATB, metronome=True) == expected

    def test_count_in_then_metronome_through_the_tempo_change(self):
        # The count-in bar plays at bar 1's tempo, then 2 bars at 90 and 2 at 120.
        expected = _beats(0.0, 90, 12) + _beats(12 * 60 / 90, 120, 8)
        assert _click_seconds(SATB, count_in_bars=1, metronome=True) == expected

    def test_tempo_factor_slows_both_sections(self):
        expected = _beats(0.0, 45, 4 + 8) + _beats(12 * 60 / 45, 60, 8)
        assert _click_seconds(SATB, tempo_factor=0.5, count_in_bars=1, metronome=True) == expected

    def test_count_in_of_a_measure_range_uses_its_own_tempo(self):
        # Bars 3-4 start at 120 BPM, so the count-in does too.
        assert _click_seconds(SATB, measures=[3, 4], count_in_bars=2) == _beats(0.0, 120, 8)

    def test_six_eight_clicks_once_a_second(self):
        # Dotted-quarter beats at 90 quarter-BPM: 1.5 x 2/3 s = 1 s.
        assert _click_seconds(SIX_EIGHT, count_in_bars=1, metronome=True) == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]

    def test_repeat_restarts_at_the_first_tempo(self):
        one_pass = _beats(0.0, 90, 8) + _beats(8 * 60 / 90, 120, 8)
        length = 8 * 60 / 90 + 8 * 60 / 120
        expected = one_pass + [length + s for s in one_pass]
        assert _click_seconds(SATB, repeat=2, metronome=True) == pytest.approx(expected, abs=1e-6)

    def test_first_note_comes_on_the_beat_after_the_count_in(self):
        tpq, tracks = _midi(SATB, count_in_bars=2)
        first = min(e.tick for t in melodic_tracks(tracks) for e in t.of("note_on"))
        assert _seconds(first, tempos(tracks), tpq) == pytest.approx(8 * 60 / 90)


METER_CHANGE = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Soprano</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>3</beats><beat-type>4</beat-type></time></attributes>
      <direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>60</per-minute></metronome></direction-type><sound tempo="60"/></direction>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>3</duration><type>half</type><dot/></note>
    </measure>
    <measure number="2">
      <attributes><time><beats>2</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>2</duration><type>half</type></note>
    </measure>
    <measure number="3">
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>2</duration><type>half</type></note>
    </measure>
  </part>
</score-partwise>"""


class TestMeterChange:
    def test_metronome_accents_each_new_bar_after_a_meter_change(self):
        tpq, tracks = _midi(METER_CHANGE, metronome=True)
        clicks = [(e.tick // tpq, e.value) for e in click_events(tracks)]
        # 3/4: accent + 2 beats; then two 2/4 bars: accent + 1 beat each.
        assert clicks == [(0, 76), (1, 77), (2, 77), (3, 76), (4, 77), (5, 76), (6, 77)]

    def test_metronome_seconds_at_60_bpm_are_whole_seconds(self):
        assert _click_seconds(METER_CHANGE, metronome=True) == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]

    def test_count_in_uses_the_first_bar_meter(self):
        tpq, tracks = _midi(METER_CHANGE, count_in_bars=1, metronome=True)
        clicks = [(e.tick // tpq, e.value) for e in click_events(tracks)]
        assert clicks[:3] == [(0, 76), (1, 77), (2, 77)]
        assert clicks[3] == (3, 76)  # bar 1 of the music


# ---------------------------------------------------------------------------
# Written repeats: the printed bar numbers as played
# ---------------------------------------------------------------------------

# Each printed bar holds one whole note with its own pitch, so the MIDI pitch names the bar.
_BAR_PITCH = {1: ("C", 60), 2: ("D", 62), 3: ("E", 64), 4: ("F", 65), 5: ("G", 67)}
_PITCH_BAR = {midi: bar for bar, (_, midi) in _BAR_PITCH.items()}
_FORWARD = '<barline location="left"><repeat direction="forward"/></barline>'
_BACKWARD = '<barline location="right"><bar-style>light-heavy</bar-style><repeat direction="backward"/></barline>'
_ENDING_1 = ('<barline location="left"><ending number="1" type="start"/></barline>',
             '<barline location="right"><ending number="1" type="stop"/><repeat direction="backward"/></barline>')
_ENDING_2 = ('<barline location="left"><ending number="2" type="start"/></barline>',
             '<barline location="right"><ending number="2" type="discontinue"/></barline>')


def _bar(number, left="", right=""):
    step, _ = _BAR_PITCH[number]
    attributes = (
        '<attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>'
        '<direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>60</per-minute>'
        '</metronome></direction-type><sound tempo="60"/></direction>'
    ) if number == 1 else ""
    note = f'<note><pitch><step>{step}</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>'
    return f'<measure number="{number}">{left}{attributes}{note}{right}</measure>'


def _score(*bars):
    return (
        '<?xml version="1.0" encoding="UTF-8"?><score-partwise version="3.1">'
        '<part-list><score-part id="P1"><part-name>Soprano</part-name></score-part></part-list>'
        f'<part id="P1">{"".join(bars)}</part></score-partwise>'
    )


# 1 |: 2 3 :| 4
SIMPLE_REPEAT = _score(_bar(1), _bar(2, left=_FORWARD), _bar(3, right=_BACKWARD), _bar(4))
# |: 1 2 [1. 3 :| [2. 4 ] 5
VOLTA = _score(_bar(1, left=_FORWARD), _bar(2), _bar(3, *_ENDING_1), _bar(4, *_ENDING_2), _bar(5))


def _played_bars(text, **practice):
    """The printed bar numbers in the order the MIDI plays them, with each bar's start in beats."""
    tpq, tracks = _midi(text, **practice)
    notes = sorted((e for t in melodic_tracks(tracks) for e in t.of("note_on")), key=lambda e: e.tick)
    return [(e.tick // tpq, _PITCH_BAR[e.value]) for e in notes]


def _bars(text, **practice):
    return [bar for _, bar in _played_bars(text, **practice)]


class TestWrittenRepeats:
    def test_simple_repeat(self):
        assert _bars(SIMPLE_REPEAT) == [1, 2, 3, 2, 3, 4]

    def test_simple_repeat_bars_are_back_to_back(self):
        assert [beat for beat, _ in _played_bars(SIMPLE_REPEAT)] == [0, 4, 8, 12, 16, 20]

    def test_volta_endings(self):
        assert _bars(VOLTA) == [1, 2, 3, 1, 2, 4, 5]

    @pytest.mark.parametrize("practice", [{"metronome": True}, {"count_in_bars": 1}])
    def test_clicks_do_not_change_the_bar_order(self, practice):
        assert _bars(VOLTA, **practice) == [1, 2, 3, 1, 2, 4, 5]

    def test_metronome_clicks_every_played_bar(self):
        tpq, tracks = _midi(VOLTA, metronome=True)
        accents = [e.tick // tpq for e in click_events(tracks) if e.value == 76]
        assert accents == [0, 4, 8, 12, 16, 20, 24]

    def test_repeat_twice_plays_the_simple_repeat_twice(self):
        assert _bars(SIMPLE_REPEAT, repeat=2) == [1, 2, 3, 2, 3, 4] * 2

    @pytest.mark.parametrize("times", [2, 3])
    def test_repeat_plays_the_volta_endings_on_every_pass(self, times):
        assert _bars(VOLTA, repeat=times) == [1, 2, 3, 1, 2, 4, 5] * times

    def test_repeat_with_metronome_plays_the_volta_endings_on_every_pass(self):
        assert _bars(VOLTA, repeat=2, metronome=True) == [1, 2, 3, 1, 2, 4, 5] * 2

    def test_repeat_passes_are_back_to_back(self):
        starts = [beat for beat, _ in _played_bars(VOLTA, repeat=2)]
        assert starts == list(range(0, 14 * 4, 4))

    def test_measure_range_inside_the_repeat(self):
        assert _bars(SIMPLE_REPEAT, measures=[2, 3]) == [2, 3, 2, 3]

    def test_measure_range_through_the_repeat(self):
        assert _bars(SIMPLE_REPEAT, measures=[2, 4], metronome=True) == [2, 3, 2, 3, 4]


# ---------------------------------------------------------------------------
# Part gains: channel volume per part, note velocities untouched
# ---------------------------------------------------------------------------


def _velocities(tracks):
    return [[e.velocity for e in t.of("note_on")] for t in melodic_tracks(tracks)]


class TestGainsPerPart:
    def test_each_part_gets_its_own_gain_as_cc7(self):
        _, tracks = _midi(SATB, part_gains={"S": 0.25, "A": 0.75, "T": 1.25, "B": 1.75})
        assert [cc7(t) for t in melodic_tracks(tracks)] == [[16], [48], [79], [111]]

    def test_cc7_is_on_the_channel_the_part_plays_on(self):
        _, tracks = _midi(SATB, preset="learning", focus_part="Tenor")
        for track in melodic_tracks(tracks):
            (event,) = [e for e in track.of("cc") if e.value[0] == 7]
            assert {e.channel for e in track.of("note_on")} == {event.channel}

    @pytest.mark.parametrize("practice", [
        {"part_gains": {"Alto": 0.0}},
        {"preset": "learning", "focus_part": "Alto"},
        {"preset": "karaoke", "focus_part": "Alto"},
    ])
    def test_gains_leave_note_velocities_alone(self, practice):
        _, plain = _midi(SATB)
        _, gained = _midi(SATB, **practice)
        assert _velocities(gained) == _velocities(plain)

    def test_one_cc7_per_part_even_when_repeated(self):
        _, tracks = _midi(SATB, preset="learning", focus_part="S", repeat=3)
        assert [cc7(t) for t in melodic_tracks(tracks)] == [[95], [32], [32], [32]]

    def test_click_track_has_no_channel_volume(self):
        _, tracks = _midi(SATB, preset="karaoke", focus_part="S", count_in_bars=1, metronome=True)
        (click_track,) = [t for t in tracks if 10 in t.channels]
        assert cc7(click_track) == []
