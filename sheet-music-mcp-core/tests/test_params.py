"""Deprecated parameter names (docs/conventions.md, Deprecated Parameter Names)."""

import logging

import pytest

from sheet_music_mcp_core import params
from sheet_music_mcp_core.errors import ProcessingError
from sheet_music_mcp_core.params import aliased


@pytest.fixture(autouse=True)
def _reset_warnings():
    params._warned.clear()
    yield
    params._warned.clear()


def test_new_name_only():
    assert aliased({"part": "Alto"}, "part", "part_id") == "Alto"


def test_neither_name_returns_none():
    assert aliased({}, "part", "part_id") is None


def test_old_name_only_is_accepted_with_one_warning(caplog):
    caplog.set_level(logging.WARNING, logger="sheet_music_mcp_core.params")

    assert aliased({"part_id": "P2"}, "part", "part_id") == "P2"
    assert aliased({"part_id": "P3"}, "part", "part_id") == "P3"

    warnings = [r for r in caplog.records if "deprecated" in r.getMessage()]
    assert len(warnings) == 1
    assert "part_id" in warnings[0].getMessage()
    assert "part" in warnings[0].getMessage()


def test_each_deprecated_name_warns_once(caplog):
    caplog.set_level(logging.WARNING, logger="sheet_music_mcp_core.params")

    aliased({"part_id": "P2"}, "part", "part_id")
    aliased({"part_ids": ["P2"]}, "parts", "part_ids")

    assert len([r for r in caplog.records if "deprecated" in r.getMessage()]) == 2


def test_both_names_with_equal_values_are_accepted():
    assert aliased({"parts": ["P1"], "part_ids": ["P1"]}, "parts", "part_ids") == ["P1"]


def test_both_names_with_different_values_are_rejected():
    with pytest.raises(ProcessingError) as excinfo:
        aliased({"part": "Alto", "part_id": "P1"}, "part", "part_id")

    assert excinfo.value.error_code == "INVALID_PARAMETER"
    assert "part" in str(excinfo.value) and "part_id" in str(excinfo.value)
    assert excinfo.value.hint


def test_explicit_none_counts_as_absent():
    assert aliased({"part": None, "part_id": "P2"}, "part", "part_id") == "P2"
