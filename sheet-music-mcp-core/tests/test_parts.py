"""Voice-part selection (docs/conventions.md, Part Selection)."""

import pytest

from sheet_music_mcp_core.errors import ProcessingError
from sheet_music_mcp_core.parts import PartInfo, PartSelectionError, resolve_part, resolve_parts

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
