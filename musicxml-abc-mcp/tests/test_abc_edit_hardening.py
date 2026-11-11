"""apply_abc_edit hardening (PR #201 security notes A and B): fixed parse error, input caps."""

import pytest
from sheet_music_mcp_core.errors import ProcessingError

from musicxml_abc_mcp import abc_edit
from musicxml_abc_mcp.abc_edit import apply_abc_edit

from .edit_fixtures import QUARTERS_ABC, SCORE


def _error(abc: str) -> ProcessingError:
    with pytest.raises(ProcessingError) as caught:
        apply_abc_edit(SCORE, "P2", [2, 3], abc)
    return caught.value


def _forbid_parse(monkeypatch):
    monkeypatch.setattr(abc_edit, "abc_to_musicxml", lambda tune: pytest.fail("parsed"))


def test_parse_failure_gives_a_fixed_message_without_music21_text(monkeypatch, caplog):
    def boom(tune):
        raise ProcessingError("Failed to parse ABC: music21 internal detail /tmp/secret", "INVALID_INPUT")

    monkeypatch.setattr(abc_edit, "abc_to_musicxml", boom)
    with caplog.at_level("DEBUG", logger="musicxml_abc_mcp.abc_edit"):
        error = _error(QUARTERS_ABC)

    assert error.error_code == "INVALID_INPUT"
    assert "could not be parsed" in str(error)
    assert "music21" not in str(error) and "secret" not in str(error)
    assert error.hint
    assert "music21 internal detail" in caplog.text


def test_abc_over_the_size_cap_is_rejected_before_any_parse(monkeypatch):
    _forbid_parse(monkeypatch)

    error = _error("X:1\nK:C\n" + "c" * abc_edit.MAX_ABC_CHARS)

    assert error.error_code == "INVALID_PARAMETER"
    assert "split" in error.hint.lower()


def test_more_bars_than_the_cap_is_rejected_before_any_parse(monkeypatch):
    _forbid_parse(monkeypatch)
    abc = "X:1\nM:4/4\nL:1/8\nK:C\n" + " | ".join(["c8"] * (abc_edit.MAX_EDIT_BARS + 1)) + " |]"

    error = _error(abc)

    assert error.error_code == "INVALID_PARAMETER"
    assert "split" in error.hint.lower()
