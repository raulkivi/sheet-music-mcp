"""A small SATB-like score for apply_abc_edit tests.

Three parts, four bars each. The Alto (P2) uses divisions 1 so an edit with eighth notes needs
more; bar 2 carries a dynamic, lyrics and an articulation, bar 3 a system break and a width, bar 4
the final barline. The header keeps a DOCTYPE and a comment, which an ElementTree round trip
would drop.
"""

import re
from xml.etree import ElementTree as ET


def _note(step: str, octave: int, duration: int, kind: str, extra: str = "") -> str:
    return (
        f"<note><pitch><step>{step}</step><octave>{octave}</octave></pitch>"
        f"<duration>{duration}</duration><type>{kind}</type>{extra}</note>"
    )


_LYRIC = '<lyric number="1"><syllabic>single</syllabic><text>{}</text></lyric>'
_ACCENT = "<notations><articulations><accent/></articulations></notations>"

SOPRANO = f"""  <part id="P1">
    <measure number="1" width="210">
      <print><system-layout><top-system-distance>170</top-system-distance></system-layout></print>
      <attributes><divisions>4</divisions><key><fifths>0</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes>
      <direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>72</per-minute></metronome></direction-type><sound tempo="72"/></direction>
      {_note("E", 5, 16, "whole")}
    </measure>
    <measure number="2">
      <direction placement="below"><direction-type><dynamics><p/></dynamics></direction-type></direction>
      {_note("D", 5, 16, "whole")}
    </measure>
    <measure number="3">
      {_note("C", 5, 16, "whole")}
    </measure>
    <measure number="4">
      {_note("C", 5, 16, "whole")}
      <barline location="right"><bar-style>light-heavy</bar-style></barline>
    </measure>
  </part>
"""

ALTO = f"""  <part id="P2">
    <measure number="1" width="210">
      <attributes><divisions>1</divisions><key><fifths>0</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes>
      {_note("G", 4, 4, "whole")}
    </measure>
    <measure number="2">
      <direction placement="below"><direction-type><dynamics><mf/></dynamics></direction-type></direction>
      {_note("A", 4, 2, "half", _ACCENT + _LYRIC.format("Ky"))}
      {_note("B", 4, 2, "half", _LYRIC.format("ri"))}
    </measure>
    <measure number="3" width="250">
      <print new-system="yes"/>
      {_note("G", 4, 4, "whole", _LYRIC.format("e"))}
    </measure>
    <measure number="4">
      {_note("E", 4, 4, "whole")}
      <barline location="right"><bar-style>light-heavy</bar-style></barline>
    </measure>
  </part>
"""

BASS = f"""  <part id="P3">
    <measure number="1" width="210">
      <attributes><divisions>4</divisions><key><fifths>0</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>F</sign><line>4</line></clef></attributes>
      {_note("C", 3, 16, "whole")}
    </measure>
    <measure number="2">
      {_note("F", 3, 16, "whole")}
    </measure>
    <measure number="3">
      {_note("G", 3, 16, "whole")}
    </measure>
    <measure number="4">
      {_note("C", 3, 16, "whole")}
      <barline location="right"><bar-style>light-heavy</bar-style></barline>
    </measure>
  </part>
"""

HEADER = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="4.0">
  <!-- engraved by hand for the apply_abc_edit tests -->
  <work><work-title>Kyrie</work-title></work>
  <part-list>
    <score-part id="P1"><part-name>Soprano</part-name></score-part>
    <score-part id="P2"><part-name>Alto</part-name><part-abbreviation>A.</part-abbreviation></score-part>
    <score-part id="P3"><part-name>Bass</part-name></score-part>
  </part-list>
"""

SCORE = HEADER + SOPRANO + ALTO + BASS + "</score-partwise>\n"

# Bars 2-3 of the Alto, with quarter and whole notes (fit divisions 1).
QUARTERS_ABC = "X:1\nT:Kyrie - Alto\nM:4/4\nL:1/8\nK:C\nc2 B2 A2 G2 | F8 |]"
# Bar 2 of the Alto with eighth notes (needs divisions 2).
EIGHTHS_ABC = "X:1\nM:4/4\nL:1/8\nK:C\nABcd e2 f2 |]"


def part_text(score: str, part_id: str) -> str:
    """The exact text of ``<part id=...>...</part>``."""
    match = re.search(rf'<part id="{part_id}">.*?</part>', score, re.DOTALL)
    assert match, part_id
    return match.group()


def canonical_part(score: str, part_id: str) -> str:
    """C14N 2.0 form of one part with whitespace-only text stripped: two parts are "identical"
    when these strings are equal (same elements, attributes, text and order)."""
    root = ET.fromstring(re.sub(r"<!DOCTYPE[^>]*>", "", score).encode())
    part = root.find(f"part[@id='{part_id}']")
    return ET.canonicalize(ET.tostring(part, encoding="unicode"), strip_text=True)


def measure(score: str, part_id: str, number: str) -> ET.Element:
    root = ET.fromstring(re.sub(r"<!DOCTYPE[^>]*>", "", score).encode())
    found = root.find(f"part[@id='{part_id}']/measure[@number='{number}']")
    assert found is not None, (part_id, number)
    return found


def notes(element: ET.Element) -> list[tuple]:
    """(step, alter, octave, type, duration) of each note in a measure, rests as 'rest'."""
    found = []
    for note in element.iter("note"):
        if note.find("rest") is not None:
            found.append(("rest", None, None, note.findtext("type"), note.findtext("duration")))
            continue
        found.append(
            (
                note.findtext("pitch/step"),
                note.findtext("pitch/alter") or "0",
                note.findtext("pitch/octave"),
                note.findtext("type"),
                note.findtext("duration"),
            )
        )
    return found
