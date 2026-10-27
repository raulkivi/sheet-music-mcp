"""Score files and descriptions (docs/conventions.md, Score References: describe_score)."""

import struct
import zipfile

import pytest

from sheet_music_mcp_core.errors import ProcessingError
from sheet_music_mcp_core.scores import (
    ScoreFormatError,
    describe_score,
    parse_score,
    read_score_file,
    score_summary,
)

from .musicxml_fixtures import (
    SATB,
    SATB_PARTS,
    UNNAMED,
    UNNAMED_PARTS,
    VOICES,
    attributes,
    metronome,
    note,
    partwise,
    rest,
    single_part,
    tempo,
    timewise,
)

CONTAINER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<container><rootfiles>"
    '<rootfile full-path="{path}" media-type="application/vnd.recordare.musicxml+xml"/>'
    "</rootfiles></container>"
)
LIMIT = 1024 * 1024


def _mxl(path, members, *, compression=zipfile.ZIP_DEFLATED):
    with zipfile.ZipFile(path, "w", compression) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


class TestReadScoreFile:
    def test_plain_file(self, tmp_path):
        path = tmp_path / "a.musicxml"
        path.write_text(SATB, encoding="utf-8")

        assert read_score_file(path, max_bytes=LIMIT) == SATB

    def test_accepts_a_string_path(self, tmp_path):
        path = tmp_path / "a.xml"
        path.write_text(SATB, encoding="utf-8")

        assert read_score_file(str(path), max_bytes=LIMIT) == SATB

    def test_utf8_bom_is_removed(self, tmp_path):
        path = tmp_path / "bom.musicxml"
        path.write_bytes(b"\xef\xbb\xbf" + SATB.encode("utf-8"))

        assert read_score_file(path, max_bytes=LIMIT) == SATB

    def test_declared_utf16_is_decoded(self, tmp_path):
        text = SATB.replace('encoding="UTF-8"', 'encoding="UTF-16"')
        path = tmp_path / "wide.musicxml"
        path.write_bytes(text.encode("utf-16"))

        result = read_score_file(path, max_bytes=LIMIT)

        assert result == text
        assert describe_score(result)["title"] == "Test Chorale"

    def test_declared_latin1_is_decoded(self, tmp_path):
        text = single_part(note("C", 4), title="Kärntner Lied").replace('encoding="UTF-8"', 'encoding="ISO-8859-1"')
        path = tmp_path / "latin.musicxml"
        path.write_bytes(text.encode("latin-1"))

        assert describe_score(read_score_file(path, max_bytes=LIMIT))["title"] == "Kärntner Lied"

    def test_undecodable_text_is_invalid_input_without_content(self, tmp_path):
        path = tmp_path / "bad.musicxml"
        path.write_bytes(b"<score-partwise>secret \xff\xfe\xfa</score-partwise>")

        with pytest.raises(ScoreFormatError) as info:
            read_score_file(path, max_bytes=LIMIT)

        assert info.value.error_code == "INVALID_INPUT"
        assert "secret" not in str(info.value)
        assert "\\xff" not in str(info.value) and "0xff" not in str(info.value)

    def test_unknown_declared_encoding_is_invalid_input(self, tmp_path):
        path = tmp_path / "bogus.musicxml"
        path.write_bytes(b'<?xml version="1.0" encoding="bogus-enc"?><score-partwise/>')

        with pytest.raises(ScoreFormatError):
            read_score_file(path, max_bytes=LIMIT)

    def test_plain_file_over_the_limit(self, tmp_path):
        path = tmp_path / "big.musicxml"
        path.write_text(SATB)

        with pytest.raises(ProcessingError) as info:
            read_score_file(path, max_bytes=100)

        assert info.value.error_code == "FILE_TOO_LARGE"

    def test_missing_file(self, tmp_path):
        with pytest.raises(ProcessingError) as info:
            read_score_file(tmp_path / "missing.musicxml", max_bytes=LIMIT)

        assert info.value.error_code == "FILE_NOT_FOUND"

    def test_mxl_with_container_equals_the_plain_text(self, tmp_path):
        path = _mxl(
            tmp_path / "a.mxl",
            {
                "META-INF/container.xml": CONTAINER.format(path="score/main.musicxml"),
                "aaa-decoy.xml": "<other/>",
                "score/main.musicxml": SATB,
            },
        )

        assert read_score_file(path, max_bytes=LIMIT) == SATB

    def test_mxl_without_container_uses_first_score_member(self, tmp_path):
        path = _mxl(
            tmp_path / "b.mxl",
            {"META-INF/manifest.xml": "<manifest/>", "readme.txt": "hi", "song.musicxml": SATB},
        )

        assert read_score_file(path, max_bytes=LIMIT) == SATB

    def test_mxl_container_naming_a_missing_member_falls_back(self, tmp_path):
        path = _mxl(
            tmp_path / "c.mxl",
            {"META-INF/container.xml": CONTAINER.format(path="gone.xml"), "song.xml": SATB},
        )

        assert read_score_file(path, max_bytes=LIMIT) == SATB

    def test_mxl_member_with_bom(self, tmp_path):
        path = _mxl(tmp_path / "d.mxl", {"song.xml": b"\xef\xbb\xbf" + SATB.encode()})

        assert read_score_file(path, max_bytes=LIMIT) == SATB

    def test_mxl_without_a_score(self, tmp_path):
        path = _mxl(tmp_path / "e.mxl", {"META-INF/container.xml": "<container/>", "a.txt": "x"})

        with pytest.raises(ScoreFormatError) as info:
            read_score_file(path, max_bytes=LIMIT)

        assert info.value.error_code == "INVALID_INPUT"

    def test_bad_zip(self, tmp_path):
        path = tmp_path / "f.mxl"
        path.write_text("this is not a zip file")

        with pytest.raises(ScoreFormatError) as info:
            read_score_file(path, max_bytes=LIMIT)

        assert info.value.error_code == "INVALID_INPUT"
        assert "this is not" not in str(info.value)

    def test_zip_bomb_is_rejected_before_extracting(self, tmp_path, monkeypatch):
        path = _mxl(tmp_path / "bomb.mxl", {"bomb.musicxml": b"\x00" * (2 * LIMIT)})
        real_open = zipfile.ZipFile.open

        def guarded_open(self, name, *args, **kwargs):
            member = name.filename if isinstance(name, zipfile.ZipInfo) else name
            assert member != "bomb.musicxml", "the oversize member must be rejected from its header"
            return real_open(self, name, *args, **kwargs)

        monkeypatch.setattr(zipfile.ZipFile, "open", guarded_open)

        with pytest.raises(ProcessingError) as info:
            read_score_file(path, max_bytes=LIMIT)

        assert info.value.error_code == "FILE_TOO_LARGE"

    def test_member_with_a_lying_size_header_is_rejected(self, tmp_path):
        data = SATB.encode() * 20
        path = _mxl(tmp_path / "liar.mxl", {"song.musicxml": data})
        raw = path.read_bytes()
        real_size = struct.pack("<I", len(data))
        assert raw.count(real_size) == 2  # local header and central directory
        path.write_bytes(raw.replace(real_size, struct.pack("<I", 100)))

        with pytest.raises(ProcessingError) as info:
            read_score_file(path, max_bytes=1000)

        assert info.value.error_code in ("FILE_TOO_LARGE", "INVALID_INPUT")


