"""
Practice-track features for synthesize (docs/conventions.md, Practice Audio; UX Wave 3 C8–C11).

No MCP SDK imports here. Each step is its own function so it can be tested alone; extract_midi
in engine.py runs them in order:

    validate_options()        → repeat, count_in_bars, metronome, timbre checked; timbre → program
    resolve_gains()           → one gain per selected part, or None (no CC7 at all)
    expand_repeats()          → written repeats played out, before bars are counted for clicks
    repeat_music()            → the selected bars appended repeat − 1 more times
    add_clicks()              → count-in bars before the music, metronome clicks through it
    tune_midi()               → after music21's export: channels, program changes, CC7
"""

import copy
from typing import Optional, Sequence

from sheet_music_mcp_core.errors import ProcessingError
from sheet_music_mcp_core.parts import PartInfo, resolve_part, resolve_parts

PRESETS = ("learning", "karaoke", "equal")
# (focus part gain, other parts' gain) per preset (decision W3-2).
_PRESET_GAINS = {"learning": (1.5, 0.5), "karaoke": (0.0, 1.0), "equal": (1.0, 1.0)}
_FOCUS_PRESETS = ("learning", "karaoke")
MAX_GAIN = 2.0

# GM program per timbre (0-indexed); "score" keeps music21's instruments.
TIMBRES = {"score": None, "piano": 0, "choir": 52, "organ": 19}

MAX_REPEAT = 20
MAX_COUNT_IN_BARS = 4

PERCUSSION_CHANNEL = 10  # 1-indexed, as music21.midi.MidiEvent.channel
ACCENT_CLICK = 76  # GM hi wood block, beat 1
BEAT_CLICK = 77  # GM low wood block, other beats
# Channels for melodic parts when each part needs its own (CC7 is per channel).
MELODIC_CHANNELS = tuple(c for c in range(1, 17) if c != PERCUSSION_CHANNEL)


def _invalid(message: str, *, hint: Optional[str] = None, choices: Optional[list[str]] = None):
    return ProcessingError(message, "INVALID_PARAMETER", hint=hint, choices=choices)


# ---------------------------------------------------------------------------
# Option checks (the input schema checks the same bounds; direct engine calls skip it)
# ---------------------------------------------------------------------------


def validate_options(repeat, count_in_bars, metronome, timbre) -> Optional[int]:
    """Check the plain practice options; return the GM program for ``timbre`` (None = score)."""
    _check_int(repeat, "repeat", 1, MAX_REPEAT)
    _check_int(count_in_bars, "count_in_bars", 0, MAX_COUNT_IN_BARS)
    if not isinstance(metronome, bool):
        raise _invalid("metronome must be true or false.")
    if not isinstance(timbre, str) or timbre not in TIMBRES:
        raise _invalid(f"timbre must be one of: {', '.join(TIMBRES)}.")
    return TIMBRES[timbre]


