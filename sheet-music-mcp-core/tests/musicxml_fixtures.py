"""Small MusicXML documents built inline for the score tests."""

from __future__ import annotations

DOCTYPE = (
    '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
    '"http://www.musicxml.org/dtds/partwise.dtd">\n'
)


def note(step, octave, alter=None, *, duration=2, chord=False, lyric=None, grace=False) -> str:
    parts = ["<note>"]
    if grace:
        parts.append("<grace/>")
    if chord:
        parts.append("<chord/>")
    parts.append(f"<pitch><step>{step}</step>")
    if alter is not None:
        parts.append(f"<alter>{alter}</alter>")
    parts.append(f"<octave>{octave}</octave></pitch>")
    if not grace:
        parts.append(f"<duration>{duration}</duration>")
    if lyric is not None:
        parts.append(f"<lyric><syllabic>single</syllabic><text>{lyric}</text></lyric>")
    parts.append("</note>")
    return "".join(parts)


def rest(duration=2) -> str:
    return f"<note><rest/><duration>{duration}</duration></note>"


def attributes(*, divisions=2, fifths=None, mode=None, time=None, clef=None, transpose=None) -> str:
    """``divisions=None`` leaves divisions out, as in a measure that only changes key or clef."""
    parts = ["<attributes>"]
    if divisions is not None:
        parts.append(f"<divisions>{divisions}</divisions>")
    if fifths is not None:
        parts.append(f"<key><fifths>{fifths}</fifths>")
        if mode is not None:
            parts.append(f"<mode>{mode}</mode>")
        parts.append("</key>")
    if time is not None:
        beats, beat_type = time.split("/")
        parts.append(f"<time><beats>{beats}</beats><beat-type>{beat_type}</beat-type></time>")
    if clef is not None:
        sign, line, *octave = clef
        parts.append(f"<clef><sign>{sign}</sign>")
        if line is not None:
            parts.append(f"<line>{line}</line>")
        if octave:
            parts.append(f"<clef-octave-change>{octave[0]}</clef-octave-change>")
        parts.append("</clef>")
    if transpose is not None:
        diatonic, chromatic = transpose
        parts.append(f"<transpose><diatonic>{diatonic}</diatonic><chromatic>{chromatic}</chromatic></transpose>")
    parts.append("</attributes>")
    return "".join(parts)


def tempo(bpm) -> str:
    return f'<direction placement="above"><direction-type><words>Moderato</words></direction-type><sound tempo="{bpm}"/></direction>'


def metronome(beat_unit, per_minute, *, dots=0) -> str:
    dot = "<beat-unit-dot/>" * dots
    return (
        f"<direction><direction-type><metronome><beat-unit>{beat_unit}</beat-unit>{dot}"
        f"<per-minute>{per_minute}</per-minute></metronome></direction-type></direction>"
    )


def _part_list(parts) -> str:
    items = []
    for part_id, name, abbreviation, _ in parts:
        item = f'<score-part id="{part_id}">'
        item += f"<part-name>{name}</part-name>" if name is not None else "<part-name/>"
        if abbreviation is not None:
            item += f"<part-abbreviation>{abbreviation}</part-abbreviation>"
        items.append(item + "</score-part>")
    return "<part-list>" + "".join(items) + "</part-list>"


def _header(title, composer, movement_title, credit) -> str:
    head = ""
    if title is not None:
        head += f"<work><work-title>{title}</work-title></work>"
    if movement_title is not None:
        head += f"<movement-title>{movement_title}</movement-title>"
    if composer is not None:
        head += f'<identification><creator type="composer">{composer}</creator></identification>'
    if credit is not None:
        head += f'<credit page="1"><credit-words>{credit}</credit-words></credit>'
    return head


def _measure_attributes(numbers, implicit_first, position) -> str:
    """The ``number`` (and ``implicit``) attributes of the measure at ``position`` (1-based)."""
    number = numbers[position - 1] if numbers is not None else str(position)
    implicit = ' implicit="yes"' if implicit_first and position == 1 else ""
    return f'number="{number}"{implicit}'


def partwise(
    parts, *, title=None, composer=None, movement_title=None, credit=None, numbers=None, implicit_first=False
) -> str:
    """``parts`` is a list of ``(id, name, abbreviation, [measure contents])``.

    Measures are numbered 1, 2, ... unless ``numbers`` gives each measure's ``number`` text;
    ``implicit_first`` marks the first measure ``implicit="yes"`` (a pickup).
    """
    body = "".join(
        f'<part id="{part_id}">'
        + "".join(
            f"<measure {_measure_attributes(numbers, implicit_first, n)}>{content}</measure>"
            for n, content in enumerate(measures, 1)
        )
        + "</part>"
        for part_id, _, _, measures in parts
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        + DOCTYPE
        + '<score-partwise version="4.0">'
        + _header(title, composer, movement_title, credit)
        + _part_list(parts)
        + body
        + "</score-partwise>\n"
    )