class TestParseScore:
    def test_returns_the_root_element(self):
        assert parse_score(SATB).tag == "score-partwise"

    def test_accepts_bytes(self):
        assert parse_score(SATB.encode("utf-16")).tag == "score-partwise"

    def test_string_with_an_encoding_declaration_and_bom(self):
        text = "\ufeff" + SATB.replace('encoding="UTF-8"', 'encoding="UTF-16"')

        assert parse_score(text).tag == "score-partwise"

    def test_musicxml_doctype_is_allowed(self):
        assert "<!DOCTYPE score-partwise PUBLIC" in SATB
        assert parse_score(SATB) is not None

    def test_malformed_xml_gives_line_and_column_only(self):
        text = '<?xml version="1.0"?>\n<score-partwise>\n<work>secret words</wrong>'

        with pytest.raises(ScoreFormatError) as info:
            parse_score(text)

        assert info.value.error_code == "INVALID_INPUT"
        assert str(info.value) == "Score is not well-formed XML at line 3, column 20"
        assert "secret" not in str(info.value)

    def test_empty_text(self):
        with pytest.raises(ScoreFormatError):
            parse_score("")

    def test_billion_laughs_is_rejected(self):
        bomb = (
            '<?xml version="1.0"?>\n<!DOCTYPE lolz [<!ENTITY lol "lol">'
            '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
            "<score-partwise>&lol2;</score-partwise>"
        )

        with pytest.raises(ScoreFormatError) as info:
            parse_score(bomb)

        assert info.value.error_code == "INVALID_INPUT"
        assert "lol" not in str(info.value)

    def test_external_entity_is_rejected_without_naming_it(self):
        xxe = (
            '<?xml version="1.0"?>\n<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
            "<score-partwise>&e;</score-partwise>"
        )

        with pytest.raises(ScoreFormatError) as info:
            parse_score(xxe)

        assert "passwd" not in str(info.value)

    def test_other_root_is_rejected_without_naming_it(self):
        with pytest.raises(ScoreFormatError) as info:
            parse_score("<secret-root-name/>")

        assert info.value.error_code == "INVALID_INPUT"
        assert "secret-root-name" not in str(info.value)
        assert "score-partwise" in str(info.value)

    def test_is_a_processing_error(self):
        assert issubclass(ScoreFormatError, ProcessingError)


