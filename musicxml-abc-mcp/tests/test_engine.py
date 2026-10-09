"""Unit and integration tests for musicxml_abc_mcp.engine."""

import io
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from musicxml_abc_mcp.engine import (
    ProcessingError,
    _duration_to_abc,
    _key_to_abc,
    _pitch_to_abc,
    abc_to_musicxml,
    musicxml_to_abc,
    validate_abc,
)

FIXTURES = Path(__file__).parent / "fixtures"

# ---------------------------------------------------------------------------
# Minimal MusicXML fixture (one part, one measure with a C4 quarter note)
# ---------------------------------------------------------------------------
MINIMAL_MUSICXML = """\
<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <work><work-title>Test Score</work-title></work>
  <part-list>
    <score-part id="P1"><part-name>Soprano</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>4</divisions>
        <key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <direction placement="above">
        <direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>120</per-minute></metronome></direction-type>
      </direction>
      <note>
        <pitch><step>C</step><octave>4</octave></pitch>
        <duration>4</duration><type>quarter</type>
      </note>
      <note>
        <pitch><step>E</step><octave>4</octave></pitch>
        <duration>4</duration><type>quarter</type>
      </note>
      <note>
        <pitch><step>G</step><octave>4</octave></pitch>
        <duration>4</duration><type>quarter</type>
      </note>
      <note><rest/><duration>4</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>
"""

MINIMAL_ABC = "X:1\nT:Test\nM:4/4\nL:1/8\nK:G\nGABc defg|]"


# ---------------------------------------------------------------------------
# Unit tests: helpers
# ---------------------------------------------------------------------------

class TestPitchToAbc:
    # ABC standard v2.1: uppercase C = middle C (C4); lowercase c = C5
    def test_c4_middle_c(self):
        import music21.pitch
        p = music21.pitch.Pitch("C4")
        assert _pitch_to_abc(p) == "C"

    def test_c5(self):
        import music21.pitch
        p = music21.pitch.Pitch("C5")
        assert _pitch_to_abc(p) == "c"

    def test_c3(self):
        import music21.pitch
        p = music21.pitch.Pitch("C3")
        assert _pitch_to_abc(p) == "C,"

    def test_c6(self):
        import music21.pitch
        p = music21.pitch.Pitch("C6")
        assert _pitch_to_abc(p) == "c'"

    def test_c7(self):
        import music21.pitch
        p = music21.pitch.Pitch("C7")
        assert _pitch_to_abc(p) == "c''"

    def test_c2(self):
        import music21.pitch
        p = music21.pitch.Pitch("C2")
        assert _pitch_to_abc(p) == "C,,"

    def test_sharp_note(self):
        import music21.pitch
        p = music21.pitch.Pitch("F#4")
        result = _pitch_to_abc(p)
        assert result == "^F"

    def test_flat_note(self):
        import music21.pitch
        p = music21.pitch.Pitch("B-4")
        result = _pitch_to_abc(p)
        assert result == "_B"

    def test_g4(self):
        import music21.pitch
        p = music21.pitch.Pitch("G4")
        assert _pitch_to_abc(p) == "G"

    def test_b4(self):
        import music21.pitch
        p = music21.pitch.Pitch("B4")
        assert _pitch_to_abc(p) == "B"

    def test_a5(self):
        import music21.pitch
        p = music21.pitch.Pitch("A5")
        assert _pitch_to_abc(p) == "a"


class TestDurationToAbc:
    def test_whole_note(self):
        assert _duration_to_abc(4.0) == "8"

    def test_half_note(self):
        assert _duration_to_abc(2.0) == "4"

    def test_quarter_note(self):
        assert _duration_to_abc(1.0) == "2"

    def test_eighth_note(self):
        assert _duration_to_abc(0.5) == ""  # 1 unit, omit

    def test_sixteenth_note(self):
        assert _duration_to_abc(0.25) == "1/2"

    def test_dotted_quarter(self):
        assert _duration_to_abc(1.5) == "3"

    def test_dotted_half(self):
        assert _duration_to_abc(3.0) == "6"


