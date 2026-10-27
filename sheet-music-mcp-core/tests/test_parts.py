"""Voice-part selection (docs/conventions.md, Part Selection)."""

import pytest

from sheet_music_mcp_core.errors import ProcessingError
from sheet_music_mcp_core.parts import (
    PartInfo,
    PartSelectionError,
    music21_part_infos,
    resolve_part,
    resolve_parts,
)

SATB = [
    PartInfo("P1", "Soprano"),
    PartInfo("P2", "Alto"),
    PartInfo("P3", "Tenor"),
    PartInfo("P4", "Bass"),
]

DIVISI = [
    PartInfo("P1", "Soprano 1"),
    PartInfo("P2", "Soprano 2"),
    PartInfo("P3", "Alto I"),
    PartInfo("P4", "Alto II"),
    PartInfo("P5", "Tenor"),
    PartInfo("P6", "Bass"),
]


class TestTier1ExactId:
    def test_exact_id(self):
        assert resolve_parts(["P2"], SATB) == ["P2"]

    def test_id_beats_role_alias(self):
        parts = [PartInfo("B", "Bells"), PartInfo("P2", "Bass")]

        assert resolve_part("B", parts) == "B"


class TestTier2NameOrId:
    @pytest.mark.parametrize("request_", ["Soprano", "soprano", "  SOPRANO. ", "Soprano!"])
    def test_name_is_normalised(self, request_):
        assert resolve_parts([request_], SATB) == ["P1"]

    def test_id_ignores_case(self):
        assert resolve_part("p3", SATB) == "P3"

    def test_roman_numerals_in_names(self):
        assert resolve_part("alto 2", DIVISI) == "P4"
        assert resolve_part("Alto II", DIVISI) == "P4"

    def test_hyphenated_name(self):
        parts = [PartInfo("P1", "Mezzo-soprano")]

        assert resolve_part("mezzo soprano", parts) == "P1"

    def test_abbreviation(self):
        parts = [
            PartInfo("P1", "Canto", "C."),
            PartInfo("P2", "Quinto", "Q."),
            PartInfo("P3", "Basso", "B."),
        ]

        assert resolve_part("Q", parts) == "P2"
        assert resolve_part("q.", parts) == "P2"

    def test_abbreviation_defaults_to_empty(self):
        assert PartInfo("P1", "Soprano").abbreviation == ""

    def test_name_beats_role(self):
        parts = [PartInfo("P1", "Alto"), PartInfo("P2", "Alto 1")]

        assert resolve_parts(["Alto"], parts) == ["P1"]


class TestTier3VoiceRole:
    @pytest.mark.parametrize(
        "request_, expected",
        [("S", "P1"), ("A", "P2"), ("T", "P3"), ("B", "P4"), ("Sop", "P1"), ("Contralto", "P2")],
    )
    def test_abbreviations(self, request_, expected):
        assert resolve_part(request_, SATB) == expected

    def test_german_and_estonian_part_names(self):
        parts = [
            PartInfo("P1", "Sopran"),
            PartInfo("P2", "Alt"),
            PartInfo("P3", "Tenor"),
            PartInfo("P4", "Bass"),
        ]

        assert resolve_parts(["Soprano", "Alto"], parts) == ["P1", "P2"]

    def test_latin_and_italian_part_names(self):
        parts = [
            PartInfo("P1", "Cantus"),
            PartInfo("P2", "Altus"),
            PartInfo("P3", "Tenor"),
            PartInfo("P4", "Bassus"),
        ]

        assert resolve_parts(["S", "Alto", "Bass"], parts) == ["P1", "P2", "P4"]

    def test_canto_and_basso(self):
        parts = [PartInfo("P1", "Canto"), PartInfo("P2", "Basso")]

        assert resolve_parts(["Soprano", "B"], parts) == ["P1", "P2"]

    def test_mezzo_and_baritone_are_their_own_roles(self):
        parts = [
            PartInfo("P1", "Soprano"),
            PartInfo("P2", "Mezzo-soprano"),
            PartInfo("P3", "Alto"),
            PartInfo("P4", "Baritone"),
            PartInfo("P5", "Bass"),
        ]

        assert resolve_parts(["Alto"], parts) == ["P3"]
        assert resolve_parts(["Bass"], parts) == ["P5"]
        assert resolve_parts(["Mezzo"], parts) == ["P2"]
        assert resolve_parts(["MS"], parts) == ["P2"]
        assert resolve_parts(["Bar"], parts) == ["P4"]

    def test_role_selects_every_division(self):
        assert resolve_parts(["Alto"], DIVISI) == ["P3", "P4"]

    @pytest.mark.parametrize("request_", ["A1", "a 1", "Alt I", "alto1"])
    def test_divisi_request_selects_one_division(self, request_):
        assert resolve_parts([request_], DIVISI) == ["P3"]

    def test_treble_is_soprano(self):
        parts = [PartInfo("P1", "Treble"), PartInfo("P2", "Alto")]

        assert resolve_parts(["Soprano"], parts) == ["P1"]
        assert resolve_parts(["Tr"], [PartInfo("P1", "Soprano")]) == ["P1"]

    def test_countertenor_is_its_own_role(self):
        parts = [
            PartInfo("P1", "Countertenor"),
            PartInfo("P2", "Alto"),
            PartInfo("P3", "Tenor"),
        ]

        assert resolve_parts(["Alto"], parts) == ["P2"]
        assert resolve_parts(["Tenor"], parts) == ["P3"]
        assert resolve_parts(["CT"], parts) == ["P1"]
        assert resolve_parts(["Contratenor"], parts) == ["P1"]
        assert resolve_parts(["Counter-tenor"], parts) == ["P1"]

    def test_divisi_request_does_not_match_undivided_part(self):
        with pytest.raises(PartSelectionError):
            resolve_parts(["S1"], SATB)