class TestDescribeScore:
    def test_satb(self):
        assert describe_score(SATB) == {
            "title": "Test Chorale",
            "composer": "J. Tester",
            "key": "D major",
            "time": "3/4",
            "tempo_bpm": 96,
            "parts": [
                {"id": "P1", "name": "Soprano", "abbreviation": "S.", "clef": "treble",
                 "range": {"low": "D4", "high": "A4"}},
                {"id": "P2", "name": "Alto", "abbreviation": "A.", "clef": "treble",
                 "range": {"low": "A3", "high": "D4"}},
                {"id": "P3", "name": "Tenor", "abbreviation": "T.", "clef": "treble_8vb",
                 "range": {"low": "F#3", "high": "D4"}},
                {"id": "P4", "name": "Bass", "abbreviation": "B.", "clef": "bass",
                 "range": {"low": "Bb2", "high": "D3"}},
            ],
            "measures": 2,
            "has_lyrics": True,
            "duration_quarters": 6.0,
            "duration_seconds": 3.75,
        }

    def test_unnamed_two_parts_without_key_time_tempo_or_title(self):
        assert describe_score(UNNAMED) == {
            "title": None,
            "composer": None,
            "key": None,
            "time": None,
            "tempo_bpm": None,
            "parts": [
                {"id": "P1", "name": None, "abbreviation": None, "clef": "treble",
                 "range": {"low": "C5", "high": "C5"}},
                {"id": "P2", "name": None, "abbreviation": None, "clef": "bass", "range": None},
            ],
            "measures": 1,
            "has_lyrics": False,
            "duration_quarters": 4.0,
            "duration_seconds": None,
        }

    def test_timewise_equals_partwise(self):
        expected = describe_score(SATB)

        assert describe_score(timewise(SATB_PARTS, title="Test Chorale", composer="J. Tester")) == expected
        assert describe_score(timewise(UNNAMED_PARTS)) == describe_score(UNNAMED)

    def test_chords_backup_forward_and_grace_notes(self):
        description = describe_score(VOICES)

        assert description["duration_quarters"] == 6.0
        assert description["duration_seconds"] == 3.0
        assert description["parts"][0]["range"] == {"low": "C4", "high": "G4"}

    def test_pickup_measure_counts_its_actual_length(self):
        score = partwise(
            [("P1", "V", None, [attributes(divisions=1, time="4/4") + note("C", 4, duration=1),
                                 note("D", 4, duration=4)])]
        )

        assert describe_score(score)["duration_quarters"] == 5.0

    @pytest.mark.parametrize(
        ("fifths", "mode", "expected"),
        [
            (2, "major", "D major"),
            (2, "minor", "B minor"),
            (-2, None, "Bb major"),
            (0, "minor", "A minor"),
            (7, "major", "C# major"),
            (-7, "major", "Cb major"),
            (6, "minor", "D# minor"),
            (0, "dorian", "D dorian"),
            (1, "mixolydian", "D mixolydian"),
        ],
    )
    def test_key(self, fifths, mode, expected):
        score = single_part(attributes(fifths=fifths, mode=mode) + note("C", 4))

        assert describe_score(score)["key"] == expected

    @pytest.mark.parametrize(
        ("clef", "expected"),
        [
            (("G", 2), "treble"),
            (("G", 2, -1), "treble_8vb"),
            (("F", 4), "bass"),
            (("C", 3), "alto"),
            (("C", 4), "tenor"),
            (("percussion", None), "percussion"),
            (("G", 1), "G1"),
            (("F", 3), "F3"),
            (("G", None), "treble"),
        ],
    )
    def test_clef(self, clef, expected):
        score = single_part(attributes(clef=clef) + note("C", 4))

        assert describe_score(score)["parts"][0]["clef"] == expected

    def test_part_without_clef(self):
        assert describe_score(single_part(attributes() + note("C", 4)))["parts"][0]["clef"] is None

    def test_double_sharps_and_flats(self):
        score = single_part(attributes() + note("C", 4, 2) + note("B", 3, -2))

        assert describe_score(score)["parts"][0]["range"] == {"low": "Bbb3", "high": "C##4"}

    def test_range_compares_by_midi_number_not_name(self):
        # Fb4 (MIDI 64) is below E#4 (MIDI 65), although E sorts before F.
        score = single_part(attributes() + note("E", 4, 1) + note("F", 4, -1))

        assert describe_score(score)["parts"][0]["range"] == {"low": "Fb4", "high": "E#4"}

    def test_range_ignores_rests_and_unpitched_notes(self):
        unpitched = "<note><unpitched><display-step>E</display-step><display-octave>6</display-octave></unpitched><duration>2</duration></note>"
        score = single_part(attributes() + rest() + unpitched + note("G", 4))

        assert describe_score(score)["parts"][0]["range"] == {"low": "G4", "high": "G4"}

    def test_range_is_sounding_pitch_for_transposing_parts(self):
        # A B-flat clarinet: written D5 sounds C5.
        score = single_part(attributes(transpose=(-1, -2)) + note("D", 5))

        assert describe_score(score)["parts"][0]["range"] == {"low": "C5", "high": "C5"}

    def test_tempo_from_metronome_in_quarter_notes(self):
        score = single_part(attributes() + metronome("quarter", 60, dots=1) + note("C", 4, duration=6))

        description = describe_score(score)

        assert description["tempo_bpm"] == 90
        assert description["duration_seconds"] == 2.0

    def test_metronome_half_note(self):
        score = single_part(attributes() + metronome("half", 40) + note("C", 4))

        assert describe_score(score)["tempo_bpm"] == 80

    def test_sound_tempo_wins_over_metronome(self):
        score = single_part(attributes() + metronome("quarter", 60) + tempo(100) + note("C", 4))

        assert describe_score(score)["tempo_bpm"] == 100

    def test_fractional_tempo(self):
        score = single_part(attributes() + tempo("72.5") + note("C", 4))

        assert describe_score(score)["tempo_bpm"] == 72.5

    def test_score_without_tempo(self):
        description = describe_score(single_part(attributes() + note("C", 4, duration=4)))

        assert description["tempo_bpm"] is None
        assert description["duration_quarters"] == 2.0
        assert description["duration_seconds"] is None

    @pytest.mark.parametrize(
        ("kwargs", "expected"),
        [
            ({"title": "Work", "movement_title": "Movement", "credit": "Credit"}, "Work"),
            ({"movement_title": "Movement", "credit": "Credit"}, "Movement"),
            ({"credit": "Credit"}, "Credit"),
            ({}, None),
        ],
    )
    def test_title_fallbacks(self, kwargs, expected):
        assert describe_score(single_part(note("C", 4), **kwargs))["title"] == expected

    def test_invalid_text_raises_score_format_error(self):
        with pytest.raises(ScoreFormatError):
            describe_score("<not closed")