class TestKeyToAbc:
    def test_c_major(self):
        import music21.key
        k = music21.key.Key("C")
        assert _key_to_abc(k) == "C"

    def test_g_major(self):
        import music21.key
        k = music21.key.Key("G")
        assert _key_to_abc(k) == "G"

    def test_f_major(self):
        import music21.key
        k = music21.key.Key("F")
        assert _key_to_abc(k) == "F"

    def test_a_minor(self):
        import music21.key
        k = music21.key.Key("a")
        result = _key_to_abc(k)
        assert "m" in result.lower() or result == "Am"

    def test_key_signature_no_sharps(self):
        import music21.key
        ks = music21.key.KeySignature(0)
        assert _key_to_abc(ks) == "C"

    def test_key_signature_one_sharp(self):
        import music21.key
        ks = music21.key.KeySignature(1)
        assert _key_to_abc(ks) == "G"


# ---------------------------------------------------------------------------
# Unit tests: engine functions (with real music21 but minimal fixtures)
# ---------------------------------------------------------------------------

class TestMusicxmlToAbc:
    def test_minimal_score_all_parts(self):
        result = musicxml_to_abc(MINIMAL_MUSICXML)
        assert "abc" in result
        assert "parts_included" in result
        assert "warnings" in result
        assert result["parts_included"] == ["Soprano"]
        abc = result["abc"]
        assert "X:1" in abc
        assert "M:4/4" in abc
        assert "K:" in abc

    def test_abc_contains_notes(self):
        result = musicxml_to_abc(MINIMAL_MUSICXML)
        abc = result["abc"]
        # C E G should appear
        assert "C" in abc or "c" in abc

    def test_invalid_musicxml_raises(self):
        with pytest.raises(ProcessingError) as exc:
            musicxml_to_abc("<not-musicxml/>")
        assert exc.value.error_code == "INVALID_INPUT"

    def test_empty_musicxml_raises(self):
        with pytest.raises(ProcessingError) as exc:
            musicxml_to_abc("")
        assert exc.value.error_code in ("INVALID_INPUT", "PROCESSING_FAILED")

    def test_invalid_part_id_raises(self):
        with pytest.raises(ProcessingError) as exc:
            musicxml_to_abc(MINIMAL_MUSICXML, part_id="P99")
        assert exc.value.error_code == "INVALID_PARAMETER"

    def test_valid_part_id_filters(self):
        result = musicxml_to_abc(MINIMAL_MUSICXML, part_id="Soprano")
        assert result["parts_included"] == ["Soprano"]

    def test_part_filter_only_returns_one_tune(self):
        result = musicxml_to_abc(MINIMAL_MUSICXML, part_id="Soprano")
        abc = result["abc"]
        # Should have exactly one X: header
        x_count = abc.count("\nX:") + (1 if abc.startswith("X:") else 0)
        assert x_count == 1


class TestAbcToMusicxml:
    def test_basic_abc_converts(self):
        result = abc_to_musicxml(MINIMAL_ABC)
        assert "musicxml" in result
        xml = result["musicxml"]
        assert "<score-partwise" in xml

    def test_empty_abc_raises(self):
        with pytest.raises(ProcessingError) as exc:
            abc_to_musicxml("")
        assert exc.value.error_code == "INVALID_INPUT"

    def test_invalid_abc_raises(self):
        with pytest.raises(ProcessingError) as exc:
            abc_to_musicxml("this is not abc")
        # music21 may raise on parse
        assert exc.value.error_code in ("INVALID_INPUT", "PROCESSING_FAILED")

    def test_abc_round_trip_preserves_octaves(self):
        """ABC -> MusicXML -> ABC must not shift notes by an octave."""
        import music21.converter

        abc_in = "X:1\nT:Octaves\nM:4/4\nL:1/8\nK:C\nC,2 C2 c2 c'2|]"
        xml = abc_to_musicxml(abc_in)["musicxml"]
        abc_out = musicxml_to_abc(xml)["abc"]

        def pitches(abc):
            score = music21.converter.parseData(abc, format="abc")
            return [p.nameWithOctave for p in score.flatten().pitches]

        assert pitches(abc_in) == ["C3", "C4", "C5", "C6"]
        assert pitches(abc_out) == pitches(abc_in)

    def test_multi_tune_abc_merges(self):
        multi_abc = "X:1\nT:Soprano\nM:4/4\nL:1/8\nK:C\nCDEF|]\n\nX:2\nT:Alto\nM:4/4\nL:1/8\nK:C\nG,A,B,C|]"
        result = abc_to_musicxml(multi_abc)
        xml = result["musicxml"]
        assert "<score-partwise" in xml