def _check_int(value, name: str, low: int, high: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise _invalid(f"{name} must be a whole number from {low} to {high}.")


# ---------------------------------------------------------------------------
# C8 — gains
# ---------------------------------------------------------------------------


def cc7_value(gain: float) -> int:
    """MIDI channel volume for a gain of 0.0–2.0: 0 → 0, 1.0 → 64, 2.0 → 127."""
    return round(127 * gain / 2)


def resolve_gains(
    parts: Sequence[PartInfo],
    part_gains: Optional[dict],
    preset: Optional[str],
    focus_part: Optional[str],
) -> Optional[list[float]]:
    """One gain per part in ``parts`` (the selected parts, in order), or None for no CC7.

    ``preset`` and ``focus_part`` give the base gains, ``part_gains`` entries (part ID, name or
    voice) override them per part, and parts without either get 1.0. Raises ProcessingError
    (INVALID_PARAMETER, with the part choices where a part is missing or unknown).
    """
    if preset is not None and preset not in _PRESET_GAINS:
        raise _invalid(f"preset must be one of: {', '.join(PRESETS)}.")
    if part_gains is not None and not isinstance(part_gains, dict):
        raise _invalid("part_gains must be an object: part (ID, name or voice) → gain 0.0–2.0.")
    if preset is None and focus_part is not None:
        raise _invalid(
            "focus_part needs a preset.",
            hint="Add preset 'learning' (focus part louder) or 'karaoke' (focus part muted).",
        )
    if part_gains is None and preset is None:
        return None

    gains = {part.id: 1.0 for part in parts}
    if preset is not None:
        focus_gain, other_gain = _PRESET_GAINS[preset]
        focus = _focus_id(parts, preset, focus_part)
        gains = {part.id: focus_gain if part.id == focus else other_gain for part in parts}
    for request, gain in (part_gains or {}).items():
        _check_gain(request, gain)
        for part_id in resolve_parts([request], parts):
            gains[part_id] = float(gain)
    return [gains[part.id] for part in parts]


def _focus_id(parts: Sequence[PartInfo], preset: str, focus_part: Optional[str]) -> Optional[str]:
    if focus_part is None:
        if preset in _FOCUS_PRESETS:
            raise _invalid(
                f"preset '{preset}' needs focus_part: the part to practise.",
                hint="Pass focus_part as one of the listed part names or IDs.",
                choices=[f"{p.name} ({p.id})" if p.name else p.id for p in parts],
            )
        return None
    return resolve_part(focus_part, parts)


def _check_gain(request, gain) -> None:
    if not isinstance(gain, (int, float)) or isinstance(gain, bool) or not 0.0 <= gain <= MAX_GAIN:
        raise _invalid(f"part_gains['{request}'] must be a number from 0.0 to {MAX_GAIN}.")


# ---------------------------------------------------------------------------
# Score transforms (music21 streams)
# ---------------------------------------------------------------------------


def expand_repeats(score):
    """The score with written repeats played out, as music21's MIDI export would do anyway.

    Done before bars are counted for clicks, so the click part lines up with the played music.
    """
    return score.expandRepeats()


def repeat_music(score, times: int) -> None:
    """Append every part's bars ``times - 1`` more times, in place.

    Each pass is whole bars; ties are cut at the joins so a pass never runs into the next.
    """
    if times == 1:
        return
    span = max(_part_end(part) for part in score.parts)
    for part in score.parts:
        bars = list(part.getElementsByClass("Measure"))
        if not bars:
            continue
        passes = [bars]
        for n in range(1, times):
            copies = []
            for bar in bars:
                bar_copy = copy.deepcopy(bar)
                part.insert(bar.offset + n * span, bar_copy)
                copies.append(bar_copy)
            passes.append(copies)
        for bars_of_pass in passes:
            _cut_edge_ties(bars_of_pass[0], bars_of_pass[-1])


def _part_end(part) -> float:
    bars = list(part.getElementsByClass("Measure"))
    return max((bar.offset + bar.duration.quarterLength for bar in bars), default=0.0)


def _cut_edge_ties(first_bar, last_bar) -> None:
    """Drop ties into the first bar's start and out of the last bar's end."""
    for element in first_bar.recurse().notes:
        if element.getOffsetInHierarchy(first_bar) == 0:
            _drop_tie_side(element, "stop", keep="start")
    end = last_bar.duration.quarterLength
    for element in last_bar.recurse().notes:
        if element.getOffsetInHierarchy(last_bar) + element.quarterLength >= end:
            _drop_tie_side(element, "start", keep="stop")


def _drop_tie_side(element, side: str, *, keep: str) -> None:
    """Remove one side of each tie on a note or chord member: ``side`` goes, ``continue``
    becomes ``keep``."""
    import music21.tie

    for note in element.notes if element.isChord else (element,):
        if note.tie is None:
            continue
        if note.tie.type == side:
            note.tie = None
        elif note.tie.type == "continue":
            note.tie = music21.tie.Tie(keep)


def scale_tempo(score, tempo_factor: float) -> None:
    """Multiply every MetronomeMark by ``tempo_factor``, in place.

    A mark read from a bare ``<sound tempo>`` (as select_measures carries the tempo into the cut
    score) has ``number`` None and ``numberSounding`` set; music21's MIDI export prefers
    ``numberSounding``, so both are scaled. With no mark at all, a scaled default of 120 BPM goes
    into the first bar.
    """
    import music21.tempo

    if tempo_factor == 1.0:
        return
    marks = list(score.recurse().getElementsByClass(music21.tempo.MetronomeMark))
    if marks:
        for mark in marks:
            if mark.number is not None:
                mark.number = mark.number * tempo_factor
            if mark.numberSounding is not None:
                mark.numberSounding = mark.numberSounding * tempo_factor
    else:
        bars = list(score.parts[0].getElementsByClass("Measure"))
        if bars:
            bars[0].insert(0, music21.tempo.MetronomeMark(number=120.0 * tempo_factor))


def add_clicks(score, count_in_bars: int, metronome: bool) -> bool:
    """Add a wood-block click part on MIDI channel 10, in place; return whether one was added.

    ``count_in_bars`` bars of clicks in the time signature and tempo in force at the first bar
    come first, and the music moves later by their length. With ``metronome``, every beat of the
    music clicks too. Beats are music21's (6/8 has two); beat 1 is GM 76, other beats GM 77.
    """
    import music21.instrument
    import music21.meter
    import music21.stream

    if not count_in_bars and not metronome:
        return False

    bars = list(score.parts[0].getElementsByClass("Measure"))
    meter = _time_signature(bars[0]) if bars else music21.meter.TimeSignature("4/4")
    bar_length = meter.barDuration.quarterLength
    start_tempo = _start_tempo(score)

    shift = count_in_bars * bar_length
    if shift:
        for part in score.parts:
            part.shiftElements(shift)
        # The count-in's meter and tempo go at offset 0 of the first part, not in the click
        # part: music21's conductor track keeps only marks met in ascending offset order, and
        # the first part is read first.
        score.parts[0].insert(0, copy.deepcopy(meter))
        if start_tempo is not None:
            score.parts[0].insert(0, copy.deepcopy(start_tempo))

    click = music21.stream.Part()
    click.partName = "Click"
    click.insert(0, music21.instrument.Woodblock())
    for n in range(count_in_bars):
        click.insert(n * bar_length, _click_bar(meter, bar_length, 0.0))
    if metronome:
        for bar in bars:
            meter = _time_signature(bar, meter)
            click.insert(bar.offset, _click_bar(meter, bar.duration.quarterLength, bar.paddingLeft))

    # Appended last, so it becomes the last MIDI track (music21 exports parts in score order).
    score.append(click)
    return True


def _time_signature(bar, current=None):
    """The bar's own time signature, else ``current``, else the one in force (default 4/4)."""
    import music21.meter

    if bar.timeSignature is not None:
        return bar.timeSignature
    if current is not None:
        return current
    return bar.getContextByClass(music21.meter.TimeSignature) or music21.meter.TimeSignature("4/4")


def _start_tempo(score):
    """The MetronomeMark at the very start of the music, or None (MIDI's 120 BPM applies)."""
    import music21.tempo

    for part in score.parts:
        for mark in part.recurse().getElementsByClass(music21.tempo.MetronomeMark):
            if mark.getOffsetInHierarchy(part) == 0:
                return mark
    return None


def _click_bar(meter, length: float, padding: float):
    """One bar of clicks: a beat at each of the meter's beats that falls inside the bar.

    ``padding`` is the part of the bar missing at its start (a pickup), so its beats line up.
    """
    import music21.note
    import music21.stream

    bar = music21.stream.Measure()
    beat = meter.beatDuration.quarterLength
    for index in range(meter.beatCount):
        at = index * beat - padding
        if 0 <= at < length:
            click = music21.note.Note(ACCENT_CLICK if index == 0 else BEAT_CLICK)
            click.quarterLength = min(beat, length - at)
            bar.insert(at, click)
    return bar


def is_percussion(part) -> bool:
    """Whether a score part is unpitched percussion (music21 puts it on channel 10 itself)."""
    import music21.instrument

    return isinstance(part.getInstrument(returnDefault=False), music21.instrument.UnpitchedPercussion)


# ---------------------------------------------------------------------------
# MIDI post-processing (music21.midi.MidiFile from streamToMidiFile)
# ---------------------------------------------------------------------------


def tune_midi(
    midi_file,
    *,
    percussion: Sequence[bool],
    gains: Optional[Sequence[float]],
    program: Optional[int],
    clicks: bool,
) -> None:
    """Channels, program changes and CC7 for practice tracks, in place.

    Track 0 is music21's conductor track, then one track per selected part (``percussion`` says
    which are score percussion), then the click track when ``clicks``. With ``gains``, every
    melodic part gets its own channel (music21 shares one between parts with the same
    instrument) and one CC7 at tick 0. ``program`` replaces the melodic program changes with one
    at tick 0 per channel. The click track stays on channel 10 with the standard kit; no melodic
    track uses channel 10.
    """
    part_tracks = midi_file.tracks[1:1 + len(percussion)]
    melodic = [t for t, perc in zip(part_tracks, percussion) if not perc]

    if clicks:
        click = midi_file.tracks[1 + len(percussion)]
        _set_channel(click, PERCUSSION_CHANNEL)
        _set_programs(click, [PERCUSSION_CHANNEL], 0)

    if gains is not None:
        if len(melodic) > len(MELODIC_CHANNELS):
            raise _invalid(
                f"part_gains and preset work with up to {len(MELODIC_CHANNELS)} pitched parts; "
                f"{len(melodic)} are selected.",
                hint="Select fewer parts with 'parts'.",
            )
        for track, channel in zip(melodic, MELODIC_CHANNELS):
            _set_channel(track, channel)
    else:
        _move_off_percussion_channel(melodic)

    if program is not None:
        seen: set[int] = set()
        for track in melodic:
            channels = sorted(_channels(track) - seen)
            _set_programs(track, channels, program)
            seen.update(channels)

    if gains is not None:
        for track, gain in zip(part_tracks, gains):
            _insert_at_start(track, [_cc7_event(track, channel, gain) for channel in sorted(_channels(track))])


def _move_off_percussion_channel(melodic) -> None:
    """Melodic tracks music21 put on channel 10 move to the first channel no melodic track uses."""
    used = set().union(*(_channels(t) for t in melodic)) if melodic else set()
    free = [c for c in MELODIC_CHANNELS if c not in used] or [MELODIC_CHANNELS[0]]
    for track in melodic:
        if PERCUSSION_CHANNEL in _channels(track):
            _set_channel(track, free[0], only=PERCUSSION_CHANNEL)


def _is_channel_event(event) -> bool:
    import music21.midi

    return not event.isDeltaTime() and isinstance(
        event.type, (music21.midi.ChannelVoiceMessages, music21.midi.ChannelModeMessages)
    )


def _channels(track) -> set[int]:
    return {e.channel for e in track.events if _is_channel_event(e)}


def _set_channel(track, channel: int, *, only: Optional[int] = None) -> None:
    for event in track.events:
        if _is_channel_event(event) and (only is None or event.channel == only):
            event.channel = channel


def _set_programs(track, channels: Sequence[int], program: int) -> None:
    """Remove the track's program changes and put one per channel in ``channels`` at tick 0."""
    import music21.midi

    _remove(track, lambda e: e.type == music21.midi.ChannelVoiceMessages.PROGRAM_CHANGE)
    events = []
    for channel in channels:
        event = music21.midi.MidiEvent(track, type=music21.midi.ChannelVoiceMessages.PROGRAM_CHANGE, channel=channel)
        event.data = program
        events.append(event)
    _insert_at_start(track, events)


def _cc7_event(track, channel: int, gain: float):
    import music21.midi

    event = music21.midi.MidiEvent(track, type=music21.midi.ChannelVoiceMessages.CONTROLLER_CHANGE, channel=channel)
    event.parameter1 = 7
    event.parameter2 = cc7_value(gain)
    return event


def _timed(track) -> list:
    """The track's events (no delta times) with absolute ticks."""
    tick, timed = 0, []
    for event in track.events:
        if event.isDeltaTime():
            tick += event.time
        else:
            timed.append((tick, event))
    return timed


def _retime(track, timed) -> None:
    import music21.midi

    events, previous = [], 0
    for tick, event in timed:
        events.append(music21.midi.DeltaTime(track, time=tick - previous))
        events.append(event)
        previous = tick
    track.events = events


def _remove(track, predicate) -> None:
    _retime(track, [(tick, e) for tick, e in _timed(track) if not predicate(e)])


def _insert_at_start(track, new_events) -> None:
    """Insert events at tick 0, after the track's leading meta events (its name) and before
    any channel event."""
    if not new_events:
        return
    timed = _timed(track)
    at = next(
        (i for i, (tick, e) in enumerate(timed) if tick > 0 or _is_channel_event(e)),
        len(timed),
    )
    timed[at:at] = [(0, e) for e in new_events]
    _retime(track, timed)