class TestScoreSummary:
    def test_is_the_a1_subset(self):
        assert score_summary(SATB) == {
            "title": "Test Chorale",
            "parts": [
                {"id": "P1", "name": "Soprano", "range": {"low": "D4", "high": "A4"}},
                {"id": "P2", "name": "Alto", "range": {"low": "A3", "high": "D4"}},
                {"id": "P3", "name": "Tenor", "range": {"low": "F#3", "high": "D4"}},
                {"id": "P4", "name": "Bass", "range": {"low": "Bb2", "high": "D3"}},
            ],
            "measures": 2,
            "key": "D major",
            "time": "3/4",
            "tempo_bpm": 96,
        }


class TestHostileNumbers:
    """Numbers in a score are untrusted text. Exponent notation, non-finite values and absurdly
    long digit runs are ignored like any other non-numeric text, so a crafted file can neither
    stall describe_score (``Fraction("1e999999999")`` builds a billion-digit integer) nor crash it
    with OverflowError."""

    @staticmethod
    def _with_duration(value):
        return single_part(attributes(divisions=2) + note("C", 4, duration=value) + note("D", 4, duration=2))

    @pytest.mark.parametrize("value", ["1e3", "1e999999999", "1E2", "inf", "nan", "9" * 400])
    def test_duration_is_ignored_like_text(self, value):
        assert describe_score(self._with_duration(value)) == describe_score(self._with_duration("x"))

    @pytest.mark.parametrize("value", ["1e3", "1e999999999", "inf", "9" * 400])
    def test_divisions_is_ignored_like_text(self, value):
        def score(divisions):
            return single_part(attributes(divisions=divisions) + note("C", 4, duration=2))

        assert describe_score(score(value)) == describe_score(score("x"))

    @pytest.mark.parametrize("value", ["1e999", "inf", "-inf", "nan", "9" * 400])
    def test_transpose_chromatic_is_ignored_like_text(self, value):
        def score(chromatic):
            return single_part(attributes(transpose=(-1, chromatic)) + note("C", 4))

        assert describe_score(score(value)) == describe_score(score("x"))

    @pytest.mark.parametrize("value", ["1e999", "9" * 400])
    def test_transpose_octave_change_is_ignored_like_text(self, value):
        def score(octaves):
            return single_part(
                "<attributes><divisions>2</divisions><transpose><diatonic>0</diatonic>"
                f"<chromatic>0</chromatic><octave-change>{octaves}</octave-change></transpose>"
                "</attributes>" + note("C", 4)
            )

        assert describe_score(score(value)) == describe_score(score("x"))

    @pytest.mark.parametrize("value", ["9" * 400, "1e999", "0"])
    def test_tempo_never_crashes(self, value):
        result = describe_score(single_part(tempo(value) + attributes() + note("C", 4)))

        assert result["tempo_bpm"] is None or 0 < result["tempo_bpm"] < 1e10
        assert result["duration_seconds"] is None or result["duration_seconds"] >= 0