class TestValidateAbc:
    def test_valid_abc(self):
        result = validate_abc(MINIMAL_ABC)
        assert result["valid"] is True
        assert result["errors"] == []

    def test_empty_abc(self):
        result = validate_abc("")
        assert result["valid"] is False
        assert result["errors"]

    def test_missing_headers_warns(self):
        result = validate_abc("CDEG|]")  # no X:, T:, K:
        # Even if music21 accepts it, we should warn
        assert result["warnings"]

    def test_valid_minimal_abc_with_all_headers(self):
        abc = "X:1\nT:Test\nM:4/4\nL:1/8\nK:C\nCDEF GABC|]"
        result = validate_abc(abc)
        assert result["valid"] is True

    def test_warnings_for_missing_x(self):
        abc = "T:Test\nM:4/4\nL:1/8\nK:C\nCDEF|]"
        result = validate_abc(abc)
        assert any("X:" in w for w in result["warnings"])

    def test_warnings_for_missing_t(self):
        abc = "X:1\nM:4/4\nL:1/8\nK:C\nCDEF|]"
        result = validate_abc(abc)
        assert any("T:" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# Integration tests: real MXL fixture (4-part SATB)
# ---------------------------------------------------------------------------

def _load_mxl_fixture() -> str:
    """Load the first available SATB MXL fixture as a MusicXML string."""
    mxl_dir = Path("../omr-mcp/test_samples/pdmx_satb_samples/mxl")
    mxl_files = sorted(mxl_dir.glob("*.mxl"))
    if not mxl_files:
        pytest.skip("No MXL fixtures available")

    mxl_path = mxl_files[0]
    with open(mxl_path, "rb") as f:
        raw = f.read()

    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        container = ET.fromstring(z.read("META-INF/container.xml"))
        rootfile = container.find(".//rootfile")
        root_path = rootfile.get("full-path")
        return z.read(root_path).decode("utf-8")


@pytest.mark.integration
class TestIntegrationRoundTrip:
    def test_satb_musicxml_to_abc(self):
        musicxml = _load_mxl_fixture()
        result = musicxml_to_abc(musicxml)
        assert result["parts_included"] == ["Soprano", "Alto", "Tenor", "Bass"]
        abc = result["abc"]
        assert abc.count("X:") == 4
        assert len(abc) > 100

    def test_satb_round_trip_note_count(self):
        import music21

        musicxml = _load_mxl_fixture()

        # Count original notes
        score_orig = music21.converter.parseData(musicxml, format="musicxml")
        orig_count = sum(len(list(p.flatten().notes)) for p in score_orig.parts)
        assert orig_count > 0

        # Convert to ABC and back
        abc_result = musicxml_to_abc(musicxml)
        xml_result = abc_to_musicxml(abc_result["abc"])

        score_rt = music21.converter.parseData(xml_result["musicxml"], format="musicxml")
        rt_count = sum(len(list(p.flatten().notes)) for p in score_rt.parts)

        # Within 5%
        assert abs(orig_count - rt_count) / orig_count < 0.05, (
            f"Note count changed too much: {orig_count} → {rt_count}"
        )

    def test_part_id_filter_soprano_only(self):
        musicxml = _load_mxl_fixture()
        result = musicxml_to_abc(musicxml, part_id="Soprano")
        assert result["parts_included"] == ["Soprano"]
        abc = result["abc"]
        assert abc.count("X:") == 1
        assert "Soprano" in abc

    def test_validate_generated_abc_is_valid(self):
        musicxml = _load_mxl_fixture()
        abc_result = musicxml_to_abc(musicxml)
        # Validate each individual tune
        for tune in abc_result["abc"].split("\n\n"):
            if tune.strip():
                val = validate_abc(tune)
                assert val["valid"] is True, (
                    f"Generated ABC failed validation:\n{tune}\nErrors: {val['errors']}"
                )