def timewise(parts, *, title=None, composer=None, numbers=None) -> str:
    """The same music as ``partwise(parts)``, grouped by measure."""
    count = len(parts[0][3])
    body = "".join(
        f"<measure {_measure_attributes(numbers, False, n)}>"
        + "".join(f'<part id="{part_id}">{measures[n - 1]}</part>' for part_id, _, _, measures in parts)
        + "</measure>"
        for n in range(1, count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + '<score-timewise version="4.0">'
        + _header(title, composer, None, None)
        + _part_list(parts)
        + body
        + "</score-timewise>\n"
    )


# SATB in D major, 3/4, quarter = 96: two measures of three quarters (divisions 2).
SATB_PARTS = [
    (
        "P1",
        "Soprano",
        "S.",
        [
            attributes(fifths=2, mode="major", time="3/4", clef=("G", 2)) + tempo(96)
            + note("D", 4, lyric="Glo") + note("F", 4, 1, lyric="ri") + note("A", 4, lyric="a"),
            note("F", 4, 1, duration=4) + rest(2),
        ],
    ),
    (
        "P2",
        "Alto",
        "A.",
        [
            attributes(fifths=2, mode="major", time="3/4", clef=("G", 2))
            + note("A", 3) + note("D", 4) + note("D", 4),
            note("A", 3, duration=6),
        ],
    ),
    (
        "P3",
        "Tenor",
        "T.",
        [
            attributes(fifths=2, mode="major", time="3/4", clef=("G", 2, -1))
            + note("F", 3, 1) + note("A", 3) + note("A", 3),
            note("D", 4, duration=6),
        ],
    ),
    (
        "P4",
        "Bass",
        "B.",
        [
            attributes(fifths=2, mode="major", time="3/4", clef=("F", 4))
            + note("D", 3) + note("B", 2, -1) + note("D", 3),
            rest(6),
        ],
    ),
]
SATB = partwise(SATB_PARTS, title="Test Chorale", composer="J. Tester")

# Two unnamed parts, no key, time, tempo, title or lyrics.
UNNAMED_PARTS = [
    ("P1", None, None, [attributes(divisions=1, clef=("G", 2)) + note("C", 5, duration=4)]),
    ("P2", None, None, [attributes(divisions=1, clef=("F", 4)) + rest(4)]),
]
UNNAMED = partwise(UNNAMED_PARTS)

# Chords do not advance, backup steps back, forward advances, grace notes take no time, and
# divisions change between measures: 4 + 2 = 6 quarters, at 120 bpm 3 seconds.
VOICES = partwise(
    [
        (
            "P1",
            "Piano",
            None,
            [
                attributes(divisions=1, time="4/4", clef=("G", 2)) + tempo(120)
                + note("C", 4, duration=4) + "<backup><duration>4</duration></backup>"
                + note("E", 4, duration=2) + note("G", 4, duration=2, chord=True)
                + "<forward><duration>2</duration></forward>",
                attributes(divisions=2) + note("D", 4, grace=True) + note("D", 4, duration=4),
            ],
        )
    ]
)


def single_part(content: str, **kwargs) -> str:
    """A one-part, one-measure score around ``content``."""
    return partwise([("P1", "Voice", None, [content])], **kwargs)


def _six_bars(first, change, step, octave, *, bar3_prefix=""):
    """Bar 1 ``first`` + four quarters, bar 2 ``change`` + three quarters, bars 3-6 three quarters."""
    return [
        first + note(step, octave) * 4,
        change + note(step, octave) * 3,
        bar3_prefix + note(step, octave) * 3,
        *(note(step, octave) * 3 for _ in range(3)),
    ]


# Six bars of SATB: C major 4/4 at quarter = 80 (soprano only) in bar 1; bar 2 changes to F major
# 3/4 without restating divisions, and the tenor to bass clef; bar 3 of the soprano starts with a
# system break. Divisions 2 throughout, so bars 3-6 last three quarters each.
SIX_BAR_PARTS = [
    (
        "P1",
        "Soprano",
        "S.",
        _six_bars(
            attributes(fifths=0, mode="major", time="4/4", clef=("G", 2)) + tempo(80),
            attributes(divisions=None, fifths=-1, mode="major", time="3/4"),
            "C", 5,
            bar3_prefix='<print new-system="yes"/>',
        ),
    ),
    (
        "P2",
        "Alto",
        "A.",
        _six_bars(
            attributes(fifths=0, mode="major", time="4/4", clef=("G", 2)),
            attributes(divisions=None, fifths=-1, mode="major", time="3/4"),
            "F", 4,
        ),
    ),
    (
        "P3",
        "Tenor",
        "T.",
        _six_bars(
            attributes(fifths=0, mode="major", time="4/4", clef=("G", 2, -1)),
            attributes(divisions=None, fifths=-1, mode="major", time="3/4", clef=("F", 4)),
            "A", 3,
        ),
    ),
    (
        "P4",
        "Bass",
        "B.",
        _six_bars(
            attributes(fifths=0, mode="major", time="4/4", clef=("F", 4)),
            attributes(divisions=None, fifths=-1, mode="major", time="3/4"),
            "F", 3,
        ),
    ),
]
SIX_BARS = partwise(SIX_BAR_PARTS, title="Six Bars")
