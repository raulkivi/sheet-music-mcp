"""Splitting an ABC tune at its bar lines (apply_abc_edit maps ABC bars to score measures)."""

import pytest
from sheet_music_mcp_core.errors import ProcessingError

from musicxml_abc_mcp.abc_bars import split_bars

HEADER = "X:1\nT:Kyrie\nM:4/4\nL:1/8\nQ:1/4=72\nK:G\n"


def _bodies(abc: str) -> list[str]:
    return [tune.rsplit("\n", 1)[1].strip() for tune in split_bars(abc)]


def _headers(abc: str) -> list[str]:
    return [tune.rsplit("\n", 1)[0] for tune in split_bars(abc)]


class TestBars:
    def test_one_tune_per_bar(self):
        assert _bodies(HEADER + "G2 A2 B2 c2 | d8 |]") == ["G2 A2 B2 c2", "d8"]

    def test_bars_over_several_lines(self):
        assert _bodies(HEADER + "G8 |\nA8 |\nB8 |]") == ["G8", "A8", "B8"]

    def test_no_closing_bar_line(self):
        assert _bodies(HEADER + "G8 | A8") == ["G8", "A8"]

    @pytest.mark.parametrize("body", ["|: G8 :|", "G8 || A8 |]", "[| G8 | A8 :: B8 |]", "G8 |1 A8 :|2 B8 |]"])
    def test_bar_line_kinds(self, body):
        assert _bodies(HEADER + body) == {
            "|: G8 :|": ["G8"],
            "G8 || A8 |]": ["G8", "A8"],
            "[| G8 | A8 :: B8 |]": ["G8", "A8", "B8"],
            "G8 |1 A8 :|2 B8 |]": ["G8", "A8", "B8"],
        }[body]

    def test_volta_bracket_is_not_content(self):
        assert _bodies(HEADER + "G8 | [1 A8 :| [2 B8 |]") == ["G8", "A8", "B8"]

    def test_chords_quotes_and_decorations_are_not_bar_lines(self):
        abc = HEADER + '"G|D"[GBd]2 !fermata!A6 | [K:D] d8 |]'

        assert _bodies(abc) == ['"G|D"[GBd]2 !fermata!A6', "[K:D] d8"]

    def test_comments_are_dropped(self):
        assert _bodies(HEADER + "G8 | % bar two | not music\nA8 |]") == ["G8", "A8"]

    def test_lyrics_lines_are_ignored(self):
        assert _bodies(HEADER + "G4 A4 | B8 |]\nw: Ky-ri e") == ["G4 A4", "B8"]


class TestHeaders:
    def test_header_kept_without_tempo_and_with_a_free_meter(self):
        [header] = _headers(HEADER + "G8 |]")
        lines = header.splitlines()

        assert lines[0] == "X:1"
        assert "L:1/8" in lines and "K:G" == lines[-1]
        assert not any(line.startswith(("Q:", "M:4/4")) for line in lines)
        assert any(line.startswith("M:") for line in lines)

    def test_key_and_length_changes_carry_to_later_bars(self):
        headers = _headers(HEADER + "G8 |\nK:D\nL:1/4\nA2 B2 | [K:F] c4 | d4 |]")

        assert headers[0].endswith("K:G")
        assert headers[1].endswith("K:D") and "L:1/4" in headers[1]
        assert headers[3].endswith("K:F")


class TestErrors:
    def _error(self, abc: str) -> ProcessingError:
        with pytest.raises(ProcessingError) as caught:
            split_bars(abc)
        return caught.value

    def test_empty(self):
        assert self._error("  ").error_code == "INVALID_INPUT"

    def test_missing_key_line(self):
        error = self._error("X:1\nL:1/8\nG8|]")

        assert error.error_code == "INVALID_INPUT"
        assert "K:" in error.hint

    def test_several_tunes(self):
        assert self._error(HEADER + "G8|]\n\nX:2\nK:C\nC8|]").error_code == "INVALID_INPUT"

    def test_several_voices(self):
        assert self._error(HEADER + "V:1\nG8|]\nV:2\nC8|]").error_code == "INVALID_INPUT"

    def test_no_bars(self):
        assert self._error(HEADER + "|]").error_code == "INVALID_INPUT"
