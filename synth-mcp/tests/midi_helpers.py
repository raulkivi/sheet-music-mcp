"""Read MIDI bytes back into plain tuples for MIDI-level assertions (no FluidSynth needed)."""

from dataclasses import dataclass
from pathlib import Path

import music21.midi

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@dataclass(frozen=True)
class Event:
    tick: int
    kind: str  # "note_on", "note_off", "program", "cc", "tempo", "time_signature", "name", ...
    channel: int | None
    value: object  # pitch, program, (controller, value), BPM or raw data
    velocity: int | None = None


@dataclass
class Track:
    name: str
    events: list[Event]

    def of(self, kind: str) -> list[Event]:
        return [e for e in self.events if e.kind == kind]

    @property
    def channels(self) -> set[int]:
        return {e.channel for e in self.events if e.kind in _CHANNEL_KINDS}


_CHANNEL_KINDS = {"note_on", "note_off", "program", "cc", "pitch_bend"}


def read_midi(midi_bytes: bytes) -> tuple[int, list[Track]]:
    """(ticks per quarter, tracks) with absolute ticks."""
    mf = music21.midi.MidiFile()
    mf.readstr(midi_bytes)
    tracks = []
    for track in mf.tracks:
        tick, events, name = 0, [], ""
        for event in track.events:
            if event.isDeltaTime():
                tick += event.time
                continue
            events.append(_event(tick, event))
            if event.type == music21.midi.MetaEvents.SEQUENCE_TRACK_NAME:
                name = event.data.decode("utf-8", "replace")
        tracks.append(Track(name, events))
    return mf.ticksPerQuarterNote, tracks


def _event(tick: int, event) -> Event:
    t = event.type
    cv = music21.midi.ChannelVoiceMessages
    meta = music21.midi.MetaEvents
    if t == cv.NOTE_ON and event.velocity:
        return Event(tick, "note_on", event.channel, event.pitch, event.velocity)
    if t in (cv.NOTE_ON, cv.NOTE_OFF):
        return Event(tick, "note_off", event.channel, event.pitch)
    if t == cv.PROGRAM_CHANGE:
        return Event(tick, "program", event.channel, event.data)
    if t == cv.CONTROLLER_CHANGE:
        return Event(tick, "cc", event.channel, (event.parameter1, event.parameter2))
    if t == cv.PITCH_BEND:
        return Event(tick, "pitch_bend", event.channel, event.data)
    if t == meta.SET_TEMPO:
        return Event(tick, "tempo", None, round(60_000_000 / int.from_bytes(event.data, "big"), 3))
    if t == meta.TIME_SIGNATURE:
        return Event(tick, "time_signature", None, event.data)
    if t == meta.SEQUENCE_TRACK_NAME:
        return Event(tick, "name", None, event.data)
    return Event(tick, str(t), None, event.data)


def melodic_tracks(tracks: list[Track]) -> list[Track]:
    """Tracks with notes on a channel other than 10, in file order."""
    return [t for t in tracks if any(e.channel != 10 for e in t.of("note_on"))]


def click_events(tracks: list[Track]) -> list[Event]:
    """Every channel-10 note-on, sorted by tick."""
    return sorted(
        (e for t in tracks for e in t.of("note_on") if e.channel == 10), key=lambda e: e.tick
    )


def cc7(track: Track) -> list[int]:
    """CC7 (channel volume) values in a track."""
    return [e.value[1] for e in track.of("cc") if e.value[0] == 7]


def first_melodic_note_tick(tracks: list[Track]) -> int:
    return min(e.tick for t in melodic_tracks(tracks) for e in t.of("note_on"))


def last_melodic_note_off_tick(tracks: list[Track]) -> int:
    return max(e.tick for t in melodic_tracks(tracks) for e in t.of("note_off"))


def tempos(tracks: list[Track]) -> list[tuple[int, float]]:
    return sorted({(e.tick, e.value) for t in tracks for e in t.of("tempo")})
