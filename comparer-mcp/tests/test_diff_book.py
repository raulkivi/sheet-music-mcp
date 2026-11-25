"""DiffBook: the scores of a comparison, kept under an opaque id for the Diff Viewer."""

import pytest
from sheet_music_mcp_core.errors import ProcessingError

from comparer_mcp.diff_book import DiffBook


class TestDiffBook:
    def test_returns_what_was_remembered_under_an_opaque_id(self):
        book = DiffBook()

        diff_id = book.remember("<ref/>", "<tgt/>", {"parts": ["P1"]})
        record = book.get(diff_id)

        assert (record.reference_xml, record.target_xml, record.options) == ("<ref/>", "<tgt/>", {"parts": ["P1"]})
        assert "/" not in diff_id and len(diff_id) >= 16

    def test_ids_are_unique(self):
        book = DiffBook()

        assert book.remember("a", "b", None) != book.remember("a", "b", None)

    @pytest.mark.parametrize("bad", ["nope", "../../etc/passwd", 7, None, ["x"]])
    def test_unknown_ids_are_invalid_parameter_without_echoing_the_id(self, bad):
        with pytest.raises(ProcessingError) as caught:
            DiffBook().get(bad)

        assert caught.value.error_code == "INVALID_PARAMETER"
        assert "passwd" not in str(caught.value)

    def test_ids_expire(self):
        now = [0.0]
        book = DiffBook(ttl_seconds=10, clock=lambda: now[0])
        diff_id = book.remember("a", "b", None)

        now[0] = 11
        with pytest.raises(ProcessingError):
            book.get(diff_id)

    def test_oldest_goes_over_the_cap(self):
        book = DiffBook(max_entries=1)
        first = book.remember("a", "b", None)
        book.remember("c", "d", None)

        with pytest.raises(ProcessingError):
            book.get(first)