class TestResolvePartsResult:
    def test_request_order_and_no_duplicates(self):
        assert resolve_parts(["Bass", "S", "Soprano", "P4"], SATB) == ["P4", "P1"]

    def test_empty_request(self):
        assert resolve_parts([], SATB) == []


class TestErrors:
    def test_no_match_lists_all_parts_as_choices(self):
        with pytest.raises(PartSelectionError) as excinfo:
            resolve_parts(["Sopran0"], SATB)

        error = excinfo.value
        assert isinstance(error, ProcessingError)
        assert error.error_code == "INVALID_PARAMETER"
        assert "Sopran0" in str(error)
        assert error.choices == ["Soprano (P1)", "Alto (P2)", "Tenor (P3)", "Bass (P4)"]
        assert error.hint

    def test_one_bad_request_among_good_ones_fails(self):
        with pytest.raises(PartSelectionError) as excinfo:
            resolve_parts(["Soprano", "Piano"], SATB)

        assert "Piano" in str(excinfo.value)

    def test_single_part_rejects_ambiguous_request(self):
        with pytest.raises(PartSelectionError) as excinfo:
            resolve_part("Alto", DIVISI)

        assert excinfo.value.choices == ["Alto I (P3)", "Alto II (P4)"]
        assert excinfo.value.error_code == "INVALID_PARAMETER"

    def test_choice_label_falls_back_to_id_when_name_is_empty(self):
        parts = [PartInfo("P1", ""), PartInfo("P2", "Alto")]

        with pytest.raises(PartSelectionError) as excinfo:
            resolve_part("Tenor", parts)

        assert excinfo.value.choices == ["P1", "Alto (P2)"]

    def test_blank_request_is_rejected(self):
        with pytest.raises(PartSelectionError):
            resolve_part("  ", SATB)


def test_resolve_part_returns_single_id():
    assert resolve_part("Tenor", SATB) == "P3"


class _FakeInstrument:
    def __init__(self, part_id):
        self.partId = part_id


class _FakePart:
    """The music21 Part attributes the adapter reads."""

    def __init__(self, music21_id, name, part_id, abbreviation=None):
        self.id = music21_id
        self.partName = name
        self.partAbbreviation = abbreviation
        self._instrument = _FakeInstrument(part_id) if part_id is not None else None

    def getInstrument(self, returnDefault=True):
        assert returnDefault is False
        return self._instrument


class TestMusic21PartInfos:
    """music21 replaces part.id with the part name, duplicates it for same-named parts and gives
    unnamed parts a new integer each parse; the MusicXML score-part id survives as
    instrument.partId (docs/research/core-library-review.md, F1)."""

    def test_uses_musicxml_part_id_not_music21_id(self):
        parts = [_FakePart("Soprano", "Soprano", "P1", "S."), _FakePart("Alto", "Alto", "P2", "A.")]

        assert music21_part_infos(parts) == [
            PartInfo("P1", "Soprano", "S."),
            PartInfo("P2", "Alto", "A."),
        ]

    def test_same_named_parts_get_distinct_ids(self):
        parts = [_FakePart("Tenor", "Tenor", "P3"), _FakePart("Tenor", "Tenor", "P4")]

        infos = music21_part_infos(parts)

        assert [i.id for i in infos] == ["P3", "P4"]
        assert resolve_part("P4", infos) == "P4"

    def test_unnamed_parts_get_stable_string_ids(self):
        parts = [_FakePart(140320038121744, None, "P1"), _FakePart(140320019650960, None, "P2")]

        assert music21_part_infos(parts) == [PartInfo("P1", ""), PartInfo("P2", "")]

    def test_missing_instrument_falls_back_to_position(self):
        parts = [_FakePart(1, None, None), _FakePart(2, "Alto", "")]

        assert [i.id for i in music21_part_infos(parts)] == ["P1", "P2"]

    def test_staves_of_one_part_use_music21_staff_ids(self):
        # A two-staff piano part becomes two PartStaff objects sharing partId "P3".
        parts = [
            _FakePart("P1", "Soprano", "P1"),
            _FakePart("P3-Staff1", "Piano", "P3"),
            _FakePart("P3-Staff2", "Piano", "P3"),
        ]

        assert [i.id for i in music21_part_infos(parts)] == ["P1", "P3-Staff1", "P3-Staff2"]

    def test_duplicate_ids_without_usable_music21_ids_are_numbered(self):
        parts = [_FakePart(11, None, "P1"), _FakePart(12, None, "P1")]

        assert [i.id for i in music21_part_infos(parts)] == ["P1-1", "P1-2"]

    def test_ids_are_unique_even_when_a_fallback_collides(self):
        parts = [_FakePart(1, None, None), _FakePart(2, None, "P1")]

        ids = [i.id for i in music21_part_infos(parts)]

        assert len(set(ids)) == 2
